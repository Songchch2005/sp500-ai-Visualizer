"""
Rebuild companies.csv for the current S&P 500 / GSPC universe.

Sources:
- marketcap.company S&P 500 index pages for constituent list, sector, industry, and market cap
- stockanalysis company/statistics pages for revenue, employees, and company website
- SEC company_tickers.json for CIK lookup

Usage:
    python rebuild_sp500_universe.py
"""

from __future__ import annotations

import csv
import re
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
COMPANIES_CSV = ROOT / "companies.csv"
SP500_URL = "https://marketcap.company/stock-indices/s-p-500-index-market-cap/"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


@dataclass
class Constituent:
    ticker: str
    name: str
    sector: str
    industry: str
    market_cap_bil_usd: int | None


def slugify_ticker(ticker: str) -> str:
    return ticker.lower().replace(".", "-")


def clean_cell(text: str) -> str:
    return text.replace("\xa0", " ").strip()


def normalize_ticker(ticker: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", ticker.upper())


def parse_money_to_billions(text: str) -> int | None:
    match = re.search(r"\$?([0-9.,]+)\s*(Trillion|Billion|Million|T|B|M)", text, flags=re.IGNORECASE)
    if not match:
        return None
    value = float(match.group(1).replace(",", ""))
    unit = match.group(2).lower()
    if unit.startswith("trillion") or unit == "t":
        value *= 1000
    elif unit.startswith("million") or unit == "m":
        value /= 1000
    return int(round(value))


def web_client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": "Mozilla/5.0"},
        follow_redirects=True,
        timeout=45.0,
        http2=False,
    )


def get_with_retries(client: httpx.Client, url: str, attempts: int = 4) -> httpx.Response:
    last_exc: Exception | None = None
    for idx in range(attempts):
        try:
            resp = client.get(url)
            resp.raise_for_status()
            return resp
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if idx == attempts - 1:
                break
            time.sleep(min(4.0, 0.8 * (idx + 1)))
    assert last_exc is not None
    raise last_exc


def scrape_sp500_constituents(client: httpx.Client) -> list[Constituent]:
    constituents: list[Constituent] = []
    page = 1
    while True:
        url = SP500_URL if page == 1 else f"{SP500_URL}?page={page}"
        soup = BeautifulSoup(get_with_retries(client, url).text, "html.parser")
        rows = soup.select("table tbody tr")
        if not rows:
            break
        for tr in rows:
            cols = [td.get_text(" ", strip=True) for td in tr.select("td")]
            if len(cols) < 6:
                continue
            name_and_ticker = cols[1]
            match = re.search(r"^(.*?)\s+(?:NASDAQ|NYSE|NYSEARCA|AMEX):([A-Z.\-]+)$", name_and_ticker)
            if not match:
                continue
            name = clean_cell(match.group(1))
            raw_ticker = match.group(2).strip()
            ticker = raw_ticker.replace("-", ".") if raw_ticker.startswith("BRK-") else raw_ticker
            market_cap = parse_money_to_billions(cols[3])
            constituents.append(
                Constituent(
                    ticker=ticker,
                    name=name,
                    sector=clean_cell(cols[4]),
                    industry=clean_cell(cols[5]),
                    market_cap_bil_usd=market_cap,
                )
            )
        if len(rows) < 50:
            break
        page += 1
        time.sleep(0.08)

    deduped: dict[str, Constituent] = {}
    for c in constituents:
        deduped[c.ticker] = c
    return list(deduped.values())


def load_sec_ciks(client: httpx.Client) -> dict[str, str]:
    payload = get_with_retries(
        client,
        SEC_TICKERS_URL,
    ).json()
    mapping: dict[str, str] = {}
    for row in payload.values():
        ticker = row.get("ticker")
        cik = row.get("cik_str")
        if ticker and cik:
            mapping[normalize_ticker(ticker)] = str(cik)
    return mapping


def parse_table_map(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    mapping: dict[str, str] = {}
    for tr in soup.select("table tr"):
        cells = tr.select("td")
        if len(cells) < 2:
            continue
        key = cells[0].get_text(" ", strip=True)
        value = cells[1].get_text(" ", strip=True)
        if key and value:
            mapping[key] = value
    return mapping


def fetch_stockanalysis_metadata(client: httpx.Client, ticker: str) -> dict[str, str | int | None]:
    ticker_path = ticker.lower()
    stats_url = f"https://stockanalysis.com/stocks/{ticker_path}/statistics/"
    company_url = f"https://stockanalysis.com/stocks/{ticker_path}/company/"

    stats_html = get_with_retries(client, stats_url).text
    company_html = get_with_retries(client, company_url).text

    stats_map = parse_table_map(stats_html)
    company_map = parse_table_map(company_html)
    company_soup = BeautifulSoup(company_html, "html.parser")

    website = ""
    website_row = company_soup.find("td", string=re.compile(r"Website", re.IGNORECASE))
    if website_row:
        link = website_row.find_parent("tr").select_one("a[href]")
        if link and link.get("href"):
            website = link["href"].strip()

    revenue = parse_money_to_billions(stats_map.get("Revenue", "") or stats_map.get("Revenue (ttm)", ""))
    market_cap = parse_money_to_billions(stats_map.get("Market Cap", ""))
    employees_text = stats_map.get("Employee Count") or company_map.get("Employees") or ""
    employees = int(employees_text.replace(",", "")) if employees_text and employees_text.replace(",", "").isdigit() else None

    return {
        "market_cap_bil_usd": market_cap,
        "revenue_bil_usd": revenue,
        "employees": employees,
        "company_url": website,
    }


def main() -> None:
    client = web_client()
    constituents = scrape_sp500_constituents(client)
    if len(constituents) < 490:
        raise RuntimeError(f"expected about 500 S&P constituents, found {len(constituents)}")

    cik_map = load_sec_ciks(client)
    today = date.today().isoformat()
    rows: list[dict[str, str]] = []

    universe = sorted(constituents, key=lambda c: c.ticker)
    for idx, c in enumerate(universe, start=1):
        try:
            metadata = fetch_stockanalysis_metadata(client, c.ticker)
        except Exception:
            metadata = {
                "market_cap_bil_usd": None,
                "revenue_bil_usd": None,
                "employees": None,
                "company_url": "",
            }
        cik = cik_map.get(normalize_ticker(c.ticker), "")
        sec_search_url = (
            f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=10-k&owner=exclude&count=40"
            if cik
            else ""
        )
        market_cap = metadata["market_cap_bil_usd"] or c.market_cap_bil_usd
        rows.append(
            {
                "ticker": c.ticker,
                "name": c.name,
                "slug": slugify_ticker(c.ticker),
                "sector": c.sector,
                "industry": c.industry,
                "market_cap_bil_usd": str(market_cap or ""),
                "revenue_bil_usd": str(metadata["revenue_bil_usd"] or ""),
                "employees": str(metadata["employees"] or ""),
                "cik": cik,
                "sec_search_url": sec_search_url,
                "company_url": str(metadata["company_url"] or ""),
                "market_cap_as_of": today,
                "market_cap_source_url": f"https://stockanalysis.com/stocks/{c.ticker.lower()}/statistics/",
            }
        )
        print(f"[{idx:03d}/{len(universe)}] {c.ticker} {c.name}".encode("ascii", "replace").decode("ascii"))
        time.sleep(0.06)

    with COMPANIES_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    client.close()
    print(f"Wrote {len(rows)} rows to {COMPANIES_CSV}")


if __name__ == "__main__":
    main()
