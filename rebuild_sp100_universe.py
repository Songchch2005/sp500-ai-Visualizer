"""
Rebuild companies.csv for the current S&P 100 / OEX universe.

Sources:
- marketcap.company S&P 100 index pages for the current constituent list, sector, industry, and ranking
- stockanalysis company/statistics pages for market cap, revenue, employees, and website
- SEC company_tickers.json for CIK lookup

Usage:
    python rebuild_sp100_universe.py
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
SP100_URL = "https://marketcap.company/stock-indices/s-p-100-index-market-cap/"
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


def marketcap_client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": "Mozilla/5.0"},
        follow_redirects=True,
        timeout=45.0,
    )


def scrape_sp100_constituents(client: httpx.Client) -> list[Constituent]:
    constituents: list[Constituent] = []
    page = 1
    while True:
        url = SP100_URL if page == 1 else f"{SP100_URL}?page={page}"
        html = client.get(url).text
        soup = BeautifulSoup(html, "html.parser")
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
            name = match.group(1).strip()
            ticker = match.group(2).strip().replace("-", ".") if match.group(2).startswith("BRK-") else match.group(2).strip()
            market_cap = parse_money_to_billions(cols[3])
            constituents.append(
                Constituent(
                    ticker=ticker,
                    name=name,
                    sector=cols[4].strip(),
                    industry=cols[5].strip(),
                    market_cap_bil_usd=market_cap,
                )
            )

        if len(rows) < 50:
            break
        page += 1

    deduped: dict[str, Constituent] = {}
    for constituent in constituents:
        deduped[constituent.ticker] = constituent
    return list(deduped.values())


def load_sec_ciks(client: httpx.Client) -> dict[str, str]:
    payload = client.get(SEC_TICKERS_URL, headers={"User-Agent": "sp500-ai-map research tool contact@example.com"}).json()
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

    stats_html = client.get(stats_url).text
    company_html = client.get(company_url).text

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
    client = marketcap_client()
    constituents = scrape_sp100_constituents(client)
    if len(constituents) < 100:
        raise RuntimeError(f"expected about 100 S&P 100 constituents, found {len(constituents)}")

    cik_map = load_sec_ciks(client)
    today = date.today().isoformat()
    rows: list[dict[str, str]] = []

    for idx, constituent in enumerate(sorted(constituents, key=lambda c: c.ticker), start=1):
        metadata = fetch_stockanalysis_metadata(client, constituent.ticker)
        cik = cik_map.get(normalize_ticker(constituent.ticker), "")
        sec_search_url = (
            f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=10-k&owner=exclude&count=40"
            if cik
            else ""
        )
        market_cap = metadata["market_cap_bil_usd"] or constituent.market_cap_bil_usd
        row = {
            "ticker": constituent.ticker,
            "name": constituent.name,
            "slug": slugify_ticker(constituent.ticker),
            "sector": constituent.sector,
            "industry": constituent.industry,
            "market_cap_bil_usd": str(market_cap or ""),
            "revenue_bil_usd": str(metadata["revenue_bil_usd"] or ""),
            "employees": str(metadata["employees"] or ""),
            "cik": cik,
            "sec_search_url": sec_search_url,
            "company_url": str(metadata["company_url"] or ""),
            "market_cap_as_of": today,
            "market_cap_source_url": f"https://stockanalysis.com/stocks/{constituent.ticker.lower()}/statistics/",
        }
        rows.append(row)
        print(f"[{idx:03d}/{len(constituents)}] {constituent.ticker} {constituent.name}")
        time.sleep(0.1)

    fieldnames = list(rows[0].keys())
    with COMPANIES_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    client.close()
    print(f"Wrote {len(rows)} rows to {COMPANIES_CSV}")


if __name__ == "__main__":
    main()
