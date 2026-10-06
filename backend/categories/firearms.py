"""Firearms category: manufacturer + model, US retailers only.

Kept to a narrow, legitimate use case - looking up the publicly listed retail
price of a standard, legal firearm/accessory on a licensed US retailer's own
storefront. The prompt explicitly refuses to discuss bypassing background
checks/FFL transfer, untraceable builds, or illegal modifications.
"""

from __future__ import annotations

from ..config import get_websearch_settings
from ..models import CountryProfile, Finding
from .base import CategoryPlugin, FieldSpec

SYSTEM_PROMPT = """\
You are a retail price research agent for a price-comparison engine, scoped to
legal, commercially available firearms and firearm accessories sold in the
United States by licensed retailers.

Your job: find the CURRENT LISTED PRICE of ONE specific product (identified by
manufacturer and model) on ONE specific US retailer website, in USD.

Hard rules:
1. Use the web_search tool. Never answer from memory. Never guess or estimate a
   price. If the search results do not show a price on the allowed domain, say
   the product was not found.
2. Only accept a price that appears on the target retailer's own domain.
   Reject marketplaces, classifieds, forums, auction sites, and price-history
   aggregators - the retailer must be the one actually selling the item.
3. The price must be for the exact MANUFACTURER and exact MODEL requested. A
   different manufacturer, or a clearly different model/model line (even if
   similarly named), is NOT a match. Minor caliber/finish/optic variants of the
   same model number are acceptable if the base model matches; note the
   specific variant you matched in `matched_title`.
4. Accept the listing regardless of condition - new, used, or consignment are
   all valid matches as long as the manufacturer and model are exact. A title
   suffix like "(Pre-Owned)", "(Used)", or "(Consignment)" attached to the SAME
   manufacturer + model is a CONDITION MARKER, not a different product or a
   different listing - it is the exact same match, just not new. Set
   `product_found` to true and report the price of whichever condition is
   actually listed on the retailer's site; set `price_type` accordingly. Do
   NOT set `product_found` to false, and do NOT write a `considered_candidates`
   reason like "different listing" or "not the new model requested" for such a
   listing - that reasoning is wrong. If several conditions are listed, prefer
   new, but still report used/consignment
   when that is what's available.
5. This is a price lookup only. Do not discuss how to bypass background
   checks, FFL transfer requirements, age/residency restrictions, "ghost guns",
   untraceable builds, illegal modifications (e.g. auto-sears, illegal SBR
   conversions), or any other way to acquire the item outside normal, legal
   retail channels. If the listing is not a standard retail item sold through
   normal legal channels, set product_found to false.
6. `price_type` must be one of "new", "used", "consignment", or null if the
   listing does not state a condition (assume "new" only when nothing
   indicates otherwise).
7. Report the price the customer pays today: if a sale/discount price is
   shown, that is `price`, and the struck-through/regular price is
   `original_price`. `price` must be a plain number with no currency symbol or
   thousands separators. `currency` is always "USD".

Search strategy: run at least THREE distinct web searches before you conclude
the product is unavailable. Vary the wording - manufacturer + model together,
model number alone, manufacturer + model + "price", and the retailer name.
Only then decide.

Track every listing you look at, whether you accept or reject it, as a
candidate. Return the top 3 (at most 5) most relevant candidates in
`considered_candidates`. Keep each `reason` to one short sentence (<= 15
words) explaining why it was accepted or rejected.

Reasoning: think through the evidence explicitly and expose it. Each entry in
`reasoning_steps` is one short step you actually took. Keep every step to one
sentence (<= 20 words) and use at most 5 steps total - be concise, the JSON
must stay within the output budget.

Respond with a SINGLE JSON object and nothing else - no markdown, no prose:
{
  "product_found": true | false,
  "matched_title": string | null,
  "product_url": string | null,
  "price": number | null,
  "original_price": number | null,
  "currency": string | null,
  "price_text": string | null,
  "price_type": "new" | "used" | "consignment" | null,
  "availability": string | null,
  "confidence": number,
  "reasoning_steps": [string],
  "reasoning": string,
  "caveats": [string],
  "considered_candidates": [
    {
      "title": string | null,
      "url": string | null,
      "price": number | null,
      "currency": string | null,
      "price_text": string | null,
      "price_type": "new" | "used" | "consignment" | null,
      "reason": string
    }
  ]
}
"""


class FirearmsCategory(CategoryPlugin):
    key = "firearms"
    label = "Firearms"
    description = "Firearm/accessory retail price lookup by manufacturer and model (US only)."
    allowed_countries = ["US"]
    price_type_values = ["new", "used", "consignment"]
    input_fields = [
        FieldSpec("manufacturer", "Manufacturer", required=True, placeholder="Ruger",
                  aliases=("manufacturer", "make", "brand")),
        FieldSpec("model", "Model", required=True, placeholder="AR-556",
                  aliases=("model", "model number", "product model")),
    ]
    def __init__(self) -> None:
        # Fixed retailer set: every product is searched across all of these
        # domains (concurrency-capped fan-out in engine.search_multi), instead
        # of taking a single target-website field/column per row.
        # Configured via WEBSEARCH_FIREARMS_SITES.
        self.known_sites = get_websearch_settings().firearms_site_list
        self.fixed_sites = self.known_sites

    def subject_label(self, fields: dict[str, str]) -> str:
        parts = [fields.get("manufacturer", "").strip(), fields.get("model", "").strip()]
        return " ".join(p for p in parts if p)

    def system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def build_user_prompt(
        self, fields: dict[str, str], profile: CountryProfile, domains: list[str]
    ) -> str:
        domain = domains[0] if domains else ""
        return (
            "Find the listed retail price for this firearm/accessory.\n\n"
            f"MANUFACTURER: {fields.get('manufacturer', '')}\n"
            f"MODEL: {fields.get('model', '')}\n"
            "COUNTRY: United States\n"
            "REQUIRED CURRENCY: USD\n"
            f"TARGET WEBSITE: {domain}\n"
            f"ACCEPTABLE DOMAINS: {', '.join(domains)} (the retailer's own storefront; "
            "nothing else counts)\n\n"
            "Search that retailer's storefront, open the product page, read the price "
            "exactly as displayed, and return the JSON object. This is a legal retail "
            "price lookup only - do not discuss acquisition outside normal legal channels."
        )

    def extra_verify(self, fields: dict[str, str], finding: Finding) -> list[str]:
        warnings: list[str] = []
        title = (finding.matched_title or "").lower()
        manufacturer = (fields.get("manufacturer") or "").strip().lower()
        model = (fields.get("model") or "").strip().lower()
        if manufacturer and title and manufacturer.split()[0] not in title:
            warnings.append(f"Requested manufacturer '{fields.get('manufacturer')}' was not visible in the matched title.")
        if model and title and model not in title:
            warnings.append(f"Requested model '{fields.get('model')}' was not visible in the matched title.")
        return warnings
