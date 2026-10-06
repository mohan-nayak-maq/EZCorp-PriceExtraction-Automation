"""Category plugin registry.

Adding a new category = write one plugin module and register it here. Nothing
else (engine, batch runner, API routes, frontend) needs to change - the
frontend renders its forms from ``GET /api/categories``, which reflects this
registry.
"""

from __future__ import annotations

from .base import CategoryPlugin
from .firearms import FirearmsCategory
from .smartphones import SmartphonesCategory

CATEGORY_REGISTRY: dict[str, CategoryPlugin] = {
    c.key: c
    for c in [
        SmartphonesCategory(),
        FirearmsCategory(),
    ]
}


def get_category(key: str) -> CategoryPlugin | None:
    return CATEGORY_REGISTRY.get(key)


def list_categories() -> list[CategoryPlugin]:
    return list(CATEGORY_REGISTRY.values())
