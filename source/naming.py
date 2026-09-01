from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path


def slug(value: str, limit: int = 70) -> str:
    """Create a readable, filesystem-safe Russian/Latin name."""
    cleaned = re.sub(r"[^0-9A-Za-zА-Яа-яЁё]+", "-", value).strip("-")
    return (cleaned[:limit].rstrip("-") or "ТЗ")


def job_folder_name(source: Path, created_at: datetime, short_id: str) -> str:
    return f"{created_at.strftime('%Y-%m-%d_%H-%M')}_{slug(source.stem)}_{short_id}"


def quote_filename(source: Path) -> str:
    return f"КП_{slug(source.stem)}.pdf"
