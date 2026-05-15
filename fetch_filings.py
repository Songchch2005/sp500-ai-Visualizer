"""
Fetch or seed business/risk summaries for representative S&P 500 companies.

When run without flags, the script attempts to pull the latest 10-K metadata and
extract rough Item 1 and Item 1A text from SEC EDGAR. Because SEC text layouts
vary by filer, this extractor is intentionally conservative and falls back to a
manual seed summary when extraction fails.

Usage:
    uv run python fetch_filings.py
    uv run python fetch_filings.py --seed
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent
COMPANIES_CSV = ROOT / "companies.csv"
FILINGS_DIR = ROOT / "filings"
PAGES_DIR = ROOT / "company_pages"
SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_ARCHIVES = "https://www.sec.gov/Archives/edgar/data/{cik_nolead}/{accession_nodash}/{primary_doc}"
USER_AGENT = os.getenv("SEC_USER_AGENT", "sp500-ai-map research tool contact@example.com")

BUSINESS_HTML_PATTERNS = [
    r"ITEM\s*1[\s\.\-–—:]*BUSINESS",
    r"ITEM\s*1[\s\.\-–—:]*BUSINESS\s+AND\s+PROPERTIES",
    r"ITEM\s*1\..{0,400}?USINESS",
]
BUSINESS_TEXT_PATTERNS = [
    r"item\s*1[\s\.\-:]*b\s*u\s*s\s*i\s*n\s*e\s*s\s*s",
    r"item\s*1[\s\.\-:]*business",
    r"part\s*i[\s\.\-:]*item\s*1",
]
RISK_HTML_PATTERNS = [
    r"ITEM\s*1A[\s\.\-–—:]*RISK\s+FACTORS",
    r"ITEM\s*1A\..{0,500}?RISK.{0,120}?FACTORS",
]
RISK_TEXT_PATTERNS = [
    r"item\s*1a[\s\.\-:]*r\s*i\s*s\s*k[\s\.\-:]*f\s*a\s*c\s*t\s*o\s*r\s*s",
    r"item\s*1a[\s\.\-:]*risk.{0,80}?factors",
]
ITEM2_HTML_PATTERNS = [
    r"ITEM\s*1B[\s\.\-–—:]*",
    r"ITEM\s*2[\s\.\-–—:]*",
]
ITEM2_TEXT_PATTERNS = [
    r"item\s*1b[\s\.\-:]",
    r"item\s*2[\s\.\-:]",
]
BUSINESS_TEXT_FALLBACKS = {
    "MSFT": r"committed to making digital technology and artificial intelligence",
    "AMZN": r"General\s+We seek to be Earth",
    "COST": r"Item 1[—\-–]?Business Costco Wholesale Corporation",
}
RISK_TEXT_FALLBACKS = {
    "MSFT": r"We face intense competition across all markets for our products and services",
    "AMZN": r"We face intense competition",
    "CAT": r"The demand for our products and services tends to be cyclical",
    "COST": r"Our growth depends on maintaining positive relationships",
}


@dataclass
class Company:
    ticker: str
    name: str
    slug: str
    sector: str
    industry: str
    market_cap_bil_usd: float | None
    revenue_bil_usd: float | None
    employees: int | None
    cik: str
    sec_search_url: str
    company_url: str


SEED_SUMMARIES: dict[str, dict[str, str]] = {
    "MSFT": {
        "business": (
            "Microsoft sells cloud infrastructure, enterprise software, productivity applications, "
            "developer tooling, gaming, and security products. Azure, Microsoft 365, GitHub, "
            "Windows, and data-platform products make the company deeply embedded in customer workflows."
        ),
        "risk": (
            "Key risks include platform competition, cloud pricing pressure, regulatory scrutiny, "
            "cybersecurity incidents, and the need to keep AI products economically attractive while "
            "funding heavy data-center investment."
        ),
        "ai_notes": (
            "Microsoft has both direct AI demand exposure through Azure and Copilot and internal leverage "
            "through software-heavy operations. It also depends on sustained capex discipline and partner "
            "ecosystems to translate model demand into durable profit pools."
        ),
    },
    "AAPL": {
        "business": (
            "Apple earns most of its revenue from iPhone, supplemented by Mac, iPad, wearables, and a large "
            "services business spanning app distribution, subscriptions, payments, and device support. Its "
            "business model is centered on premium hardware, integrated software, and a tightly controlled ecosystem."
        ),
        "risk": (
            "Important risks include consumer hardware cycles, supply-chain concentration, app-store and antitrust "
            "pressure, dependence on new device refreshes, and the possibility that AI shifts value toward cloud "
            "assistants rather than local device features."
        ),
        "ai_notes": (
            "Apple may use AI to improve devices and services, but it is less of a pure AI revenue beneficiary "
            "than infrastructure or software vendors. The core strategic question is whether AI becomes another "
            "premium ecosystem feature or weakens the importance of the device shell."
        ),
    },
    "NVDA": {
        "business": (
            "NVIDIA designs GPUs, accelerated computing systems, networking hardware, and software platforms used "
            "in AI training, inference, gaming, simulation, and industrial computing. Revenue is now dominated by "
            "data-center demand tied to hyperscalers and enterprise AI deployments."
        ),
        "risk": (
            "Major risks include customer concentration, export controls, supply constraints, large-capex cyclicality, "
            "intense semiconductor competition, and the possibility that model economics shift toward lower-cost compute."
        ),
        "ai_notes": (
            "NVIDIA is the clearest direct AI infrastructure beneficiary in the MVP set. The interesting research angle "
            "is not whether AI matters, but how durable its platform moat remains as customers push on pricing and "
            "alternative silicon stacks mature."
        ),
    },
    "AMZN": {
        "business": (
            "Amazon combines first-party and third-party e-commerce, logistics, advertising, subscriptions, and AWS cloud "
            "infrastructure. It operates at global scale across retail operations, fulfillment, enterprise cloud, and digital services."
        ),
        "risk": (
            "Risks include retail margin pressure, labor and logistics complexity, antitrust scrutiny, cloud competition, "
            "capital intensity, and platform abuse or trust issues across marketplace businesses."
        ),
        "ai_notes": (
            "Amazon has both AI tailwind and operating leverage angles: AWS can sell AI infrastructure while the retail "
            "business can automate planning, service, and logistics. The key uncertainty is whether AI monetization is "
            "captured mostly in cloud or diffuses into lower-margin commerce improvements."
        ),
    },
    "GOOGL": {
        "business": (
            "Alphabet generates most revenue from digital advertising tied to search, YouTube, and network properties, "
            "with cloud services and other bets adding smaller but strategic revenue streams. Search distribution and user "
            "intent data are central to the model."
        ),
        "risk": (
            "Core risks include advertising cyclicality, antitrust and distribution remedies, shifts in search behavior, "
            "rising traffic acquisition costs, cloud competition, and AI answers potentially reducing traditional search monetization."
        ),
        "ai_notes": (
            "Alphabet has enormous AI capability and data advantages, but it also faces unusually direct disruption risk "
            "because AI changes how users seek information. The central question is whether it re-bundles AI into search "
            "economics faster than AI erodes high-margin query monetization."
        ),
    },
    "META": {
        "business": (
            "Meta monetizes consumer attention through advertising across Facebook, Instagram, WhatsApp, and Messenger, "
            "while investing heavily in AI infrastructure and Reality Labs. Targeting, ranking, and engagement systems "
            "are already software-and-data intensive."
        ),
        "risk": (
            "Risks include ad-market cyclicality, privacy and platform-policy changes, large infrastructure spend, "
            "regulatory scrutiny, content moderation costs, and uncertain returns from experimental products."
        ),
        "ai_notes": (
            "Meta has a strong AI tailwind in ad relevance and content generation, plus internal leverage across support, "
            "creator tools, and moderation workflows. It still needs to prove that higher AI capex translates into durable "
            "cash-generation rather than just a more expensive version of the same ad machine."
        ),
    },
    "TSLA": {
        "business": (
            "Tesla sells electric vehicles, energy storage, charging, and related software-enabled services. Its long-term "
            "strategy relies on manufacturing scale, vehicle software, autonomy ambitions, and energy ecosystem expansion."
        ),
        "risk": (
            "Major risks include vehicle pricing pressure, manufacturing execution, regulation, safety claims around autonomy, "
            "battery supply, and intense global automotive competition."
        ),
        "ai_notes": (
            "Tesla's AI story is concentrated in autonomy, robotics, and software differentiation rather than pure language-model "
            "economics. That creates potentially high upside in AI-driven products, but also a long timing risk between research "
            "claims and commercially reliable deployment."
        ),
    },
    "JPM": {
        "business": (
            "JPMorgan Chase operates consumer banking, credit cards, payments, investment banking, trading, asset management, "
            "and treasury services. The franchise combines huge balance-sheet scale with complex operational and regulatory processes."
        ),
        "risk": (
            "Risks include credit losses, market shocks, compliance failures, cyber threats, capital rules, and pressure on fees "
            "and spreads across highly competitive financial products."
        ),
        "ai_notes": (
            "JPM is a strong operating-leverage candidate because so much work involves documents, workflows, fraud detection, "
            "service operations, and internal analysis. AI disruption to the bank's own products is more limited than for software "
            "or media companies, but AI may still compress some advisory and information-service economics over time."
        ),
    },
    "V": {
        "business": (
            "Visa runs a global electronic payments network connecting consumers, merchants, banks, and processors. Its model is "
            "built on transaction volume, acceptance ubiquity, trust, and network effects rather than credit risk."
        ),
        "risk": (
            "Key risks include regulation of interchange and routing, competitive payment rails, cyber events, cross-border weakness, "
            "and shifts in how commerce is initiated or embedded in software."
        ),
        "ai_notes": (
            "Visa can benefit from AI in fraud detection, merchant tooling, and smarter commerce workflows, but it is not a direct "
            "AI infrastructure play. The interesting question is whether AI assistants strengthen network incumbents or route around "
            "them through new agentic payment layers."
        ),
    },
    "UNH": {
        "business": (
            "UnitedHealth combines insurance, care delivery, pharmacy-benefit functions, and health-services operations through "
            "UnitedHealthcare and Optum. The business is administrative, regulated, and rich in claims and clinical workflow data."
        ),
        "risk": (
            "Important risks include reimbursement pressure, regulatory changes, medical-cost trends, public scrutiny of claims and "
            "benefit practices, cyber incidents, and integration complexity across health-service businesses."
        ),
        "ai_notes": (
            "UNH has substantial AI operating-leverage potential in coding, prior authorization, service operations, and care-management "
            "workflows. At the same time, healthcare regulation, patient safety, and reputational risk place clear limits on how fast "
            "AI can replace human oversight."
        ),
    },
    "LLY": {
        "business": (
            "Eli Lilly develops, manufactures, and commercializes branded pharmaceuticals, with value tied to research pipelines, "
            "clinical execution, manufacturing capacity, and intellectual property."
        ),
        "risk": (
            "Risks include trial failures, patent cliffs, pricing and reimbursement pressure, manufacturing constraints, safety signals, "
            "and concentration in a small number of major products."
        ),
        "ai_notes": (
            "AI can improve discovery, trial design, and commercial analytics, but most economic value still depends on biology, "
            "regulation, and manufacturing execution. Lilly therefore looks more like a moderate AI leverage story than a direct "
            "AI disruption target."
        ),
    },
    "XOM": {
        "business": (
            "Exxon Mobil spans upstream oil and gas production, refining, chemicals, and trading. The company is asset-heavy, "
            "operationally complex, and highly exposed to commodity cycles and project execution."
        ),
        "risk": (
            "Core risks include commodity-price volatility, geopolitical exposure, environmental regulation, project delays, "
            "accidents, and the long-term energy-transition debate."
        ),
        "ai_notes": (
            "Exxon is not a direct AI beneficiary in the software sense, but AI can improve field optimization, maintenance, and "
            "commercial planning. AI's role is mostly incremental operating leverage rather than existential business-model pressure."
        ),
    },
    "CAT": {
        "business": (
            "Caterpillar sells heavy equipment, engines, services, and financing tied to construction, mining, and energy end markets. "
            "Its model combines industrial hardware, dealer networks, installed-base service, and parts."
        ),
        "risk": (
            "Risks include cyclical end demand, dealer health, supply-chain and input-cost pressure, product reliability, financing risk, "
            "and global trade exposure."
        ),
        "ai_notes": (
            "Caterpillar can use AI in predictive maintenance, fleet optimization, and autonomous equipment, but adoption is anchored to "
            "physical assets and safety requirements. That usually means a slower but still meaningful AI curve."
        ),
    },
    "WMT": {
        "business": (
            "Walmart operates large-scale retail stores, e-commerce, advertising, and logistics networks with a model built on assortment, "
            "price, convenience, and supply-chain execution."
        ),
        "risk": (
            "Major risks include thin retail margins, labor costs, inventory mistakes, e-commerce competition, regulation, and execution "
            "challenges across omnichannel fulfillment."
        ),
        "ai_notes": (
            "Walmart has broad AI operating-leverage opportunities across forecasting, service, merchandising, and logistics. AI is more "
            "likely to improve productivity than to directly disrupt the core low-price retail proposition."
        ),
    },
    "COST": {
        "business": (
            "Costco runs a membership-driven warehouse retail model with high traffic, limited assortment, and unusually strong customer "
            "trust. Economics rely on membership fees, disciplined merchandising, and high inventory turns."
        ),
        "risk": (
            "Risks include traffic softness, supplier and inventory pressure, wage inflation, international execution issues, and mistakes "
            "that weaken the value proposition or membership renewal behavior."
        ),
        "ai_notes": (
            "Costco can apply AI to supply chain and back-office efficiency, but its moat remains physical buying scale and member loyalty. "
            "AI disruption risk is lower than for digital-first businesses."
        ),
    },
    "NEE": {
        "business": (
            "NextEra Energy combines regulated electric utility operations with renewable-generation development. Value comes from rate-base "
            "growth, project execution, capital access, grid planning, and reliable operations."
        ),
        "risk": (
            "Key risks include regulation, storm and reliability events, financing costs, construction delays, power-price changes, and "
            "the need to match renewable growth with transmission and storage economics."
        ),
        "ai_notes": (
            "NextEra has moderate infrastructure relevance because AI data-center demand can increase power needs, but its economics are still "
            "mostly governed by regulation and capital-intensive utility execution. AI is more a demand and planning factor than a core product."
        ),
    },
}


def load_companies() -> list[Company]:
    def parse_float(value: str) -> float | None:
        return float(value) if value else None

    def parse_int(value: str) -> int | None:
        return int(value) if value else None

    rows = []
    with COMPANIES_CSV.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(
                Company(
                    ticker=row["ticker"],
                    name=row["name"],
                    slug=row["slug"],
                    sector=row["sector"],
                    industry=row["industry"],
                    market_cap_bil_usd=parse_float(row["market_cap_bil_usd"]),
                    revenue_bil_usd=parse_float(row["revenue_bil_usd"]),
                    employees=parse_int(row["employees"]),
                    cik=row["cik"],
                    sec_search_url=row["sec_search_url"],
                    company_url=row["company_url"],
                )
            )
    return rows


def parse_ticker_filter(raw: str | None) -> set[str]:
    if not raw:
        return set()
    parts = [part.strip().upper() for part in raw.split(",")]
    return {part for part in parts if part}


def select_companies(
    companies: list[Company],
    tickers: set[str],
    only_seed: bool,
) -> list[Company]:
    selected = companies
    if tickers:
        selected = [company for company in selected if company.ticker.upper() in tickers]
    if only_seed:
        seeded: list[Company] = []
        for company in selected:
            filing_path = FILINGS_DIR / f"{company.slug}.json"
            if not filing_path.exists():
                seeded.append(company)
                continue
            try:
                payload = json.loads(filing_path.read_text(encoding="utf-8"))
            except Exception:
                seeded.append(company)
                continue
            if payload.get("source") != "sec_10k":
                seeded.append(company)
        selected = seeded
    return selected


def edgar_client() -> httpx.Client:
    return httpx.Client(
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "gzip, deflate",
            "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
        },
        follow_redirects=True,
        http2=False,
        timeout=45.0,
    )


def get_with_retries(client: httpx.Client, url: str, attempts: int = 5) -> httpx.Response:
    last_exc: Exception | None = None
    for idx in range(attempts):
        try:
            response = client.get(url)
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if idx == attempts - 1:
                break
            time.sleep(min(6, 1.2 * (idx + 1)))
    assert last_exc is not None
    raise last_exc


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def strip_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "table"]):
        tag.decompose()
    text = soup.get_text("\n")
    lines = [clean_text(line) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def extract_between(text: str, start_pat: str, end_pat: str) -> str | None:
    start = re.search(start_pat, text, flags=re.IGNORECASE)
    if not start:
        return None
    tail = text[start.end():]
    end = re.search(end_pat, tail, flags=re.IGNORECASE)
    if not end:
        return clean_text(tail[:12000])
    return clean_text(tail[: end.start()][:12000])


def text_section_from_patterns(text: str, start_patterns: list[str], end_patterns: list[str]) -> str | None:
    start = last_match(start_patterns, text)
    if not start:
        return None
    end = first_match_after(end_patterns, text, start.end())
    segment = text[start.start(): end.start() if end else start.start() + 16000]
    return clean_text(segment[:10000]) if segment else None


def best_text_section(
    text: str,
    start_patterns: list[str],
    end_patterns: list[str],
    min_chars: int = 800,
    max_chars: int = 12000,
) -> str | None:
    candidates: list[str] = []
    for pattern in start_patterns:
        for start in re.finditer(pattern, text, flags=re.IGNORECASE | re.DOTALL):
            end = first_match_after(end_patterns, text, start.end())
            segment = text[start.start(): end.start() if end else start.start() + (max_chars * 3)]
            cleaned = clean_text(segment[:max_chars])
            if len(cleaned) >= min_chars:
                candidates.append(cleaned)
    if not candidates:
        return None
    return max(candidates, key=len)


def find_dense_window(text: str, anchors: list[str], window_chars: int = 4500) -> str | None:
    candidates: list[tuple[int, str]] = []
    lowered = text.lower()
    for anchor in anchors:
        if not anchor:
            continue
        start = lowered.find(anchor.lower())
        if start < 0:
            continue
        segment = clean_text(text[start:start + window_chars])
        if len(segment) < 700:
            continue
        # prefer narrative-heavy text windows over table-like noise
        alpha = sum(ch.isalpha() for ch in segment)
        score = alpha + (segment.count(".") * 20)
        candidates.append((score, segment))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    return candidates[0][1]


def fallback_business_section(company: Company, text: str) -> str | None:
    first_name = company.name.split()[0].lower() if company.name else ""
    anchors = [
        "part i",
        "item 1",
        "items 1 and 2",
        "business",
        "business overview",
        "our business",
        first_name,
    ]
    return find_dense_window(text, anchors, window_chars=5000)


def fallback_risk_section(text: str) -> str | None:
    return find_dense_window(
        text,
        [
            "item 1a",
            "risk factors",
            "factors that may affect future results",
            "cautionary statement",
        ],
        window_chars=5500,
    )


def latest_10k_metadata(client: httpx.Client, company: Company) -> dict[str, str] | None:
    url = SEC_SUBMISSIONS.format(cik=company.cik.zfill(10))
    data = get_with_retries(client, url).json()
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accession_numbers = recent.get("accessionNumber", [])
    filing_dates = recent.get("filingDate", [])
    primary_docs = recent.get("primaryDocument", [])
    rows = list(zip(forms, accession_numbers, filing_dates, primary_docs))
    preferred = [row for row in rows if row[0] == "10-K"] or [row for row in rows if row[0] == "10-K/A"]
    if preferred:
        form, accession, filing_date, primary_doc = preferred[0]
        accession_nodash = accession.replace("-", "")
        return {
            "form": form,
            "filing_date": filing_date,
            "accession": accession,
            "primary_doc": primary_doc,
            "filing_url": SEC_ARCHIVES.format(
                cik_nolead=str(int(company.cik)),
                accession_nodash=accession_nodash,
                primary_doc=primary_doc,
            ),
        }
    return None


def last_match(patterns: list[str], html: str) -> re.Match[str] | None:
    matches: list[re.Match[str]] = []
    for pattern in patterns:
        matches.extend(re.finditer(pattern, html, flags=re.IGNORECASE | re.DOTALL))
    return matches[-1] if matches else None


def first_match_after(patterns: list[str], html: str, start: int) -> re.Match[str] | None:
    matches: list[re.Match[str]] = []
    for pattern in patterns:
        for match in re.finditer(pattern, html, flags=re.IGNORECASE | re.DOTALL):
            if match.start() > start:
                matches.append(match)
    matches.sort(key=lambda m: m.start())
    return matches[0] if matches else None


def html_section(html: str, start_patterns: list[str], end_patterns: list[str]) -> str | None:
    start = last_match(start_patterns, html)
    if not start:
        return None
    end = first_match_after(end_patterns, html, start.end())
    segment = html[start.start(): end.start() if end else start.start() + 180000]
    text = strip_html(segment)
    return clean_text(text[:10000]) if text else None


def text_section(text: str, start_pattern: str, end_pattern: str | None = None) -> str | None:
    start = re.search(start_pattern, text, flags=re.IGNORECASE)
    if not start:
        return None
    tail = text[start.start():]
    if end_pattern:
        end = re.search(end_pattern, tail, flags=re.IGNORECASE)
        tail = tail[:end.start()] if end else tail[:10000]
    return clean_text(tail[:10000]) if tail else None


def summarize_from_text(company: Company, filing_meta: dict[str, str], filing_html: str) -> dict[str, str]:
    text = strip_html(filing_html)
    business = best_text_section(text, BUSINESS_TEXT_PATTERNS, RISK_TEXT_PATTERNS, min_chars=900)
    if not business:
        business = html_section(filing_html, BUSINESS_HTML_PATTERNS, RISK_HTML_PATTERNS)
    if not business:
        business = text_section_from_patterns(text, BUSINESS_TEXT_PATTERNS, RISK_TEXT_PATTERNS)
    if not business and company.ticker in BUSINESS_TEXT_FALLBACKS:
        business = text_section(text, BUSINESS_TEXT_FALLBACKS[company.ticker], r"item\s*1a.{0,30}?risk factors|item\s*2[\s\.\-??:]")
    if not business:
        business = extract_between(text, r"item\s*1.{0,30}?business", r"item\s*1a.{0,30}?risk factors")
    if not business:
        business = fallback_business_section(company, text)

    risks = best_text_section(text, RISK_TEXT_PATTERNS, ITEM2_TEXT_PATTERNS, min_chars=900)
    if not risks:
        risks = html_section(filing_html, RISK_HTML_PATTERNS, ITEM2_HTML_PATTERNS)
    if not risks:
        risks = text_section_from_patterns(text, RISK_TEXT_PATTERNS, ITEM2_TEXT_PATTERNS)
    if risks and (len(risks) < 220 or "2025 COMPARED WITH 2024" in risks):
        risks = None
    if not risks and company.ticker in RISK_TEXT_FALLBACKS:
        risks = text_section(text, RISK_TEXT_FALLBACKS[company.ticker], r"item\s*2[\s\.\-??:]|unresolved staff comments")
    if not risks:
        risks = extract_between(text, r"item\s*1a.{0,30}?risk factors", r"item\s*1b[\s\.\-??:]|item\s*2[\s\.\-??:]")
    if not risks:
        risks = fallback_risk_section(text)

    if not business or not risks:
        return seed_payload(company, source_note="seed fallback after failed SEC extraction")

    business = business[:4000]
    risks = risks[:4000]
    ai_notes = (
        "SEC filing pulled successfully. This page contains raw Item 1 and Item 1A excerpts rather than an LLM-compressed memo. "
        "Use score.py to translate the filing text into the five AI exposure dimensions."
    )
    return {
        "source": "sec_10k",
        "source_url": filing_meta["filing_url"],
        "form": filing_meta["form"],
        "filing_date": filing_meta["filing_date"],
        "business": business,
        "risk": risks,
        "ai_notes": ai_notes,
    }


def seed_payload(company: Company, source_note: str = "manual seed summary") -> dict[str, str]:
    seed = SEED_SUMMARIES.get(company.ticker)
    if not seed:
        seed = {
            "business": (
                f"{company.name} operates in {company.sector.lower()} within the {company.industry.lower()} category. "
                "This is a generic fallback summary because SEC extraction failed and no hand-written seed memo exists yet."
            ),
            "risk": (
                "Primary risks should be read directly from the filing once extraction is repaired. "
                "For now, assume a mix of competitive, regulatory, operational, and capital-allocation risks typical of the sector."
            ),
            "ai_notes": (
                "This fallback note is intentionally thin. Re-run fetch_filings.py or improve the extractor for a higher-quality "
                "company memo before relying on the LLM score."
            ),
        }
    return {
        "source": "seed",
        "source_url": company.sec_search_url,
        "form": "seed",
        "filing_date": "seed",
        "business": seed["business"],
        "risk": seed["risk"],
        "ai_notes": seed["ai_notes"],
        "source_note": source_note,
    }


def markdown_for_company(company: Company, payload: dict[str, str]) -> str:
    market_cap = f"${company.market_cap_bil_usd:.0f}B" if company.market_cap_bil_usd is not None else "n/a"
    revenue = f"${company.revenue_bil_usd:.0f}B" if company.revenue_bil_usd is not None else "n/a"
    employees = f"{company.employees:,}" if company.employees is not None else "n/a"
    return "\n".join(
        [
            f"# {company.name} ({company.ticker})",
            "",
            f"- Sector: {company.sector}",
            f"- Industry: {company.industry}",
            f"- Market cap: {market_cap}",
            f"- Revenue: {revenue}",
            f"- Employees: {employees}",
            f"- Source: {payload['source']}",
            f"- Filing date: {payload.get('filing_date', 'unknown')}",
            f"- Filing lookup: {company.sec_search_url}",
            f"- Company URL: {company.company_url}",
            "",
            "## Business Summary",
            "",
            payload["business"],
            "",
            "## Risk Factors Summary",
            "",
            payload["risk"],
            "",
            "## AI Research Notes",
            "",
            payload["ai_notes"],
            "",
        ]
    )


def write_outputs(company: Company, payload: dict[str, str]) -> None:
    FILINGS_DIR.mkdir(exist_ok=True)
    PAGES_DIR.mkdir(exist_ok=True)

    with (FILINGS_DIR / f"{company.slug}.json").open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    with (PAGES_DIR / f"{company.slug}.md").open("w", encoding="utf-8") as f:
        f.write(markdown_for_company(company, payload))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", action="store_true", help="Write curated seed summaries instead of calling SEC")
    parser.add_argument(
        "--tickers",
        default="",
        help="Comma-separated ticker filter (example: AAPL,MSFT,NVDA).",
    )
    parser.add_argument(
        "--only-seed",
        action="store_true",
        help="Only process companies whose existing filing payload is not sec_10k.",
    )
    args = parser.parse_args()

    companies = load_companies()
    ticker_filter = parse_ticker_filter(args.tickers)
    companies = select_companies(companies, ticker_filter, args.only_seed)
    if not companies:
        print("nothing to process")
        return

    if args.seed:
        for company in companies:
            write_outputs(company, seed_payload(company))
            print(f"seeded {company.ticker}")
        return

    client = edgar_client()
    for company in companies:
        try:
            meta = latest_10k_metadata(client, company)
            if not meta:
                payload = seed_payload(company, source_note="no 10-K found in recent SEC submissions")
            else:
                filing_html = get_with_retries(client, meta["filing_url"]).text
                payload = summarize_from_text(company, meta, filing_html)
        except Exception as exc:
            payload = seed_payload(company, source_note=f"seed fallback after error: {exc}")
        write_outputs(company, payload)
        print(f"wrote {company.ticker} -> {payload['source']}")
    client.close()


if __name__ == "__main__":
    main()
