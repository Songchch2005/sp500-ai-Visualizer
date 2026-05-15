"""
Merge company metadata and multi-factor AI scores into site/data.json.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COMPANIES_CSV = ROOT / "companies.csv"
SCORES_JSON = ROOT / "scores.json"
FILINGS_DIR = ROOT / "filings"
SITE_JSON = ROOT / "site" / "data.json"
SITE_JS = ROOT / "site" / "data.js"
NUMERIC_SCORE_FIELDS = [
    "tailwind",
    "pricing_power_risk",
    "channel_control_risk",
    "disruption",
    "leverage",
    "moat",
    "infrastructure",
    "confidence",
    "consistency",
    "sample_size",
    "net_ai_pressure",
]


def to_float(value: str) -> float | None:
    return float(value) if value else None


def to_int(value: str) -> int | None:
    return int(value) if value else None


def composite_index(
    tailwind: float | None,
    pricing_power_risk: float | None,
    channel_control_risk: float | None,
    leverage: float | None,
    moat: float | None,
    infrastructure: float | None,
) -> float | None:
    values = [tailwind, pricing_power_risk, channel_control_risk, leverage, moat, infrastructure]
    if any(v is None for v in values):
        return None
    # 0..10 scale: higher means stronger net AI business position.
    score = (
        0.30 * float(tailwind)
        + 0.20 * float(leverage)
        + 0.25 * float(moat)
        + 0.15 * float(infrastructure)
        + 0.05 * (10.0 - float(pricing_power_risk))
        + 0.05 * (10.0 - float(channel_control_risk))
    )
    return round(max(0.0, min(10.0, score)), 2)


def entity_key(ticker: str) -> str:
    if ticker in {"GOOG", "GOOGL"}:
        return "ALPHABET"
    return ticker


def weighted_mean(items: list[dict], field: str) -> float | None:
    pairs = []
    for item in items:
        value = item.get(field)
        cap = item.get("market_cap")
        if value is None:
            continue
        if cap is None or cap <= 0:
            cap = 1
        pairs.append((float(value), float(cap)))
    if not pairs:
        return None
    total_w = sum(weight for _, weight in pairs)
    return sum(value * weight for value, weight in pairs) / total_w


def merge_entity_rows(items: list[dict]) -> dict:
    if len(items) == 1:
        one = dict(items[0])
        one["share_classes"] = [one["ticker"]]
        one["ai_composite_index"] = composite_index(
            one.get("tailwind"),
            one.get("pricing_power_risk"),
            one.get("channel_control_risk"),
            one.get("leverage"),
            one.get("moat"),
            one.get("infrastructure"),
        )
        return one

    # Prefer the Class A row as canonical metadata when present.
    preferred = next((item for item in items if item["ticker"] == "GOOGL"), items[0])
    merged = dict(preferred)
    merged["ticker"] = "GOOGL+GOOG"
    merged["slug"] = "alphabet-combined"
    merged["title"] = "Alphabet Inc"
    merged["share_classes"] = sorted(item["ticker"] for item in items)
    # Market-cap providers often repeat total-company cap on both share classes.
    # Use max rather than sum to avoid double counting GOOG/GOOGL.
    merged["market_cap"] = max((item.get("market_cap") or 0) for item in items)

    # Keep non-additive business metadata from the preferred class.
    for field in NUMERIC_SCORE_FIELDS:
        v = weighted_mean(items, field)
        if v is None:
            merged[field] = None
        elif field == "sample_size":
            merged[field] = int(round(v))
        else:
            merged[field] = round(v, 2)

    # Merge evidence de-duplicated, capped for readability.
    evidence: list[str] = []
    for item in items:
        for line in item.get("evidence", []):
            if line and line not in evidence:
                evidence.append(line)
    merged["evidence"] = evidence[:8]
    merged["filing_source_note"] = "Merged GOOG and GOOGL into one Alphabet business entity."
    merged["ai_composite_index"] = composite_index(
        merged.get("tailwind"),
        merged.get("pricing_power_risk"),
        merged.get("channel_control_risk"),
        merged.get("leverage"),
        merged.get("moat"),
        merged.get("infrastructure"),
    )
    return merged


def main() -> None:
    with COMPANIES_CSV.open(newline="", encoding="utf-8") as f:
        companies = list(csv.DictReader(f))

    with SCORES_JSON.open(encoding="utf-8") as f:
        scores = {row["ticker"]: row for row in json.load(f)}

    filings = {}
    for path in FILINGS_DIR.glob("*.json"):
        try:
            filings[path.stem] = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

    raw_data = []
    for row in companies:
        ticker = row["ticker"]
        score = scores.get(ticker, {})
        filing = filings.get(row["slug"], {})
        raw_data.append(
            {
                "ticker": ticker,
                "title": row["name"],
                "slug": row["slug"],
                "sector": row["sector"],
                "industry": row["industry"],
                "market_cap": to_float(row["market_cap_bil_usd"]),
                "revenue": to_float(row["revenue_bil_usd"]),
                "employees": to_int(row["employees"]),
                "tailwind": score.get("ai_revenue_tailwind"),
                "pricing_power_risk": score.get("pricing_power_risk"),
                "channel_control_risk": score.get("channel_control_risk"),
                "disruption": score.get("ai_disruption_risk"),
                "leverage": score.get("ai_operating_leverage"),
                "moat": score.get("data_distribution_moat"),
                "infrastructure": score.get("ai_infrastructure_exposure"),
                "confidence": score.get("confidence"),
                "consistency": score.get("consistency"),
                "sample_size": score.get("sample_size"),
                "metric_means": score.get("metric_means", {}),
                "metric_stddevs": score.get("metric_stddevs", {}),
                "metric_ranges": score.get("metric_ranges", {}),
                "net_ai_pressure": score.get("net_ai_pressure"),
                "summary": score.get("summary", ""),
                "evidence": score.get("evidence", []),
                "filing_source": filing.get("source", "unknown"),
                "filing_source_note": filing.get("source_note", ""),
                "filing_date": filing.get("filing_date", ""),
                "url": filing.get("source_url") or row["sec_search_url"],
                "company_url": row["company_url"],
            }
        )

    grouped: dict[str, list[dict]] = {}
    for item in raw_data:
        key = entity_key(item["ticker"])
        grouped.setdefault(key, []).append(item)

    data = [merge_entity_rows(items) for items in grouped.values()]
    data.sort(key=lambda d: (d.get("market_cap") or 0), reverse=True)

    SITE_JSON.parent.mkdir(exist_ok=True)
    with SITE_JSON.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    with SITE_JS.open("w", encoding="utf-8") as f:
        f.write("window.__SITE_DATA__ = ")
        json.dump(data, f, ensure_ascii=False)
        f.write(";\n")

    print(f"Wrote {len(data)} companies to {SITE_JSON}")
    total_cap = sum(d["market_cap"] or 0 for d in data)
    print(f"Total market cap represented: ${total_cap:.0f}B")


if __name__ == "__main__":
    main()
