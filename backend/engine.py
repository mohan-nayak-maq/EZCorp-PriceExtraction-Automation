"""Category-agnostic search engine: Azure OpenAI Responses API + web_search tool.

Flow
----
1. Resolve the country to an ISO-2 code + expected currency, and the target
   website to a bare domain (+ likely country-TLD variants).
2. Ask the category plugin for its system prompt and per-request user prompt.
3. Call the Responses API with ``tools=[{"type": "web_search", ...}]``, pinning
   ``filters.allowed_domains`` to the resolved domains and ``user_location`` to
   the country.
4. Parse the model's strict-JSON answer, then verify it against the tool trace
   (domain of the cited URL, currency) plus the category's own checks
   (storage for phones, manufacturer/model for firearms).

Truncated/unparsable responses and low-confidence "not found" results are
retried automatically, followed by an unrestricted-search fallback; all retry
counts are configurable (see ``config.py``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from typing import Any
from urllib.parse import urlsplit

import httpx

from .categories.base import CategoryPlugin
from .config import get_websearch_settings
from .models import (
    CandidateProduct,
    Citation,
    Finding,
    SearchQuery,
    SearchResult,
    SearchTrace,
    SiteCitation,
    domain_variants,
)

log = logging.getLogger(__name__)


class UpstreamError(RuntimeError):
    """Azure OpenAI call failed; the message is safe to show (details are logged)."""


def public_error(exc: BaseException) -> str:
    """User-facing error text: no raw exception/upstream details, plus a short
    reference id that is also written to the log so it can be looked up."""
    ref = uuid.uuid4().hex[:8]
    log.error("Error ref %s: %s: %s", ref, type(exc).__name__, exc)
    return f"The search failed due to an internal error (ref {ref})."


def _sdk_client() -> Any | None:
    """Return an OpenAI client only if the installed SDK exposes the Responses API.

    The repo pins ``openai==1.59.6``, which predates ``client.responses``; in that
    case we fall back to the REST transport below instead of forcing an upgrade
    on the shared virtualenv.
    """
    settings = get_websearch_settings()
    try:
        from openai import OpenAI
    except ImportError:
        return None
    client = OpenAI(
        base_url=settings.responses_base_url,
        api_key=settings.azure_openai_api_key,
        timeout=settings.websearch_request_timeout,
    )
    return client if hasattr(client, "responses") else None


async def _call_responses_api(payload: dict[str, Any]) -> dict[str, Any]:
    settings = get_websearch_settings()
    if not settings.configured:
        raise RuntimeError(
            "Azure OpenAI is not configured. Set AZURE_OPENAI_ENDPOINT and "
            "AZURE_OPENAI_API_KEY in .env or the environment"
        )

    client = _sdk_client()
    if client is not None:
        # The SDK client is synchronous; run it off the event loop so concurrent
        # rows/sites (and health probes) aren't blocked while a call is in flight.
        response = await asyncio.to_thread(client.responses.create, **payload)
        return response.model_dump()

    url = f"{settings.responses_base_url}responses"
    async with httpx.AsyncClient(timeout=settings.websearch_request_timeout) as http:
        response = await http.post(
            url,
            headers={"api-key": settings.azure_openai_api_key, "Content-Type": "application/json"},
            json=payload,
        )
    if response.status_code >= 400:
        # Full body goes to the server log only; callers/clients get a generic message.
        log.error("Azure OpenAI returned %s: %s", response.status_code, response.text[:600])
        raise UpstreamError(f"Azure OpenAI returned HTTP {response.status_code}")
    return response.json()


def _web_search_tool(profile, domains: list[str]) -> dict[str, Any]:
    settings = get_websearch_settings()
    tool: dict[str, Any] = {"type": "web_search", "search_context_size": settings.websearch_search_context_size}
    if domains:
        tool["filters"] = {"allowed_domains": domains}
    location: dict[str, Any] = {"type": "approximate"}
    if profile.iso2:
        location["country"] = profile.iso2
    if profile.city:
        location["city"] = profile.city
    if profile.region:
        location["region"] = profile.region
    if profile.timezone:
        location["timezone"] = profile.timezone
    if len(location) > 1:
        tool["user_location"] = location
    return tool


# Fields that must be present on the top-level result object; used to reject a
# truncated response where a *nested* candidate object (e.g. one entry of
# considered_candidates) is mistakenly balanced and picked up instead.
_REQUIRED_TOP_LEVEL_KEYS = ("product_found",)


def _extract_json(text: str) -> dict[str, Any] | None:
    """Pull the first balanced JSON object that looks like our schema out of the output."""
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escape = False
        for idx in range(start, len(text)):
            ch = text[idx]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(text[start : idx + 1])
                    except json.JSONDecodeError:
                        break
                    if isinstance(parsed, dict) and all(
                        key in parsed for key in _REQUIRED_TOP_LEVEL_KEYS
                    ):
                        return parsed
                    break
        start = text.find("{", start + 1)
    return None


def _safe_url(value: Any) -> str | None:
    """Keep only absolute http(s) URLs from model/web output (drops javascript:, data:, etc.)."""
    if not isinstance(value, str):
        return None
    url = value.strip()
    parts = urlsplit(url)
    if parts.scheme.lower() in ("http", "https") and parts.netloc:
        return url
    return None


def _collect_trace(payload: dict[str, Any]) -> tuple[SearchTrace, str]:
    trace = SearchTrace()
    text_parts: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        itype = item.get("type")
        if itype == "web_search_call":
            action = item.get("action") or {}
            if isinstance(action, dict):
                if action.get("type"):
                    trace.actions.append(str(action["type"]))
                if action.get("query"):
                    trace.queries.append(str(action["query"]))
                if action.get("url") and _safe_url(action["url"]):
                    trace.sources.append(str(action["url"]))
                for source in action.get("sources") or []:
                    url = _safe_url(source.get("url")) if isinstance(source, dict) else None
                    if url:
                        trace.sources.append(url)
        elif itype == "message":
            for block in item.get("content") or []:
                if not isinstance(block, dict):
                    continue
                if block.get("text"):
                    text_parts.append(str(block["text"]))
                for ann in block.get("annotations") or []:
                    if isinstance(ann, dict) and ann.get("type") == "url_citation" and _safe_url(ann.get("url")):
                        trace.citations.append(Citation(url=_safe_url(ann["url"]), title=ann.get("title")))
    trace.queries = list(dict.fromkeys(trace.queries))
    trace.actions = list(dict.fromkeys(trace.actions))
    trace.sources = list(dict.fromkeys(trace.sources))
    seen: set[str] = set()
    unique_citations: list[Citation] = []
    for citation in trace.citations:
        if citation.url not in seen:
            seen.add(citation.url)
            unique_citations.append(citation)
    trace.citations = unique_citations
    return trace, "\n".join(text_parts)


def _coerce_price(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = re.sub(r"[^\d.,]", "", str(value))
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", "." if len(cleaned.split(",")[-1]) == 2 else "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _host_matches(url: str | None, domains: list[str]) -> bool:
    if not url or not domains:
        return False
    host = (urlsplit(url).netloc or "").lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return any(host == d or host.endswith(f".{d}") for d in domains)


def _on_target_domain(result: SearchResult) -> bool:
    return bool(result.finding.product_url) and _host_matches(result.finding.product_url, result.allowed_domains)


def _to_candidates(data: Any) -> list[CandidateProduct]:
    if not isinstance(data, list):
        return []
    candidates: list[CandidateProduct] = []
    for item in data[:5]:
        if not isinstance(item, dict):
            continue
        candidates.append(
            CandidateProduct(
                title=item.get("title") or None,
                url=_safe_url(item.get("url")),
                price=_coerce_price(item.get("price")),
                currency=item.get("currency") or None,
                price_text=item.get("price_text") or None,
                price_type=item.get("price_type") or None,
                reason=item.get("reason") or None,
            )
        )
    return candidates


def _to_finding(data: dict[str, Any]) -> Finding:
    steps = data.get("reasoning_steps") or []
    caveats = data.get("caveats") or []
    confidence = data.get("confidence")
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.0
    price = _coerce_price(data.get("price"))
    original_price = _coerce_price(data.get("original_price"))
    if original_price is None:
        # No discount was reported - original price equals the current retail price.
        original_price = price
    return Finding(
        product_found=bool(data.get("product_found")),
        matched_title=data.get("matched_title") or None,
        product_url=_safe_url(data.get("product_url")),
        price=price,
        original_price=original_price,
        currency=(data.get("currency") or None),
        price_text=data.get("price_text") or None,
        price_type=data.get("price_type") or None,
        availability=data.get("availability") or None,
        confidence=max(0.0, min(1.0, confidence)),
        reasoning_steps=[str(s) for s in steps if str(s).strip()],
        reasoning=data.get("reasoning") or None,
        caveats=[str(c) for c in caveats if str(c).strip()],
        considered_candidates=_to_candidates(data.get("considered_candidates")),
    )


def _generic_verify(result: SearchResult) -> None:
    """Domain/currency checks common to every category."""
    finding = result.finding
    if not finding.product_found:
        return

    if finding.product_url and not _host_matches(finding.product_url, result.allowed_domains):
        result.warnings.append(
            f"Reported URL is not on {result.resolved_domain}; treating the match as unverified."
        )
        result.finding.confidence = min(finding.confidence, 0.3)

    if not finding.product_url:
        result.warnings.append("No product URL was returned, so the price could not be traced to a page.")
        result.finding.confidence = min(finding.confidence, 0.4)

    if finding.price is None:
        result.warnings.append("The model reported a match but no numeric price.")

    expected = result.expected_currency
    if expected and finding.currency and finding.currency.upper() != expected.upper():
        result.warnings.append(
            f"Returned currency {finding.currency} is not {expected}, the currency of "
            f"{result.query.profile.name}."
        )

    if not result.trace.queries and not result.trace.sources:
        result.warnings.append("No web_search call was recorded - the answer may not be grounded.")


async def _run_once(query: SearchQuery, category: CategoryPlugin, use_domain_filter: bool = True) -> SearchResult:
    settings = get_websearch_settings()
    profile = query.profile
    domains = domain_variants(query.domain, profile.iso2)
    result = SearchResult(
        query=query,
        subject_label=category.subject_label(query.fields),
        resolved_domain=query.domain,
        allowed_domains=domains,
        expected_currency=profile.currency or None,
        status="error",
        model=settings.azure_openai_deployment,
    )

    if not query.domain:
        result.error = "Could not read a website domain from the target website field."
        log.warning("[%s] no domain resolved from target_website=%r", result.subject_label, query.target_website)
        return result

    # The prompt always tells the model only ``domains`` counts as a match,
    # regardless of whether the API call itself is domain-filtered - that's
    # what lets the unrestricted fallback below still reject off-site hits.
    filter_domains = domains if use_domain_filter else []
    log.info(
        "[%s] calling web_search (domain_filter=%s, domains=%s)",
        result.subject_label, use_domain_filter, filter_domains or "none",
    )
    payload = {
        "model": settings.azure_openai_deployment,
        "tools": [_web_search_tool(profile, filter_domains)],
        "tool_choice": "auto",
        "temperature": settings.websearch_temperature,
        "include": ["web_search_call.action.sources"],
        "max_output_tokens": settings.websearch_max_output_tokens,
        "input": [
            {"role": "system", "content": category.system_prompt()},
            {"role": "user", "content": category.build_user_prompt(query.fields, profile, domains)},
        ],
    }

    started = time.perf_counter()
    try:
        response = await _call_responses_api(payload)
    except Exception as exc:  # network, auth, tool-blocked, quota
        result.elapsed_seconds = round(time.perf_counter() - started, 2)
        log.exception("[%s] web_search call raised an exception", result.subject_label)
        result.error = str(exc) if isinstance(exc, UpstreamError) else public_error(exc)
        return result

    result.elapsed_seconds = round(time.perf_counter() - started, 2)
    trace, output_text = _collect_trace(response)
    result.trace = trace
    result.raw_output_text = output_text
    log.info(
        "[%s] response received in %.2fs (%d web_search queries, %d citations)",
        result.subject_label, result.elapsed_seconds, len(trace.queries), len(trace.citations),
    )

    data = _extract_json(output_text)
    if data is None:
        result.error = "The model did not return parsable JSON."
        log.warning("[%s] could not parse a JSON result out of the model's response", result.subject_label)
        return result

    result.finding = _to_finding(data)
    _generic_verify(result)
    result.warnings.extend(category.extra_verify(query.fields, result.finding))
    result.status = "found" if result.finding.product_found and result.finding.price is not None else "not_found"
    result.error = None
    log.info(
        "[%s] parsed: status=%s, confidence=%.2f, price=%s %s",
        result.subject_label, result.status, result.finding.confidence,
        result.finding.price, result.finding.currency,
    )
    return result


async def search(query: SearchQuery, category: CategoryPlugin) -> SearchResult:
    """Run one lookup, retrying if the response was truncated/unparsable, or
    if it came back "not found" with low confidence.

    The web_search tool is non-deterministic - the same query, on the same
    domain, for a product confirmed to be well-indexed (verified independently
    against Bing/DuckDuckGo results) can still miss two calls in a row before
    succeeding on a third. Verified directly: re-running the exact same
    20-row batch (identical inputs, identical code) swung from 19 to 11
    "found" between two runs. Retrying low-confidence misses a few times
    materially improves the batch hit rate without changing behaviour on
    confident results - each retry only replaces the result if it's an
    improvement (found, or higher confidence). Every call runs a fresh
    web_search - the current retail price is always re-extracted, never
    served from a cache.
    """
    settings = get_websearch_settings()
    label = category.subject_label(query.fields)

    log.info("[%s] search starting (domain=%s, country=%s)", label, query.domain, query.country)
    result = await _run_once(query, category)

    json_retries = 0
    while (
        result.error
        and "parsable JSON" in result.error
        and json_retries < settings.websearch_json_max_retries
    ):
        json_retries += 1
        log.info("[%s] retrying after unparsable JSON response (attempt %d)", label, json_retries)
        result = await _run_once(query, category)

    attempts = 0
    while (
        result.status == "not_found"
        and not result.error
        and result.finding.confidence < settings.websearch_low_confidence_retry_threshold
        and attempts < settings.websearch_low_confidence_max_retries
    ):
        attempts += 1
        log.info(
            "[%s] retrying low-confidence not-found result (confidence=%.2f, attempt %d/%d)",
            label, result.finding.confidence, attempts, settings.websearch_low_confidence_max_retries,
        )
        retry = await _run_once(query, category)
        if retry.status == "found" or retry.finding.confidence > result.finding.confidence:
            result = retry

    broad_attempts = 0
    max_broad = settings.websearch_broad_search_max_attempts
    while result.status != "found" and broad_attempts < max_broad:
        # Domain-restricted search sometimes misses pages that Bing's general
        # index does have (verified: a well-indexed Coppel product page failed
        # every domain-filtered attempt but was found instantly unfiltered).
        # Also worth trying if every domain-filtered attempt errored (e.g. kept
        # returning unparsable JSON) - a fresh, differently-shaped call can
        # still succeed. The prompt still tells the model only the target
        # domain counts, so this only helps - it can't return an off-site
        # match as a "found". Retried since this draws from the same
        # non-deterministic pool as everything above.
        broad_attempts += 1
        log.info(
            "[%s] domain-filtered search exhausted (status=%s); trying an unrestricted web search (attempt %d/%d)",
            label, result.status, broad_attempts, max_broad,
        )
        broad = await _run_once(query, category, use_domain_filter=False)
        if broad.status == "found" and _on_target_domain(broad):
            broad.warnings.append("Found via an unrestricted web search after the domain-filtered search missed it.")
            result = broad
            break

    log.info("[%s] search finished: status=%s", label, result.status)
    return result


async def search_multi(country: str, fields: dict[str, str], category: CategoryPlugin) -> SearchResult:
    """Fan a single product out across every domain in ``category.fixed_sites``.

    Runs up to ``websearch_site_fanout_concurrency`` domain searches at once,
    then picks the winning listing by condition priority first (new > used >
    refurbished, per ``category.condition_rank``) and lowest price second.
    Every domain that returned a real price is kept in ``citations``.
    """
    settings = get_websearch_settings()
    domains = category.fixed_sites or []
    label = category.subject_label(fields)
    started = time.perf_counter()
    log.info("[%s] multi-site search starting across %d domain(s)", label, len(domains))

    semaphore = asyncio.Semaphore(max(1, settings.websearch_site_fanout_concurrency))

    async def run_one(domain: str) -> SearchResult:
        async with semaphore:
            query = SearchQuery(category=category.key, country=country, target_website=domain, fields=fields)
            return await search(query, category)

    per_domain = await asyncio.gather(*(run_one(d) for d in domains))

    aggregate = SearchResult(
        query=SearchQuery(category=category.key, country=country, target_website=domains[0] if domains else "", fields=fields),
        subject_label=category.subject_label(fields),
        resolved_domain=f"{len(domains)} sites",
        allowed_domains=domains,
        expected_currency=per_domain[0].expected_currency if per_domain else None,
        status="not_found",
        model=settings.azure_openai_deployment,
        domains_searched=domains,
        elapsed_seconds=round(time.perf_counter() - started, 2),
    )

    priced: list[tuple[str, SearchResult]] = []
    errored: list[str] = []
    for domain, result in zip(domains, per_domain, strict=True):
        if result.error:
            errored.append(domain)
            continue
        if result.finding.product_found and result.finding.price is not None:
            priced.append((domain, result))

    aggregate.citations = [
        SiteCitation(
            domain=domain,
            url=r.finding.product_url,
            title=r.finding.matched_title,
            price=r.finding.price,
            currency=r.finding.currency,
            price_type=r.finding.price_type,
        )
        for domain, r in priced
    ]

    if not priced:
        aggregate.status = "error" if len(errored) == len(domains) and domains else "not_found"
        if errored:
            aggregate.warnings.append(f"{len(errored)}/{len(domains)} sites could not be searched (see logs).")
        log.info(
            "[%s] multi-site search finished in %.2fs: status=%s (0/%d domains priced, %d errored)",
            label, aggregate.elapsed_seconds, aggregate.status, len(domains), len(errored),
        )
        return aggregate

    prices = [float(r.finding.price) for _, r in priced if r.finding.price is not None]
    aggregate.least_price = min(prices)
    aggregate.max_price = max(prices)

    best_rank = min(category.condition_rank(r.finding.price_type) for _, r in priced)
    best_tier = [(d, r) for d, r in priced if category.condition_rank(r.finding.price_type) == best_rank]
    winner_domain, winner = min(best_tier, key=lambda item: float(item[1].finding.price or 0.0))

    aggregate.finding = winner.finding.model_copy(update={
        "reasoning_steps": [
            f"{d}: {r.finding.price_type or 'unknown condition'} @ {r.finding.price}" if r.finding.product_found else f"{d}: not found"
            for d, r in zip(domains, per_domain, strict=True)
        ],
        "reasoning": (
            f"Searched {len(domains)} retailer sites; {len(priced)} had a price. "
            f"Picked {winner_domain} at {winner.finding.price} {winner.finding.currency} "
            f"(condition: {winner.finding.price_type or 'unknown'}) as the lowest price in the "
            "best available condition tier."
        ),
        "considered_candidates": [
            CandidateProduct(
                title=f"[{d}] {r.finding.matched_title or ''}".strip(),
                url=r.finding.product_url,
                price=r.finding.price,
                currency=r.finding.currency,
                price_text=r.finding.price_text,
                price_type=r.finding.price_type,
                reason="Selected as current retail price" if d == winner_domain else "Priced listing, not the winner",
            )
            for d, r in priced
        ],
    })
    aggregate.resolved_domain = winner_domain
    aggregate.status = "found"
    if errored:
        aggregate.warnings.append(f"{len(errored)}/{len(domains)} sites could not be searched (see logs).")
    log.info(
        "[%s] multi-site search finished in %.2fs: winner=%s @ %s %s (%d/%d domains priced)",
        label, aggregate.elapsed_seconds, winner_domain, winner.finding.price, winner.finding.currency,
        len(priced), len(domains),
    )
    return aggregate

