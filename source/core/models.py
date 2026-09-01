from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class QuoteItem:
    source_ref: str
    name: str
    quantity: int
    width_m: float | None = None
    height_m: float | None = None
    area_m2: float | None = None
    system: str = ""
    fabric: str = ""
    color: str = ""
    opacity: str = ""
    split_into: int = 1
    category: str | None = None
    price_rub: int | None = None
    price_source: str = ""
    analogue_source: str = ""
    note: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def has_size(self) -> bool:
        return bool(self.raw.get("size_not_required") or self.area_m2 or (self.width_m and self.height_m))

    @property
    def line_total(self) -> int:
        return int(self.price_rub or 0) * int(self.quantity or 0)


@dataclass
class ReviewResult:
    ok: bool
    errors: list[str]
    warnings: list[str]
    checks: dict[str, Any]
