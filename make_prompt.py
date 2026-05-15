"""
Generate a compact all-in-one prompt document for downstream LLM analysis.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COMPANIES_CSV = ROOT / "companies.csv"
SCORES_JSON = ROOT / "scores.json"
PROMPT_MD = ROOT / "prompt.md"

LAYER_FIELDS = [
    ("AI Revenue Tailwind", "ai_revenue_tailwind"),
    ("Pricing Power Risk", "pricing_power_risk"),
    ("Channel Control Risk", "channel_control_risk"),
    ("Composite Disruption Risk", "ai_disruption_risk"),
    ("AI Operating Leverage", "ai_operating_leverage"),
    ("Data / Distribution Moat", "data_distribution_moat"),
    ("AI Infrastructure Exposure", "ai_infrastructure_exposure"),
]


def main() -> None:
    def parse_float(value: str) -> float | None:
        return float(value) if value else None

    def parse_int(value: str) -> int | None:
        return int(value) if value else None

    with COMPANIES_CSV.open(newline="", encoding="utf-8") as f:
        companies = {row["ticker"]: row for row in csv.DictReader(f)}

    with SCORES_JSON.open(encoding="utf-8") as f:
        scores = {row["ticker"]: row for row in json.load(f)}

    records = []
    for ticker, company in companies.items():
        score = scores.get(ticker, {})
        records.append(
            {
                "ticker": ticker,
                "name": company["name"],
                "sector": company["sector"],
                "industry": company["industry"],
                "market_cap": parse_float(company["market_cap_bil_usd"]),
                "revenue": parse_float(company["revenue_bil_usd"]),
                "employees": parse_int(company["employees"]),
                "tailwind": score.get("ai_revenue_tailwind"),
                "pricing_power_risk": score.get("pricing_power_risk"),
                "channel_control_risk": score.get("channel_control_risk"),
                "disruption": score.get("ai_disruption_risk"),
                "leverage": score.get("ai_operating_leverage"),
                "moat": score.get("data_distribution_moat"),
                "infrastructure": score.get("ai_infrastructure_exposure"),
                "net": score.get("net_ai_pressure"),
                "confidence": score.get("confidence"),
                "consistency": score.get("consistency"),
                "sample_size": score.get("sample_size"),
                "metric_stddevs": score.get("metric_stddevs", {}),
                "summary": score.get("summary", ""),
                "evidence": score.get("evidence", []),
                "url": company["sec_search_url"],
            }
        )

    records.sort(key=lambda r: (-(r["market_cap"] or 0), r["name"]))
    total_cap = sum(r["market_cap"] or 0 for r in records)

    lines = [
        "# AI Shock Map for a Representative S&P 500 Set",
        "",
        "This document packages a small company universe for an AI business-model analysis. The goal is not to predict stock returns, but to compare how AI may reshape revenue, cost structure, defensibility, and infrastructure exposure.",
        "",
        f"- Companies: {len(records)}",
        f"- Total market cap represented: ${total_cap:.0f}B",
        "- Scores are 0-10 and higher means 'more of that attribute'.",
        "",
        "## Scoring dimensions",
        "",
        "- AI Revenue Tailwind: how directly AI can expand revenue opportunity",
        "- Pricing Power Risk: how much AI may weaken willingness to pay, take rates, or gross margins",
        "- Channel Control Risk: how much AI may weaken control of distribution, discovery, or workflow entry",
        "- Composite Disruption Risk: average of pricing power risk and channel control risk",
        "- AI Operating Leverage: how much internal work can be improved economically",
        "- Data / Distribution Moat: strength of workflow, data, trust, and installed-base defenses",
        "- AI Infrastructure Exposure: direct benefit from AI buildout in compute, networking, power, or enabling tools",
        "",
        "## Company table",
        "",
        "| Ticker | Company | Sector | Market Cap | Revenue | Tailwind | Pricing | Channel | Disruption | Leverage | Moat | Infra | Net |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for r in records:
        market_cap_text = f"${r['market_cap']:.0f}B" if r["market_cap"] is not None else "n/a"
        revenue_text = f"${r['revenue']:.0f}B" if r["revenue"] is not None else "n/a"
        lines.append(
            f"| {r['ticker']} | {r['name']} | {r['sector']} | "
            f"{market_cap_text} | {revenue_text} | "
            f"{r['tailwind']} | {r['pricing_power_risk']} | {r['channel_control_risk']} | {r['disruption']} | "
            f"{r['leverage']} | {r['moat']} | {r['infrastructure']} | {r['net']} |"
        )

    lines.extend(["", "## Company notes", ""])
    for r in records:
        market_cap_text = f"${r['market_cap']:.0f}B" if r["market_cap"] is not None else "n/a"
        revenue_text = f"${r['revenue']:.0f}B" if r["revenue"] is not None else "n/a"
        lines.append(f"### {r['name']} ({r['ticker']})")
        lines.append("")
        lines.append(f"- Sector / industry: {r['sector']} / {r['industry']}")
        lines.append(f"- Market cap: {market_cap_text}")
        lines.append(f"- Revenue: {revenue_text}")
        lines.append(f"- Pricing power risk: {r['pricing_power_risk']}")
        lines.append(f"- Channel control risk: {r['channel_control_risk']}")
        lines.append(f"- Composite disruption risk: {r['disruption']}")
        lines.append(f"- Confidence: {r['confidence']}")
        lines.append(f"- Consistency: {r['consistency']} across {r['sample_size']} samples")
        if r["metric_stddevs"]:
            lines.append(f"- Metric stddevs: {r['metric_stddevs']}")
        lines.append(f"- Summary: {r['summary']}")
        for item in r["evidence"]:
            lines.append(f"- Evidence: {item}")
        lines.append(f"- Filing lookup: {r['url']}")
        lines.append("")

    PROMPT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {PROMPT_MD}")


if __name__ == "__main__":
    main()
