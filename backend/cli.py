"""Manual test CLI for the generalized engine (run from the project root).

    python -m backend.cli --category smartphones --country Mexico \
        --site amazon.com.mx --field product_name="iPhone 16" --field storage=256GB

    # Firearms is a multi-site category: --site is ignored, every product is
    # fanned out across all of category.fixed_sites automatically.
    python -m backend.cli --category firearms --country US \
        --field manufacturer=Ruger --field model=AR-556
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys

from .categories import get_category, list_categories
from .engine import search, search_multi
from .logging_config import configure_logging
from .models import SearchQuery

# Windows consoles default to cp1252, which can't encode the non-ASCII
# punctuation ("‑", "…") the model sometimes returns; force UTF-8 on stdout.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")



def _parse_fields(pairs: list[str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"--field must be key=value, got: {pair}")
        key, _, value = pair.partition("=")
        fields[key.strip()] = value.strip()
    return fields


async def _main_async() -> int:
    parser = argparse.ArgumentParser(description="Run one category search from the command line.")
    parser.add_argument("--category", required=True, choices=[c.key for c in list_categories()])
    parser.add_argument("--country", required=True, help='e.g. "Mexico" or "US"')
    parser.add_argument("--site", default=None, help='e.g. "amazon.com.mx" (ignored for multi-site categories)')
    parser.add_argument("--field", action="append", default=[], help="key=value, repeatable")
    parser.add_argument("--json", action="store_true", help="print the full result as JSON")
    args = parser.parse_args()

    configure_logging()

    category = get_category(args.category)
    if category is None:
        raise SystemExit(f"Unknown category: {args.category}")

    fields = _parse_fields(args.field)
    country_error = category.validate_country(args.country)
    if country_error:
        raise SystemExit(country_error)
    field_errors = category.validate_fields(fields)
    if field_errors:
        raise SystemExit("; ".join(field_errors))

    if category.is_multi_site:
        result = await search_multi(args.country, fields, category)
    else:
        if not args.site:
            raise SystemExit("--site is required for this category")
        query = SearchQuery(category=category.key, country=args.country, target_website=args.site, fields=fields)
        result = await search(query, category)

    if args.json:
        print(json.dumps(result.model_dump(), indent=2, ensure_ascii=False))
        return 0 if result.status == "found" else 1

    finding = result.finding
    print(f"\nQuery    : {result.subject_label} · {result.query.profile.name} · {result.resolved_domain}")
    print(f"Status   : {result.status}  ({result.elapsed_seconds}s, model={result.model})")
    if result.error:
        print(f"Error    : {result.error}")
        return 1
    if result.least_price is not None:
        print(
            f"Range    : least {result.least_price:,.2f} / max {result.max_price:,.2f} "
            f"across {len(result.domains_searched)} sites"
        )
    if finding.price is not None:
        label = "Current retail price" if result.least_price is not None else "Price"
        print(f"{label:9}: {finding.price:,.2f} {finding.currency or ''}  ({finding.price_text or '-'})")
    if finding.original_price is not None and finding.original_price != finding.price:
        print(f"Original : {finding.original_price:,.2f} {finding.currency or ''}")
    if finding.price_type:
        print(f"Condition: {finding.price_type}")
    if finding.matched_title:
        print(f"Title    : {finding.matched_title}")
    if finding.product_url:
        print(f"URL      : {finding.product_url}")
    print(f"Confidence: {finding.confidence:.2f}")
    if finding.reasoning_steps:
        print("Reasoning:")
        for i, step in enumerate(finding.reasoning_steps, 1):
            print(f"  {i}. {step}")
    for caveat in finding.caveats:
        print(f"Caveat   : {caveat}")
    for warning in result.warnings:
        print(f"Warning  : {warning}")
    if finding.considered_candidates:
        print("Candidates considered:")
        for i, c in enumerate(finding.considered_candidates, 1):
            price_bit = f"{c.price:,.2f} {c.currency or ''}".strip() if c.price is not None else "-"
            print(f"  {i}. {c.title or '-'} [{c.price_type or 'unknown'}] {price_bit} - {c.reason or '-'}")
    if result.citations:
        print("Citations (all sites with a captured price):")
        for c in result.citations:
            print(f"  [{c.domain}] {c.price} {c.currency or ''} ({c.price_type or 'unknown'}) - {c.url or 'no link'}")
    return 0 if result.status == "found" else 1


def main() -> int:
    return asyncio.run(_main_async())


if __name__ == "__main__":
    raise SystemExit(main())
