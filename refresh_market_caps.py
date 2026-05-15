"""
Refresh market_cap_bil_usd in companies.csv from CompaniesMarketCap.

Usage:
    python refresh_market_caps.py
"""

from __future__ import annotations

import csv
import re
from datetime import date
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
COMPANIES_CSV = ROOT / "companies.csv"

MARKET_CAP_URLS = {
    "MSFT": "https://companiesmarketcap.com/microsoft/marketcap/",
    "AAPL": "https://companiesmarketcap.com/apple/marketcap/",
    "NVDA": "https://companiesmarketcap.com/nvidia/marketcap/",
    "AMZN": "https://companiesmarketcap.com/amazon/marketcap/",
    "GOOGL": "https://companiesmarketcap.com/alphabet-google/marketcap/",
    "META": "https://companiesmarketcap.com/meta-platforms/marketcap/",
    "TSLA": "https://companiesmarketcap.com/tesla/marketcap/",
    "JPM": "https://companiesmarketcap.com/jp-morgan-chase/marketcap/",
    "V": "https://companiesmarketcap.com/visa/marketcap/",
    "UNH": "https://companiesmarketcap.com/united-health/marketcap/",
    "LLY": "https://companiesmarketcap.com/eli-lilly/marketcap/",
    "XOM": "https://companiesmarketcap.com/exxon-mobil/marketcap/",
    "CAT": "https://companiesmarketcap.com/caterpillar/marketcap/",
    "WMT": "https://companiesmarketcap.com/walmart/marketcap/",
    "COST": "https://companiesmarketcap.com/costco/marketcap/",
    "NEE": "https://companiesmarketcap.com/nextera-energy/marketcap/",
}


def parse_cap_to_billions(html: str) -> float:
    match = re.search(r'content="As of .*? has a market cap of \$([0-9.,]+)\s*(Trillion|Billion|Million) USD', html, flags=re.IGNORECASE)
    if not match:
        raise ValueError("could not parse market cap from page")
    value = float(match.group(1).replace(",", ""))
    unit = match.group(2).lower()
    if unit.startswith("trillion"):
        return round(value * 1000, 0)
    if unit.startswith("billion"):
        return round(value, 0)
    return round(value / 1000, 0)


def main() -> None:
    rows = []
    with COMPANIES_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys())

    client = httpx.Client(headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    today = date.today().isoformat()
    for row in rows:
        ticker = row["ticker"]
        url = MARKET_CAP_URLS[ticker]
        html = client.get(url).text
        cap = parse_cap_to_billions(html)
        row["market_cap_bil_usd"] = str(int(cap))
        row["market_cap_as_of"] = today
        row["market_cap_source_url"] = url
        print(f"{ticker}: ${int(cap)}B")
    client.close()

    with COMPANIES_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
