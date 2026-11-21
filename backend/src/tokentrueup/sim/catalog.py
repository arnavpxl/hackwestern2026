"""Synthetic world: providers, models, teams, owners, keys, contracts, POs.

ALL NAMES AND NUMBERS ARE SYNTHETIC. Rates are cents per 1M tokens, cents per 1k
requests, or cents per GPU-hour.
"""

from dataclasses import dataclass, field

TEAMS = [("Platform", "CC-100"), ("Support AI", "CC-200"), ("Growth", "CC-300"), ("Research", "CC-400")]

OWNERS = [
    ("Priya Natarajan", "priya.n@example.test", "Platform"),
    ("Marcus Oyelaran", "marcus.o@example.test", "Platform"),
    ("Lena Fischbach", "lena.f@example.test", "Support AI"),
    ("Tomás Ibarra", "tomas.i@example.test", "Growth"),
    ("Aiko Brennan", "aiko.b@example.test", "Research"),
    ("Dev Raman", "dev.r@example.test", "Research"),
]

# id, name, kind, invoice_lag_days
PROVIDERS = [
    ("nimbus-llm", "Nimbus AI (synthetic)", "llm", 4),
    ("cortexa", "Cortexa Models (synthetic)", "llm", 5),
    ("helio-gpu", "Helio GPU Cloud (synthetic)", "gpu", 6),
    ("stratus-cloud", "Stratus Vision API (synthetic)", "cloud", 3),
    ("quillsearch", "Quill Search API (synthetic)", "cloud", 5),
    ("vectorhaus", "VectorHaus (synthetic)", "cloud", 4),
]

# (provider, model, unit_kind, rates) where rates = input, output, cached, request, gpu
MODELS = {
    ("nimbus-llm", "nimbus-pro"): ("tokens", (300, 1500, 30, 0, 0)),
    ("nimbus-llm", "nimbus-lite"): ("tokens", (25, 125, 2.5, 0, 0)),
    ("cortexa", "cx-large"): ("tokens", (250, 1000, 25, 0, 0)),
    ("cortexa", "cx-embed"): ("tokens", (10, 0, 0, 0, 0)),
    ("helio-gpu", "h100"): ("gpu", (0, 0, 0, 0, 249)),
    ("stratus-cloud", "vision-api"): ("requests", (0, 0, 0, 150, 0)),
    ("quillsearch", "quill-rerank"): ("requests", (0, 0, 0, 100, 0)),
    ("vectorhaus", "vh-serverless"): ("requests", (0, 0, 0, 8, 0)),
}

# Historical price change: nimbus-lite was cut on day 15 of the backfill's 2nd month.
# (provider, model, month_offset_from_start, day, old_rates)
HISTORICAL_PRICE_CHANGES = [("nimbus-llm", "nimbus-lite", 1, 15, (30, 150, 3, 0, 0))]


@dataclass
class KeySpec:
    label: str
    provider: str
    team: str
    owner_email: str | None
    models: list[tuple[str, float]]  # (model, share of the key's volume)
    daily_units: float  # tokens/day, requests/day or GPU-hours/day
    mix: tuple[float, float, float] = (0.7, 0.2, 0.1)  # input/output/cached token split
    is_batch: bool = False
    diurnal: float = 0.7  # 0 = flat, 1 = strongly business-hours
    weekend: float = 0.45  # weekend volume multiplier
    growth_per_month: float = 0.04
    extra: dict = field(default_factory=dict)


KEYS: list[KeySpec] = [
    KeySpec("plat-gateway-prod", "nimbus-llm", "Platform", "priya.n@example.test",
            [("nimbus-pro", 0.7), ("nimbus-lite", 0.3)], 600e6),
    KeySpec("plat-gateway-staging", "nimbus-llm", "Platform", "marcus.o@example.test",
            [("nimbus-lite", 1.0)], 80e6, diurnal=0.9),
    KeySpec("support-copilot", "cortexa", "Support AI", "lena.f@example.test",
            [("cx-large", 1.0)], 300e6, mix=(0.45, 0.2, 0.35)),
    KeySpec("support-embeddings", "cortexa", "Support AI", "lena.f@example.test",
            [("cx-embed", 1.0)], 900e6, mix=(1.0, 0.0, 0.0), diurnal=0.3),
    KeySpec("support-triage-agent", "nimbus-llm", "Support AI", "lena.f@example.test",
            [("nimbus-pro", 1.0)], 150e6),
    KeySpec("growth-personalize", "cortexa", "Growth", "tomas.i@example.test",
            [("cx-large", 1.0)], 120e6, mix=(0.5, 0.2, 0.3)),
    KeySpec("growth-scraper-legacy", "quillsearch", "Growth", None,
            [("quill-rerank", 1.0)], 400e3, diurnal=0.1, weekend=1.0),
    KeySpec("growth-search", "quillsearch", "Growth", "tomas.i@example.test",
            [("quill-rerank", 1.0)], 1.2e6),
    KeySpec("research-train-h100", "helio-gpu", "Research", "aiko.b@example.test",
            [("h100", 1.0)], 300, diurnal=0.1, weekend=0.9),
    KeySpec("research-eval-h100", "helio-gpu", "Research", "dev.r@example.test",
            [("h100", 1.0)], 60, diurnal=0.5),
    KeySpec("research-batch-labeling", "nimbus-llm", "Research", "dev.r@example.test",
            [("nimbus-pro", 1.0)], 500e6, is_batch=True, diurnal=0.2, weekend=0.8),
    KeySpec("plat-vision-ocr", "stratus-cloud", "Platform", "marcus.o@example.test",
            [("vision-api", 1.0)], 800e3),
    KeySpec("support-vision", "stratus-cloud", "Support AI", "lena.f@example.test",
            [("vision-api", 1.0)], 200e3),
    KeySpec("plat-vectors", "vectorhaus", "Platform", "priya.n@example.test",
            [("vh-serverless", 1.0)], 5e6, diurnal=0.4),
    KeySpec("research-notebooks", "cortexa", "Research", "aiko.b@example.test",
            [("cx-large", 1.0)], 40e6, mix=(0.6, 0.3, 0.1), diurnal=0.9),
]

RUNAWAY_KEY = "support-triage-agent"
ORPHAN_KEY = "growth-scraper-legacy"

# Contracts. Note: Cortexa's 50% cached-input discount is ONLY in the source text — the
# structured CLM record has cached_discount_pct = 0. That gap is what reconciliation finds.
CONTRACTS = [
    dict(provider_id="nimbus-llm", name="Nimbus Enterprise API", kind="usage",
         tiers=[{"from_tokens": 0, "discount_pct": 0}, {"from_tokens": 15e9, "discount_pct": 5},
                {"from_tokens": 30e9, "discount_pct": 8}],
         batch_discount_pct=50,
         source_text=("NIMBUS ENTERPRISE API ORDER FORM (SYNTHETIC). Usage billed at list rates per "
                      "million tokens. Volume discount: 5% on monthly token volume above 15 billion "
                      "tokens, 8% above 30 billion tokens. Batch API requests are billed at 50% of list.")),
    dict(provider_id="nimbus-llm", name="Nimbus Workspace Seats", kind="fixed", seats=120,
         seat_price_cents=3000, fixed_monthly_cents=120 * 3000,
         source_text="Nimbus Workspace: 120 seats at $30.00 per seat per month, billed monthly in arrears."),
    dict(provider_id="cortexa", name="Cortexa Growth Agreement", kind="usage",
         source_text=("CORTEXA GROWTH AGREEMENT (SYNTHETIC). Section 4.2 Pricing: list rates apply. "
                      "Section 4.3 Prompt caching: cached input tokens receive an additional 50% "
                      "discount off the published cached-input rate, applied on the monthly invoice.")),
    dict(provider_id="helio-gpu", name="Helio On-Demand GPU", kind="usage",
         source_text=("HELIO GPU CLOUD TERMS (SYNTHETIC). H100 billed per GPU-second at $2.49/GPU-hour. "
                      "Metering from preemptible nodes may be reported up to 72 hours late.")),
    dict(provider_id="stratus-cloud", name="Stratus Vision API", kind="usage",
         source_text="Stratus Vision API: $1.50 per 1,000 requests."),
    dict(provider_id="stratus-cloud", name="Stratus Premium Support", kind="fixed",
         fixed_monthly_cents=150000, source_text="Premium support plan: $1,500.00 per month."),
    dict(provider_id="quillsearch", name="Quill Search API", kind="usage",
         source_text="Quill rerank: $1.00 per 1,000 requests. All keys on the account are billed."),
    dict(provider_id="vectorhaus", name="VectorHaus Serverless", kind="usage",
         source_text="VectorHaus serverless: $0.08 per 1,000 requests."),
    dict(provider_id="vectorhaus", name="VectorHaus Team Seats", kind="committed", seats=25,
         seat_price_cents=4000, fixed_monthly_cents=25 * 4000,
         source_text="VectorHaus Team plan: 25 seats at $40.00 per seat per month (12-month commitment)."),
]

# One-time obligations: (month_offset from current month, day, provider, team, kind, desc, amount_cents)
PURCHASE_ORDERS = [
    (-3, 8, "helio-gpu", "Research", "reserved_capacity", "Reserved H100 block (64 GPUs x 1 wk)", 1_600_000),
    (-2, 12, "nimbus-llm", "Support AI", "fine_tune", "Fine-tune job: triage-classifier-v3", 420_000),
    (-1, 9, "helio-gpu", "Research", "reserved_capacity", "Reserved H100 block (64 GPUs x 1 wk)", 1_600_000),
    (0, 10, "helio-gpu", "Research", "reserved_capacity", "Reserved H100 block (96 GPUs x 1 wk)", 2_400_000),
    (0, 12, "nimbus-llm", "Support AI", "fine_tune", "Fine-tune job: triage-classifier-v4", 650_000),
]

# The provider's billing "truth" for synthetic invoices: what the estimator does not know.
INVOICE_TRUTH = {
    "cortexa": {"cached_discount_pct": 50},
    "helio-gpu": {"uplift_pct": 2.5},  # late-metered preemptible usage never reaches our telemetry
}
