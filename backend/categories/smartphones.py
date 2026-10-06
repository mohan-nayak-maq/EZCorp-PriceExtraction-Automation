"""Smartphones category: product name + storage, any country."""

from __future__ import annotations

import re

from ..models import CountryProfile, Finding
from .base import CategoryPlugin, FieldSpec

SYSTEM_PROMPT = """\
You are a retail price research agent for a price-comparison engine.

Your job: find the CURRENT LISTED PRICE of ONE specific product on ONE specific
retailer website, for ONE specific country, and report it in that country's
local currency.

Hard rules:
1. Use the web_search tool. Never answer from memory. Never guess or estimate a
   price. If the search results do not show a price on the allowed domain, say
   the product was not found.
2. Only accept a price that appears on the target retailer's own domain
   (including its country subdomain/TLD). Reject marketplaces, resellers,
   aggregators, news articles, and price-history sites.
3. The price must be for the exact model AND the exact storage capacity
   requested. A different generation, a different variant (Pro / Pro Max /
   Plus / Ultra / FE), or a different capacity is NOT a match.
4. Many retailer product pages (especially brand sites like Samsung and Apple)
   show every storage capacity as a selectable option on ONE page, each with
   its own price - the page's default/first-shown capacity is often NOT the
   one requested. Before concluding a capacity is unavailable, look for the
   storage selector or variant list on that same page (or a `?`-parameter/URL
   slug variant of it, e.g. ".../512gb" or "?opt=512GB") and read the price
   for the SPECIFIC capacity requested. Only report not-found if that capacity
   genuinely is not offered anywhere on the page or its variants. NEVER
   substitute the default/first-shown variant's price when the requested
   capacity is a different option on that same selector - if the selector
   marks the requested capacity as unavailable/out of stock/"not available in
   this combination" and no distinct price for it can be found, that is a
   not-found, even if a different capacity's price is visible on the page.
   Reporting another capacity's price under the requested capacity's label is
   a wrong answer, not a best-effort one.
5. Reject bundles and accessories - those are never a match. Accept new,
   pre-owned, refurbished, renewed, or open-box listings that are the exact
   model and storage requested - report whichever is available, setting
   `price_type` to its condition. A title suffix or word like "(Refurbished)",
   "reacondicionado", "pre-owned", or "renewed" attached to the SAME model and
   storage is a CONDITION MARKER, not a different product - it is the exact
   same match, just not new. Do NOT set `product_found` to false, and do NOT
   write a `considered_candidates` reason like "different listing" or "not the
   new model requested" for such a listing - that reasoning is wrong. If
   several conditions are listed, prefer new, but still report
   pre-owned/refurbished when that is what's available, and add a caveat
   noting no new listing was found.
6. Report the price the customer pays today: if a sale/discount price is shown,
   that is `price`, and the struck-through price is `original_price`. Never
   report a monthly installment or trade-in price as the price. If only
   installments are shown, set product_found to false and explain in caveats.
7. `price` must be a plain number with no currency symbol or thousands
   separators (e.g. 24999.00). `currency` must be the ISO-4217 code of the
   country's currency.
8. `price_type` must be one of "new", "pre-owned", "refurbished", or null if
   the listing does not state a condition (assume "new" only when the listing
   gives no indication otherwise and nothing suggests used/refurbished stock).

Search strategy: run at least THREE distinct web searches before you conclude
the product is unavailable. Vary the wording between searches - with and
without the storage capacity, with the local-language price word ("precio",
"preco", "prix", "preis"), with the retailer name, and with the product's local
SKU/marketing name. Only then decide.

Track every listing you look at, whether you accept or reject it, as a
candidate. Return the top 3 (at most 5) most relevant candidates in
`considered_candidates`. Keep each `reason` to one short sentence (<= 15
words) explaining why it was accepted or rejected (wrong storage, refurbished,
different variant, accepted as the match, etc.) - do not repeat the title in
the reason.

Reasoning: think through the evidence explicitly and expose it. Each entry in
`reasoning_steps` is one short step you actually took (the query you ran, the
listing you opened, why you accepted or rejected it, how you read the price).
Keep every step to one sentence (<= 20 words) and use at most 5 steps total -
be concise, the JSON must stay within the output budget.

Respond with a SINGLE JSON object and nothing else - no markdown, no prose:
{
  "product_found": true | false,
  "matched_title": string | null,
  "product_url": string | null,
  "price": number | null,
  "original_price": number | null,
  "currency": string | null,
  "price_text": string | null,
  "price_type": "new" | "pre-owned" | "refurbished" | null,
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
      "price_type": "new" | "pre-owned" | "refurbished" | null,
      "reason": string
    }
  ]
}
"""


class SmartphonesCategory(CategoryPlugin):
    key = "smartphones"
    label = "Smartphones"
    description = "Phone price lookup by model, storage, country and retailer."
    allowed_countries = None
    price_type_values = ["new", "pre-owned", "refurbished"]
    input_fields = [
        FieldSpec("product_name", "Product name", required=True, placeholder="iPhone 16 Pro",
                  aliases=("product", "product name", "model", "phone")),
        FieldSpec("storage", "Storage", required=False, placeholder="256GB",
                  aliases=("storage", "capacity")),
    ]
    # Display-only suggestions (Home/Settings screens + template example row).
    # Searches always use each row's own Target Website, never this list.
    known_sites = [
        "apple.com", "samsung.com", "amazon.com.mx", "liverpool.com.mx",
        "elektra.com.mx", "coppel.com", "walmart.com.mx", "bestbuy.com",
        "ishop.gt", "max.com.gt", "bodegaaurrera.com.mx",
    ]

    def subject_label(self, fields: dict[str, str]) -> str:
        parts = [fields.get("product_name", "").strip()]
        if fields.get("storage"):
            parts.append(fields["storage"].strip())
        return " ".join(p for p in parts if p)

    def system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def build_user_prompt(
        self, fields: dict[str, str], profile: CountryProfile, domains: list[str]
    ) -> str:
        currency_line = (
            f"{profile.currency} ({profile.symbol})"
            if profile.currency
            else "the local currency of that country"
        )
        storage_line = fields.get("storage") or "not specified - prefer the base/entry capacity and say so"
        cc = (profile.iso2 or "").lower()
        domain = domains[0] if domains else ""
        storefront_hint = (
            f"The {profile.name} storefront may be a path on the main domain "
            f"(for example {domain}/{cc}/) or a country-specific domain. Try both."
            if cc
            else "Find the storefront that serves this country."
        )
        return (
            "Find the listed price for this product.\n\n"
            f"PRODUCT: {fields.get('product_name', '')}\n"
            f"STORAGE: {storage_line}\n"
            f"COUNTRY: {profile.name}\n"
            f"REQUIRED CURRENCY: {currency_line}\n"
            f"TARGET WEBSITE: {domain}\n"
            f"ACCEPTABLE DOMAINS: {', '.join(domains)} (the retailer's own storefront for "
            f"{profile.name}; nothing else counts)\n"
            f"STOREFRONT HINT: {storefront_hint}\n\n"
            "Search that retailer's storefront for the country above, open the product "
            "page, read the price exactly as displayed, and return the JSON object."
        )

    def extra_verify(self, fields: dict[str, str], finding: Finding) -> list[str]:
        warnings: list[str] = []
        storage = fields.get("storage")
        title = finding.matched_title or ""
        if storage and title:
            digits = re.sub(r"\D", "", storage)
            if digits and digits not in re.sub(r"[^0-9]", "", title):
                warnings.append(f"Requested storage {storage} was not visible in the matched title.")
        return warnings
