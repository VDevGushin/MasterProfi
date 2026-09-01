from __future__ import annotations

import time
from pathlib import Path

from .agent import log, process_file
from .config import INPUT_DIR, OUTPUT_DIR, TASKS_DIR, load_agent_config, load_qwen_config


SUPPORTED_SUFFIXES = {".xlsx", ".docx", ".pdf"}


def main() -> None:
    for directory in (INPUT_DIR, OUTPUT_DIR, TASKS_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    agent_config = load_agent_config()
    qwen_config = load_qwen_config()
    log("Агент запущен. Ожидаю XLSX, DOCX или PDF в папке input. Остановка: Ctrl+C.")
    log(f"Qwen: {qwen_config['model']}; монтаж и доставка отключены.")
    seen: dict[Path, int] = {}
    while True:
        files = sorted(path for path in INPUT_DIR.iterdir() if path.suffix.lower() in SUPPORTED_SUFFIXES and not path.name.startswith("~$"))
        for path in files:
            version = path.stat().st_mtime_ns
            if seen.get(path) == version:
                continue
            process_file(path, agent_config, qwen_config)
            if path.exists():
                seen[path] = version
        time.sleep(int(agent_config.get("poll_seconds", 3)))


if __name__ == "__main__":
    main()
