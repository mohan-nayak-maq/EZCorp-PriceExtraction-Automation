"""Settings for the web-search price tool.

Reads ``<project root>/.env`` for local runs. Real environment variables take
precedence over the file, which is how values are supplied in Azure Container
Apps (no ``.env`` is shipped in the container image).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .../websearch-tool/backend/config.py -> .../websearch-tool (holds .env)
PROJECT_DIR = Path(__file__).resolve().parent.parent


class WebSearchSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = "gpt-4.1"

    # Responses API lives under the resource's /openai/v1 surface, so the
    # chat-completions api-version used elsewhere is not needed here.
    websearch_request_timeout: float = 180.0
    websearch_max_output_tokens: int = 3500
    # Comma-separated extra origins allowed to call the API cross-origin. Empty
    # (default) = no CORS at all; the UI is served from the same origin.
    websearch_cors_origins: str = ""
    websearch_batch_concurrency: int = 3
    # "high" pulls more retrieved page content into context per search than
    # the API default ("medium"), giving the model more to work with before
    # it concludes a product isn't listed. One of only two params the plain
    # `web_search` tool exposes (the other is user_location, already set).
    websearch_search_context_size: str = "high"
    # A "not found" result below this confidence gets automatically retried -
    # web_search grounding is non-deterministic, so a low-confidence miss is
    # often just an unlucky search, not a real absence.
    websearch_low_confidence_retry_threshold: float = 0.5
    # Up to this many extra attempts while the result stays a low-confidence
    # "not found" (verified: a real, well-indexed product can miss 2 calls in
    # a row before succeeding on a 3rd - bumped from 2 to 3 after a repeat run
    # of the same 20-row batch swung from 19 to 11 found with identical inputs).
    websearch_low_confidence_max_retries: int = 3
    # Extra attempts when the model's response is truncated/unparsable JSON.
    websearch_json_max_retries: int = 3
    # Unrestricted (no domain filter) fallback searches tried after every
    # domain-filtered attempt missed; only an on-target-domain hit is accepted.
    websearch_broad_search_max_attempts: int = 2
    # Low (not zero - tool-use planning needs a little room) to make the
    # model's own query choices and stop-decisions more consistent between
    # identical calls. Doesn't affect Bing's own result variability.
    websearch_temperature: float = 0.2
    # For multi-site (fixed_sites) categories: how many of the retailer
    # domains to search concurrently per product.
    websearch_site_fanout_concurrency: int = 5
    # Where the SQLite history DB and rotating logs are written; defaults to
    # <project root>/data. Keep this on the container's local disk - Microsoft
    # advises against SQLite on Azure Files/storage mounts (file locking), so in
    # Container Apps this history is lost on restart/redeploy until it moves to
    # a managed database.
    websearch_data_dir: str = ""

    # Comma-separated firearms retailer domains: every firearms product is
    # searched across ALL of these (multi-site fan-out).
    websearch_firearms_sites: str = (
        "academy.com,basspro.com,budsgunshop.com,cabelas.com,discountgunmart.com,guns.com,"
        "palmettostatearmory.com,rockislandauction.com,spiketactical.com,sportsmans.com,"
        "sportsmansoutdoorsuperstore.com"
    )

    @staticmethod
    def _csv(value: str) -> list[str]:
        return list(dict.fromkeys(v.strip().lower() for v in value.split(",") if v.strip()))

    @property
    def firearms_site_list(self) -> list[str]:
        return self._csv(self.websearch_firearms_sites)

    @property
    def data_dir(self) -> Path:
        return Path(self.websearch_data_dir) if self.websearch_data_dir.strip() else PROJECT_DIR / "data"

    @property
    def configured(self) -> bool:
        endpoint = self.azure_openai_endpoint.strip()
        return bool(
            endpoint and self.azure_openai_api_key and not endpoint.startswith("https://<")
        )

    @property
    def responses_base_url(self) -> str:
        """Normalise whatever endpoint form is in .env to the v1 base URL."""
        raw = self.azure_openai_endpoint.strip().rstrip("/")
        if not raw:
            return ""
        for suffix in ("/openai/v1", "/openai/responses", "/openai"):
            if raw.endswith(suffix):
                raw = raw[: -len(suffix)]
                break
        return f"{raw}/openai/v1/"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.websearch_cors_origins.split(",") if o.strip()]


@lru_cache
def get_websearch_settings() -> WebSearchSettings:
    return WebSearchSettings()
