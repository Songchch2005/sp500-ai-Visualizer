"""
Score each company across five AI business exposure dimensions.

Usage:
    uv run python score.py
    uv run python score.py --provider openrouter --model google/gemini-3-flash-preview
    uv run python score.py --provider gemini --model gemini-2.5-flash-lite
    uv run python score.py --seed
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent
PAGES_DIR = ROOT / "company_pages"
COMPANIES_CSV = ROOT / "companies.csv"
OUTPUT_FILE = ROOT / "scores.json"
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_OPENROUTER_MODEL = "google/gemini-3-flash-preview"
DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")

SYSTEM_PROMPT = """\
You are an expert research analyst evaluating how AI may reshape a public company's business model.

You will receive a compact company memo built from SEC filing content and basic metadata.
Score the company on six separate dimensions from 0 to 10.

Scoring principle:
- High score always means "more of this attribute", not "better stock".
- Use only the supplied memo.
- Do not predict stock returns.
- Keep each score conceptually separate. A company can have high tailwind and low pricing risk, or high tailwind and high channel risk.
- Be conservative. Do not infer a high score unless the memo gives clear evidence.

Dimension 1: ai_revenue_tailwind
Question: how directly can AI expand this company's revenue pool over the next several years?
High score signals:
- The company sells AI infrastructure, AI software, AI-enabled tools, or AI-driven services.
- AI can raise usage, wallet share, ARPU, or create new SKUs for the current customer base.
- AI can plausibly become part of what customers pay this company for.
Low score signals:
- AI is mostly an internal efficiency tool, not a product or demand driver.
- The memo only mentions AI as a general priority, without a monetization surface.

Dimension 2: pricing_power_risk
Question: how likely is AI to weaken this company's existing product pricing power, take rates, attach rates, or gross-margin structure?
This is deliberately narrow.
Only score this high if the memo supports one or more of these specific threats:
- the core paid product may become easier to substitute or commoditize because generic AI can do enough of the job
- the buyer may become less willing to pay current prices because AI lowers differentiation
- AI may compress take rates, pricing, attach rates, or gross margins in the current business model
Do NOT score this high just because:
- AI is strategically important to the company
- the company spends heavily on AI capex or R&D
- AI improves the product
- AI creates broad competitive pressure in a vague sense
- the company uses AI internally
Practical calibration:
- 0 to 2: little sign that AI attacks the current economic structure; physical, regulated, commodity, or infrastructure businesses often sit here
- 3 to 4: some plausible pressure on value capture, but not a direct threat to the current profit engine
- 5 to 7: credible risk that AI lowers willingness to pay or compresses margins in an important segment
- 8 to 10: strong evidence that AI can directly commoditize the core paid product or pricing umbrella

Dimension 3: channel_control_risk
Question: how likely is AI to weaken this company's control of the customer interface, distribution channel, or demand-routing layer?
Only score this high if the memo supports one or more of these specific threats:
- the user or buyer relationship may move to an AI assistant, aggregator, agent, or platform the company does not control
- discovery, traffic, or workflow entry points may shift away from the company's interface
- AI may reduce the company's ability to own distribution, defaults, or workflow routing
Do NOT score this high just because:
- the company has many competitors
- AI matters strategically
- AI is used heavily inside the business
Practical calibration:
- 0 to 2: the company still directly owns the key route to demand, or the business is not interface-driven
- 3 to 4: some plausible risk of weaker routing power, but not enough evidence of meaningful disintermediation
- 5 to 7: credible risk that AI intermediaries or agents can reroute demand away from the company's existing interface
- 8 to 10: strong evidence that AI can sit between the company and the customer in a way that meaningfully erodes channel control
Extra guardrails for both risk fields:
- AI infrastructure providers, chip suppliers, cloud capacity sellers, and regulated utilities should usually be low unless the memo explicitly shows their current economics being threatened by AI
- Retailers, industrials, oil and gas, and pharma should usually be low unless AI clearly disintermediates the customer relationship or commoditizes a high-margin information layer
- A company can have high tailwind and still low pricing or channel risk if AI mostly strengthens its current position

Dimension 4: ai_operating_leverage
Question: how much can AI materially improve the company's cost structure, throughput, or labor productivity?
High score signals:
- Many workflows are document-heavy, service-heavy, analytical, coding, support, or planning intensive.
- AI can improve output per employee, shorten cycle times, or automate repetitive judgment work.
Low score signals:
- Most value creation remains physical, regulated, or bottlenecked by assets rather than knowledge work.
- AI can help, but it is unlikely to move company-level economics much.

Dimension 5: data_distribution_moat
Question: how strong are this company's advantages in proprietary data, workflow embedding, customer trust, regulation, installed base, or distribution?
High score signals:
- Deep workflow lock-in, privileged data, strong ecosystem control, or hard-to-replicate channels.
- Customer behavior, scale, regulation, or installed base make displacement hard.
Low score signals:
- Weak switching costs, commodity interfaces, little control over the customer relationship.
- The memo does not show meaningful proprietary advantage beyond generic scale.

Dimension 6: ai_infrastructure_exposure
Question: how directly does the company benefit from AI buildout in chips, cloud, networking, data centers, power, or enabling tools?
High score signals:
- Chips, cloud, networking, power, cooling, or direct AI platform infrastructure.
- Revenue rises when the AI stack expands physically or computationally.
Low score signals:
- End-market user of AI with little direct exposure to buildout.
- AI matters mainly through software adoption inside the company.

Calibration anchors:
- NVIDIA: tailwind 10, pricing risk low, channel risk low, moat high, infrastructure 10
- Microsoft: tailwind high, pricing risk moderate at most unless the memo directly shows price compression, channel risk moderate if interfaces may shift away from Microsoft-owned workflows
- Alphabet: tailwind high, pricing risk and channel risk can both be high because AI can alter search, discovery, and ad economics
- Walmart: tailwind low to moderate, pricing risk low, channel risk low, operating leverage high
- Exxon: tailwind low, pricing risk low, channel risk low, operating leverage low to moderate

Return ONLY valid JSON in this exact shape:
{
  "ai_revenue_tailwind": 0,
  "pricing_power_risk": 0,
  "channel_control_risk": 0,
  "ai_operating_leverage": 0,
  "data_distribution_moat": 0,
  "ai_infrastructure_exposure": 0,
  "confidence": 0.0,
  "summary": "",
  "evidence": ["", "", ""]
}

Formatting rules for the JSON:
- All five scores must be integers from 0 to 10.
- confidence must be a number from 0.0 to 1.0.
- summary must be 3 to 5 sentences.
- In the summary, sentence 1 should explain tailwind, sentence 2 should explain pricing risk, sentence 3 should explain channel risk or moat, and optional later sentences can note uncertainty.
- evidence must contain 3 to 5 short bullets grounded in the memo.
- If the memo does not clearly justify high risk, keep pricing_power_risk and channel_control_risk conservative.
"""

NUMERIC_FIELDS = [
    "ai_revenue_tailwind",
    "pricing_power_risk",
    "channel_control_risk",
    "ai_operating_leverage",
    "data_distribution_moat",
    "ai_infrastructure_exposure",
]

GEMINI_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "ai_revenue_tailwind": {"type": "integer"},
        "pricing_power_risk": {"type": "integer"},
        "channel_control_risk": {"type": "integer"},
        "ai_operating_leverage": {"type": "integer"},
        "data_distribution_moat": {"type": "integer"},
        "ai_infrastructure_exposure": {"type": "integer"},
        "confidence": {"type": "number"},
        "summary": {"type": "string"},
        "evidence": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": [
        "ai_revenue_tailwind",
        "pricing_power_risk",
        "channel_control_risk",
        "ai_operating_leverage",
        "data_distribution_moat",
        "ai_infrastructure_exposure",
        "confidence",
        "summary",
        "evidence",
    ],
}

SEED_SCORES = {
    "MSFT": dict(ai_revenue_tailwind=9, pricing_power_risk=4, channel_control_risk=4, ai_operating_leverage=9, data_distribution_moat=9, ai_infrastructure_exposure=8, confidence=0.88, summary="Microsoft combines strong AI demand capture through Azure and Copilot with unusually strong enterprise workflow distribution. Pricing pressure exists in some software layers, but is not the whole story. Channel risk is moderate because workflow entry points could shift, though Microsoft still owns many of them.", evidence=["Azure and enterprise software are direct monetization surfaces for AI demand.", "Microsoft is deeply embedded in productivity, developer, and security workflows.", "Its capex intensity is high, but the business already monetizes software and infrastructure together."]),
    "AAPL": dict(ai_revenue_tailwind=5, pricing_power_risk=3, channel_control_risk=4, ai_operating_leverage=6, data_distribution_moat=9, ai_infrastructure_exposure=2, confidence=0.72, summary="Apple has a powerful ecosystem moat, but AI's economic impact is less direct because the core business is still premium hardware plus services. Pricing pressure appears limited. The strategic tension is whether AI shifts user interaction toward cloud intermediaries and away from device-centric control.", evidence=["Apple monetizes hardware and services rather than selling AI infrastructure.", "The installed base and ecosystem integration remain major distribution advantages.", "AI assistants could reduce the importance of some app and device interaction layers."]),
    "NVDA": dict(ai_revenue_tailwind=10, pricing_power_risk=2, channel_control_risk=1, ai_operating_leverage=5, data_distribution_moat=8, ai_infrastructure_exposure=10, confidence=0.93, summary="NVIDIA is the purest AI infrastructure beneficiary in the sample. The main debate is about durability and cyclicality, not whether AI matters to the business model. Channel control risk is low because the company sits underneath the application interface layer.", evidence=["Data-center demand is the dominant current AI revenue stream.", "The CUDA and systems ecosystem create real platform stickiness.", "Risks are more about customer concentration and pricing pressure than direct AI substitution."]),
    "AMZN": dict(ai_revenue_tailwind=8, pricing_power_risk=3, channel_control_risk=3, ai_operating_leverage=9, data_distribution_moat=8, ai_infrastructure_exposure=7, confidence=0.84, summary="Amazon benefits from AI through AWS and through productivity gains inside retail and logistics. AI looks additive to the existing model rather than obviously disruptive to it. Some channel risk exists if shopping and discovery shift to AI agents, but the current model still has strong scale advantages.", evidence=["AWS offers infrastructure and platform monetization for AI workloads.", "Retail and logistics are rich areas for planning and service automation.", "Marketplace and cloud scale provide distribution and data advantages."]),
    "GOOGL": dict(ai_revenue_tailwind=8, pricing_power_risk=8, channel_control_risk=8, ai_operating_leverage=8, data_distribution_moat=9, ai_infrastructure_exposure=6, confidence=0.85, summary="Alphabet is one of the most strategically interesting AI cases because it has both extraordinary capability and real economic risk. AI can expand cloud and product usage while pressuring legacy search monetization. It also threatens to reroute discovery and user intent away from the traditional search interface.", evidence=["Search and ad distribution give Alphabet massive user-intent and workflow advantages.", "AI answer experiences can reduce traditional search query economics.", "Cloud and model capabilities provide an offsetting tailwind."]),
    "META": dict(ai_revenue_tailwind=8, pricing_power_risk=4, channel_control_risk=5, ai_operating_leverage=8, data_distribution_moat=8, ai_infrastructure_exposure=6, confidence=0.82, summary="Meta can apply AI directly to advertising, content tools, and engagement systems. The bigger risk is not product commoditization so much as whether AI alters the interface layer between users, creators, and advertisers. Its challenge is less displacement and more proving attractive returns on very large infrastructure spend.", evidence=["Ranking and targeting already depend on data-intensive software systems.", "AI can improve creator tooling and advertising efficiency.", "The company is making unusually large AI infrastructure investments."]),
    "TSLA": dict(ai_revenue_tailwind=7, pricing_power_risk=3, channel_control_risk=2, ai_operating_leverage=6, data_distribution_moat=6, ai_infrastructure_exposure=3, confidence=0.68, summary="Tesla's AI exposure is concentrated in autonomy and robotics ambitions rather than generic language-model monetization. The upside could be large, but commercialization timing and safety constraints matter a lot. Its current customer route is still fairly direct, so channel control risk is limited.", evidence=["Vehicle autonomy and robotics are central to the AI thesis.", "The company still sells physical products in a competitive manufacturing market.", "Execution and regulation shape how much AI value can actually be captured."]),
    "JPM": dict(ai_revenue_tailwind=4, pricing_power_risk=3, channel_control_risk=4, ai_operating_leverage=9, data_distribution_moat=8, ai_infrastructure_exposure=1, confidence=0.80, summary="JPM looks like a strong internal AI productivity story more than a direct AI revenue winner. Franchise strength and regulation reduce near-term pricing pressure. The more meaningful risk is whether AI-native financial interfaces and agents weaken distribution control over time.", evidence=["Banking has many document, service, compliance, and analysis workflows.", "Scale and trust provide meaningful distribution advantages.", "Core balance-sheet and regulated products are not easy to disintermediate overnight."]),
    "V": dict(ai_revenue_tailwind=5, pricing_power_risk=4, channel_control_risk=5, ai_operating_leverage=7, data_distribution_moat=9, ai_infrastructure_exposure=1, confidence=0.76, summary="Visa can use AI to improve fraud, acceptance, and commerce tooling. The bigger question is whether new agentic payment experiences weaken network control over checkout and transaction routing. Its moat is still very strong, but interface-layer change is worth watching.", evidence=["Global acceptance and network effects remain substantial advantages.", "AI can improve fraud management and transaction intelligence.", "New software-mediated commerce flows could pressure some legacy economics over time."]),
    "UNH": dict(ai_revenue_tailwind=4, pricing_power_risk=2, channel_control_risk=3, ai_operating_leverage=9, data_distribution_moat=8, ai_infrastructure_exposure=1, confidence=0.79, summary="UnitedHealth has many AI-suitable administrative and service workflows, but regulated healthcare processes slow full automation. AI matters more as leverage than as a direct revenue step-function. Some interface risk exists through digital care coordination, but the regulated workflow remains sticky.", evidence=["Claims, coding, and service operations are information-heavy workflows.", "Healthcare regulation limits fully autonomous deployment.", "Scale and integrated data assets create meaningful defensibility."]),
    "LLY": dict(ai_revenue_tailwind=4, pricing_power_risk=2, channel_control_risk=1, ai_operating_leverage=5, data_distribution_moat=7, ai_infrastructure_exposure=1, confidence=0.70, summary="Lilly can benefit from AI in research and commercial analytics, but biology, regulation, and manufacturing still dominate value creation. AI is helpful, though not central to near-term economics. Channel risk is low because the business is not primarily controlled by a consumer-facing interface.", evidence=["Drug development may benefit from better research tooling.", "Revenue remains tied to branded therapies and execution.", "The core business is not highly exposed to language-model substitution."]),
    "XOM": dict(ai_revenue_tailwind=2, pricing_power_risk=2, channel_control_risk=1, ai_operating_leverage=5, data_distribution_moat=6, ai_infrastructure_exposure=2, confidence=0.67, summary="Exxon faces relatively low direct AI disruption and only modest direct AI tailwind. AI mostly shows up as optimization and planning support inside a capital-intensive physical business. The company is not especially exposed to AI-driven loss of interface control.", evidence=["Operations are physical, regulated, and asset-heavy.", "AI can improve maintenance and planning, but not redefine the product.", "Commodity exposure remains far more important than software substitution."]),
    "CAT": dict(ai_revenue_tailwind=4, pricing_power_risk=2, channel_control_risk=1, ai_operating_leverage=6, data_distribution_moat=7, ai_infrastructure_exposure=3, confidence=0.71, summary="Caterpillar can use AI in autonomy, maintenance, and fleet intelligence, but the adoption curve is constrained by physical hardware and safety. Pricing pressure from AI itself looks limited. The dealer network and installed base remain important moats, and channel disintermediation risk is low.", evidence=["Heavy equipment has real predictive maintenance and autonomy use cases.", "Physical deployment and customer replacement cycles slow AI impact.", "Parts, service, and dealers reinforce the installed-base advantage."]),
    "WMT": dict(ai_revenue_tailwind=4, pricing_power_risk=2, channel_control_risk=2, ai_operating_leverage=9, data_distribution_moat=8, ai_infrastructure_exposure=1, confidence=0.80, summary="Walmart looks like a major AI efficiency story across merchandising, support, and logistics rather than a direct AI product winner. Pricing pressure from AI itself appears limited. Some shopping-interface change is possible, but omnichannel scale still anchors the customer relationship.", evidence=["Retail forecasting, pricing, support, and logistics are AI-friendly workflows.", "The low-price, physical-distribution model is not easily displaced by foundation models.", "Scale and customer reach remain powerful advantages."]),
    "COST": dict(ai_revenue_tailwind=3, pricing_power_risk=1, channel_control_risk=1, ai_operating_leverage=7, data_distribution_moat=9, ai_infrastructure_exposure=1, confidence=0.77, summary="Costco has low direct AI pressure because the core value proposition is physical buying power and membership trust. AI should help operations more than it changes the essence of the business. Both pricing and channel risks are low because the model is not primarily an AI-vulnerable information layer.", evidence=["Membership economics and trust create durable distribution strength.", "AI can improve inventory and back-office workflows.", "The warehouse retail model is less vulnerable to AI-native substitution than digital products."]),
    "NEE": dict(ai_revenue_tailwind=5, pricing_power_risk=1, channel_control_risk=1, ai_operating_leverage=5, data_distribution_moat=7, ai_infrastructure_exposure=4, confidence=0.69, summary="NextEra has some indirect AI tailwind because AI infrastructure expands electricity demand, but the business remains governed by utility and project economics. AI is a demand and planning factor, not the product itself. Pricing and channel risks stay low because regulated structures still anchor value capture.", evidence=["Data-center growth can increase power demand.", "Regulated utility structures still anchor economics.", "Grid planning and operations may benefit from AI-assisted optimization."]),
}


def load_companies() -> list[dict[str, str]]:
    with COMPANIES_CSV.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def parse_ticker_filter(raw: str | None) -> set[str]:
    if not raw:
        return set()
    parts = [part.strip().upper() for part in raw.split(",")]
    return {part for part in parts if part}


def score_company_openrouter(client: httpx.Client, text: str, model: str, temperature: float) -> dict:
    response = client.post(
        OPENROUTER_API_URL,
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            "temperature": temperature,
        },
        timeout=90,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
    return json.loads(content)


def gemini_generation_config(model: str, temperature: float) -> dict:
    if model.startswith("gemini-3"):
        return {
            "temperature": temperature,
            "responseMimeType": "application/json",
            "responseJsonSchema": GEMINI_RESPONSE_SCHEMA,
            "thinkingConfig": {"thinkingLevel": "minimal"},
        }
    return {
        "temperature": temperature,
        "responseMimeType": "application/json",
        "responseJsonSchema": GEMINI_RESPONSE_SCHEMA,
        "thinkingConfig": {"thinkingBudget": 0},
    }


def extract_gemini_text(payload: dict) -> str:
    candidates = payload.get("candidates", [])
    if not candidates:
        raise ValueError(f"Gemini returned no candidates: {json.dumps(payload)[:500]}")
    parts = candidates[0].get("content", {}).get("parts", [])
    texts = [part.get("text", "") for part in parts if "text" in part]
    text = "".join(texts).strip()
    if not text:
        raise ValueError(f"Gemini returned empty text: {json.dumps(payload)[:500]}")
    return text


def score_company_gemini(client: httpx.Client, text: str, model: str, temperature: float) -> dict:
    response = client.post(
        GEMINI_API_URL.format(model=model),
        headers={
            "x-goog-api-key": os.environ["GEMINI_API_KEY"],
            "Content-Type": "application/json",
        },
        json={
            "system_instruction": {
                "parts": [{"text": SYSTEM_PROMPT}],
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": text}],
                }
            ],
            "generationConfig": gemini_generation_config(model, temperature),
        },
        timeout=90,
    )
    response.raise_for_status()
    content = extract_gemini_text(response.json())
    return json.loads(content)


def score_company(client: httpx.Client, text: str, provider: str, model: str, temperature: float) -> dict:
    if provider == "gemini":
        return score_company_gemini(client, text, model, temperature)
    return score_company_openrouter(client, text, model, temperature)


def score_with_retries(
    client: httpx.Client,
    text: str,
    provider: str,
    model: str,
    temperature: float,
    max_retries: int,
) -> dict:
    delay = 2.0
    for attempt in range(max_retries + 1):
        try:
            return score_company(client, text, provider, model, temperature)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if attempt >= max_retries or status not in {429, 500, 502, 503, 504}:
                raise
            print(f"    retrying after HTTP {status} ({attempt + 1}/{max_retries})")
        except (httpx.TimeoutException, httpx.NetworkError, httpx.ProtocolError, httpx.TransportError) as exc:
            if attempt >= max_retries:
                raise
            print(f"    retrying after network error {type(exc).__name__} ({attempt + 1}/{max_retries})")
        time.sleep(delay)
        delay *= 2
    raise RuntimeError("unreachable retry loop")


def net_score(entry: dict) -> float:
    composite_disruption = (
        entry["pricing_power_risk"] + entry["channel_control_risk"]
    ) / 2
    val = (
        entry["ai_revenue_tailwind"]
        + entry["ai_operating_leverage"]
        + entry["data_distribution_moat"]
        + entry["ai_infrastructure_exposure"]
        - composite_disruption
    ) / 4
    return round(val, 2)


def clip_score(value: float) -> int:
    return max(0, min(10, int(round(value))))


def consistency_score(samples: list[dict]) -> float:
    if len(samples) <= 1:
        return 1.0
    stds = []
    for field in NUMERIC_FIELDS:
        values = [sample[field] for sample in samples]
        stds.append(statistics.pstdev(values))
    avg_std = sum(stds) / len(stds)
    return round(max(0.0, min(1.0, 1.0 - avg_std / 2.5)), 2)


def aggregate_samples(samples: list[dict]) -> dict:
    means = {field: statistics.mean(sample[field] for sample in samples) for field in NUMERIC_FIELDS}
    stddevs = {
        field: round(statistics.pstdev([sample[field] for sample in samples]), 2) if len(samples) > 1 else 0.0
        for field in NUMERIC_FIELDS
    }
    ranges = {
        field: max(sample[field] for sample in samples) - min(sample[field] for sample in samples)
        for field in NUMERIC_FIELDS
    }
    target = [means[field] for field in NUMERIC_FIELDS]

    def distance(sample: dict) -> tuple[float, float]:
        vec = [sample[field] for field in NUMERIC_FIELDS]
        dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(vec, target)))
        return dist, -sample.get("confidence", 0.0)

    representative = min(samples, key=distance)
    aggregated = {
        field: clip_score(means[field])
        for field in NUMERIC_FIELDS
    }
    aggregated["ai_disruption_risk"] = round(
        (aggregated["pricing_power_risk"] + aggregated["channel_control_risk"]) / 2,
        2,
    )
    aggregated["confidence"] = round(statistics.mean(sample.get("confidence", 0.0) for sample in samples), 2)
    aggregated["summary"] = representative["summary"]
    aggregated["evidence"] = representative["evidence"]
    aggregated["sample_size"] = len(samples)
    aggregated["consistency"] = consistency_score(samples)
    aggregated["metric_means"] = {field: round(means[field], 2) for field in NUMERIC_FIELDS}
    aggregated["metric_stddevs"] = stddevs
    aggregated["metric_ranges"] = ranges
    aggregated["representative_sample_confidence"] = representative.get("confidence", 0.0)
    return aggregated


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["openrouter", "gemini"], default="openrouter")
    parser.add_argument("--model", default=None)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--temperature", type=float, default=0.25)
    parser.add_argument("--sample-size", type=int, default=1)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--seed", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--tickers",
        default="",
        help="Comma-separated ticker filter (example: AAPL,MSFT,NVDA).",
    )
    args = parser.parse_args()

    if args.model is None:
        args.model = DEFAULT_GEMINI_MODEL if args.provider == "gemini" else DEFAULT_OPENROUTER_MODEL

    companies = load_companies()
    ticker_filter = parse_ticker_filter(args.tickers)
    if ticker_filter:
        companies = [row for row in companies if row["ticker"].upper() in ticker_filter]
    if not companies:
        print("nothing to score")
        return
    existing = {}
    if OUTPUT_FILE.exists():
        with OUTPUT_FILE.open(encoding="utf-8") as f:
            existing = {row["ticker"]: row for row in json.load(f)}

    results = existing.copy()
    # --force without a ticker filter means full rebuild.
    if args.force and not ticker_filter:
        results = {}
    # --force with ticker filter only invalidates selected tickers.
    if args.force and ticker_filter:
        for ticker in ticker_filter:
            results.pop(ticker, None)

    if args.seed:
        for row in companies:
            ticker = row["ticker"]
            payload = dict(SEED_SCORES[ticker])
            payload.update(
                ticker=ticker,
                name=row["name"],
                slug=row["slug"],
                ai_disruption_risk=round((payload["pricing_power_risk"] + payload["channel_control_risk"]) / 2, 2),
                net_ai_pressure=net_score(payload),
                source="seed",
                sample_size=1,
                consistency=1.0,
                metric_means={field: payload[field] for field in NUMERIC_FIELDS},
                metric_stddevs={field: 0.0 for field in NUMERIC_FIELDS},
                metric_ranges={field: 0 for field in NUMERIC_FIELDS},
                representative_sample_confidence=payload["confidence"],
            )
            results[ticker] = payload
        with OUTPUT_FILE.open("w", encoding="utf-8") as f:
            json.dump(list(results.values()), f, indent=2)
        print(f"seeded {len(results)} scores")
        return

    client = httpx.Client()
    for row in companies:
        ticker = row["ticker"]
        if ticker in results:
            continue
        page_path = PAGES_DIR / f"{row['slug']}.md"
        if not page_path.exists():
            print(f"skip {ticker}: missing {page_path.name}")
            continue
        text = page_path.read_text(encoding="utf-8")
        sample_count = max(1, args.sample_size)
        print(f"scoring {ticker} with {args.provider}:{args.model} ({sample_count} sample{'s' if sample_count > 1 else ''})...")
        samples = []
        for idx in range(sample_count):
            if sample_count > 1:
                print(f"  sample {idx + 1}/{sample_count}")
            samples.append(
                score_with_retries(
                    client,
                    text,
                    args.provider,
                    args.model,
                    args.temperature,
                    args.max_retries,
                )
            )
            if idx < sample_count - 1:
                time.sleep(args.delay)
        result = aggregate_samples(samples)
        result.update(
            ticker=ticker,
            name=row["name"],
            slug=row["slug"],
            net_ai_pressure=net_score(result),
            source=f"{args.provider}:{args.model}",
        )
        results[ticker] = result
        with OUTPUT_FILE.open("w", encoding="utf-8") as f:
            json.dump(list(results.values()), f, indent=2)
        time.sleep(args.delay)
    client.close()
    print(f"wrote {len(results)} scores")


if __name__ == "__main__":
    main()
