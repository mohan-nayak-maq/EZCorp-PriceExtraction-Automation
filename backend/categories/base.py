"""Shared category plugin contract.

Each category (smartphones, firearms, ...) implements ``CategoryPlugin`` to
supply its own input fields, prompt rules, condition vocabulary, and
verification logic, while the engine/batch runner/API stay category-agnostic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..models import CountryProfile, Finding, resolve_country


@dataclass(frozen=True)
class FieldSpec:
    """One input field, used both to render the frontend form and to map
    Excel columns for batch uploads."""

    name: str
    label: str
    required: bool = True
    placeholder: str = ""
    aliases: tuple[str, ...] = ()


class CategoryPlugin(ABC):
    key: str
    label: str
    description: str = ""
    # None = any country allowed. A list restricts the category (e.g. firearms -> ["US"]).
    allowed_countries: list[str] | None = None
    price_type_values: list[str] = ["new", "pre-owned", "refurbished"]
    input_fields: list[FieldSpec] = []
    known_sites: list[str] = []
    # When set, every request is fanned out across ALL of these domains instead
    # of taking a single "target website" field/column from the user - the
    # cheapest listing (after condition-priority) wins. See engine.search_multi.
    fixed_sites: list[str] | None = None

    @property
    def is_multi_site(self) -> bool:
        return bool(self.fixed_sites)

    def to_metadata(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "allowed_countries": self.allowed_countries,
            "price_type_values": self.price_type_values,
            "known_sites": self.known_sites,
            "fixed_sites": self.fixed_sites,
            "input_fields": [
                {
                    "name": f.name,
                    "label": f.label,
                    "required": f.required,
                    "placeholder": f.placeholder,
                }
                for f in self.input_fields
            ],
        }

    def validate_country(self, country: str) -> str | None:
        """Return an error message if this category can't search this country."""
        if self.allowed_countries is None:
            return None
        profile = resolve_country(country)
        if profile.iso2 and profile.iso2 in self.allowed_countries:
            return None
        if country.strip().upper() in self.allowed_countries:
            return None
        return (
            f"{self.label} is only supported for: {', '.join(self.allowed_countries)}. "
            f"'{country}' is not allowed."
        )

    def validate_fields(self, fields: dict[str, str]) -> list[str]:
        errors = []
        for f in self.input_fields:
            if f.required and not (fields.get(f.name) or "").strip():
                errors.append(f"Missing required field: {f.label}")
        return errors

    # Lower rank = higher priority when picking the winning listing across
    # sites in a multi-site (fixed_sites) category. Default: new > used-like >
    # refurbished > unknown. Override per-category if the vocabulary differs.
    _CONDITION_RANK = {
        "new": 0,
        "used": 1,
        "old": 1,
        "pre-owned": 1,
        "preowned": 1,
        "consignment": 1,
        "refurbished": 2,
        "reconditioned": 2,
    }

    def condition_rank(self, price_type: str | None) -> int:
        return self._CONDITION_RANK.get((price_type or "").strip().lower(), 3)

    @abstractmethod
    def subject_label(self, fields: dict[str, str]) -> str:
        """Human-readable label for this row, e.g. 'iPhone 16 Pro 256GB'."""

    @abstractmethod
    def system_prompt(self) -> str:
        """The category's hard rules for the model, appended to the shared base rules."""

    @abstractmethod
    def build_user_prompt(
        self, fields: dict[str, str], profile: CountryProfile, domains: list[str]
    ) -> str:
        """The per-request instructions naming the exact subject to search for."""

    def extra_verify(self, fields: dict[str, str], finding: Finding) -> list[str]:
        """Category-specific post-hoc checks; return warning strings."""
        return []
