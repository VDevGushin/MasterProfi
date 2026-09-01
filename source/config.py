from __future__ import annotations

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.9–3.10
    import tomli as tomllib
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = ROOT / "source"
INPUT_DIR = ROOT / "input"
OUTPUT_DIR = ROOT / "output"
DATA_DIR = ROOT / "Локальные данные"
EXAMPLES_DIR = ROOT / "ПримерыТЗ"
REFERENCE_QUOTES_DIR = ROOT / "ПримерыКП"
KNOWLEDGE_DIR = SOURCE_DIR / "knowledge"
TASKS_DIR = ROOT / ".agent_data" / "tasks"
KNOWLEDGE_DB = KNOWLEDGE_DIR / "knowledge.sqlite3"
COMPETITORS_CONFIG = KNOWLEDGE_DIR / "competitors.yaml"
COMPETITOR_SOURCES = KNOWLEDGE_DIR / "competitor_sources.toml"


def _read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        return tomllib.load(stream)


def load_agent_config() -> dict[str, Any]:
    return _read_toml(SOURCE_DIR / "config" / "agent.toml")


def load_qwen_config() -> dict[str, Any]:
    return _read_toml(SOURCE_DIR / "config" / "qwen.toml")
