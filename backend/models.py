"""Request/response shapes and country → currency/locale reference data."""

from __future__ import annotations

from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator


class CountryProfile(BaseModel):
    name: str
    iso2: str
    currency: str
    symbol: str
    region: str | None = None
    city: str | None = None
    timezone: str | None = None


# Keyed by lowercase country name; ISO-2 aliases are added below.
_PROFILES: list[CountryProfile] = [
    CountryProfile(name="Mexico", iso2="MX", currency="MXN", symbol="$", city="Mexico City", region="Ciudad de Mexico", timezone="America/Mexico_City"),
    CountryProfile(name="Guatemala", iso2="GT", currency="GTQ", symbol="Q", city="Guatemala City", timezone="America/Guatemala"),
    CountryProfile(name="United States", iso2="US", currency="USD", symbol="$", city="New York", region="New York", timezone="America/New_York"),
    CountryProfile(name="Canada", iso2="CA", currency="CAD", symbol="$", city="Toronto", region="Ontario", timezone="America/Toronto"),
    CountryProfile(name="Brazil", iso2="BR", currency="BRL", symbol="R$", city="Sao Paulo", timezone="America/Sao_Paulo"),
    CountryProfile(name="Colombia", iso2="CO", currency="COP", symbol="$", city="Bogota", timezone="America/Bogota"),
    CountryProfile(name="Chile", iso2="CL", currency="CLP", symbol="$", city="Santiago", timezone="America/Santiago"),
    CountryProfile(name="Argentina", iso2="AR", currency="ARS", symbol="$", city="Buenos Aires", timezone="America/Argentina/Buenos_Aires"),
    CountryProfile(name="Peru", iso2="PE", currency="PEN", symbol="S/", city="Lima", timezone="America/Lima"),
    CountryProfile(name="United Kingdom", iso2="GB", currency="GBP", symbol="£", city="London", timezone="Europe/London"),
    CountryProfile(name="Germany", iso2="DE", currency="EUR", symbol="€", city="Berlin", timezone="Europe/Berlin"),
    CountryProfile(name="France", iso2="FR", currency="EUR", symbol="€", city="Paris", timezone="Europe/Paris"),
    CountryProfile(name="Spain", iso2="ES", currency="EUR", symbol="€", city="Madrid", timezone="Europe/Madrid"),
    CountryProfile(name="Italy", iso2="IT", currency="EUR", symbol="€", city="Rome", timezone="Europe/Rome"),
    CountryProfile(name="India", iso2="IN", currency="INR", symbol="₹", city="Bengaluru", region="Karnataka", timezone="Asia/Kolkata"),
    CountryProfile(name="United Arab Emirates", iso2="AE", currency="AED", symbol="AED", city="Dubai", timezone="Asia/Dubai"),
    CountryProfile(name="Saudi Arabia", iso2="SA", currency="SAR", symbol="SAR", city="Riyadh", timezone="Asia/Riyadh"),
    CountryProfile(name="Singapore", iso2="SG", currency="SGD", symbol="S$", city="Singapore", timezone="Asia/Singapore"),
    CountryProfile(name="Japan", iso2="JP", currency="JPY", symbol="¥", city="Tokyo", timezone="Asia/Tokyo"),
    CountryProfile(name="Australia", iso2="AU", currency="AUD", symbol="A$", city="Sydney", region="New South Wales", timezone="Australia/Sydney"),
]

_ALIASES = {
    "usa": "united states",
    "us": "united states",
    "u.s.": "united states",
    "uk": "united kingdom",
    "gb": "united kingdom",
    "england": "united kingdom",
    "uae": "united arab emirates",
    "méxico": "mexico",
    "mexico city": "mexico",
    "espana": "spain",
    "españa": "spain",
    "deutschland": "germany",
}

_BY_KEY: dict[str, CountryProfile] = {}
for _p in _PROFILES:
    _BY_KEY[_p.name.lower()] = _p
    _BY_KEY[_p.iso2.lower()] = _p


def resolve_country(value: str) -> CountryProfile:
    """Best-effort country lookup; unknown values fall back to a generic profile."""
    key = (value or "").strip().lower()
    key = _ALIASES.get(key, key)
    profile = _BY_KEY.get(key)
    if profile:
        return profile
    return CountryProfile(
        name=(value or "Unknown").strip() or "Unknown",
        iso2="",
        currency="",
        symbol="",
    )


def normalise_domain(value: str) -> str:
    """Turn any user-entered site reference into a bare host for domain filtering."""
    raw = (value or "").strip()
    if not raw:
        return ""
    if "//" not in raw:
        raw = f"https://{raw}"
    host = urlsplit(raw).netloc or urlsplit(raw).path
    host = host.split("@")[-1].split(":")[0].strip().lower()
    if host.startswith("www."):
        host = host[4:]
    return host.strip("/")


# Retailers usually serve a country from a local TLD (apple.com -> apple.com.mx),
# and Bing's allowed_domains filter treats those as unrelated domains.
_COUNTRY_TLDS: dict[str, list[str]] = {
    "MX": ["com.mx", "mx"],
    "GT": ["com.gt", "gt"],
    "US": ["com"],
    "CA": ["ca"],
    "BR": ["com.br"],
    "CO": ["com.co"],
    "CL": ["cl", "com.cl"],
    "AR": ["com.ar"],
    "PE": ["com.pe", "pe"],
    "GB": ["co.uk", "uk"],
    "DE": ["de"],
    "FR": ["fr"],
    "ES": ["es"],
    "IT": ["it"],
    "IN": ["in", "co.in"],
    "AE": ["ae"],
    "SA": ["sa", "com.sa"],
    "SG": ["sg", "com.sg"],
    "JP": ["co.jp", "jp"],
    "AU": ["com.au"],
}


def domain_variants(domain: str, iso2: str) -> list[str]:
    """The target domain plus the same brand on that country's TLDs."""
    if not domain:
        return []
    variants = [domain]
    brand = domain.split(".")[0]
    for tld in _COUNTRY_TLDS.get((iso2 or "").upper(), []):
        candidate = f"{brand}.{tld}"
        if candidate not in variants:
            variants.append(candidate)
    return variants


class SearchQuery(BaseModel):
    """One lookup request. ``fields`` holds category-specific inputs
    (e.g. product_name/storage for smartphones, manufacturer/model for
    firearms) - the category plugin knows how to read and prompt with them.
    """

    category: str = Field(min_length=1, max_length=40)
    country: str = Field(min_length=2, max_length=60)
    target_website: str = Field(min_length=3, max_length=200)
    fields: dict[str, str] = Field(default_factory=dict)

    @field_validator("category", "country", "target_website")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @field_validator("fields")
    @classmethod
    def _strip_fields(cls, v: dict[str, str]) -> dict[str, str]:
        return {k: (val or "").strip() for k, val in v.items() if (val or "").strip()}

    @property
    def domain(self) -> str:
        return normalise_domain(self.target_website)

    @property
    def profile(self) -> CountryProfile:
        return resolve_country(self.country)


class Citation(BaseModel):
    url: str
    title: str | None = None


class SearchTrace(BaseModel):
    """What the model actually did on the web, surfaced for auditability."""

    queries: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)


class CandidateProduct(BaseModel):
    """One listing the model looked at while searching, kept for auditability."""

    title: str | None = None
    url: str | None = None
    price: float | None = None
    currency: str | None = None
    price_text: str | None = None
    price_type: str | None = None
    reason: str | None = None


class SiteCitation(BaseModel):
    """One priced listing found while fanning a query out across several
    retailer domains - kept even when it wasn't the winning (least-price)
    listing, so every source that had a real price stays auditable."""

    domain: str
    url: str | None = None
    title: str | None = None
    price: float | None = None
    currency: str | None = None
    price_type: str | None = None


class Finding(BaseModel):
    product_found: bool = False
    matched_title: str | None = None
    product_url: str | None = None
    price: float | None = None
    currency: str | None = None
    price_text: str | None = None
    original_price: float | None = None
    # condition vocabulary is category-defined, e.g. "new"/"pre-owned"/"refurbished"
    # for smartphones, "new"/"used"/"consignment" for firearms
    price_type: str | None = None
    availability: str | None = None
    confidence: float = 0.0
    reasoning_steps: list[str] = Field(default_factory=list)
    reasoning: str | None = None
    caveats: list[str] = Field(default_factory=list)
    considered_candidates: list[CandidateProduct] = Field(default_factory=list)


class SearchResult(BaseModel):
    query: SearchQuery
    subject_label: str = ""
    resolved_domain: str
    allowed_domains: list[str] = Field(default_factory=list)
    expected_currency: str | None = None
    status: str  # found | not_found | error
    finding: Finding = Field(default_factory=Finding)
    trace: SearchTrace = Field(default_factory=SearchTrace)
    warnings: list[str] = Field(default_factory=list)
    model: str | None = None
    elapsed_seconds: float | None = None
    raw_output_text: str | None = None
    error: str | None = None

    # Populated only for multi-site categories (e.g. firearms), where the same
    # product is searched across every domain in ``category.fixed_sites`` and
    # the cheapest listing (after condition-priority) becomes ``finding``.
    domains_searched: list[str] = Field(default_factory=list)
    least_price: float | None = None
    max_price: float | None = None
    citations: list[SiteCitation] = Field(default_factory=list)


class BatchRowResult(BaseModel):
    row_index: int
    input_fields: dict[str, str] = Field(default_factory=dict)
    result: SearchResult | None = None
    error: str | None = None


class BatchJob(BaseModel):
    id: str
    category: str
    status: str = "queued"  # queued | running | done | error
    total: int = 0
    processed: int = 0
    rows: list[BatchRowResult] = Field(default_factory=list)
    error: str | None = None
    created_at: float = 0.0
    # Anonymous per-browser id (X-Client-Id header) of whoever started the job;
    # history/view/export are scoped to it. Empty for jobs created before scoping.
    owner: str = ""

