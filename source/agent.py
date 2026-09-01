from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import INPUT_DIR, OUTPUT_DIR, TASKS_DIR
from .knowledge import KnowledgeBase, initialize_knowledge
from .parser import parse_tz
from .pdf_renderer import create_quote_pdf
from .qwen import QwenClient
from .reviewer import review_quote
from .tools import price_items


def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


class TaskContext:
    def __init__(self, source: Path) -> None:
        safe = "".join(char if char.isalnum() or char in "_-" else "_" for char in source.stem).strip("_")
        self.path = TASKS_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe}_{uuid.uuid4().hex[:6]}"
        self.path.mkdir(parents=True, exist_ok=False)
        self.save("task.json", {"source": source.name, "created_at": datetime.now().isoformat()})

    def save(self, name: str, payload: Any) -> None:
        (self.path / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _review_report(source: Path) -> Path:
    return OUTPUT_DIR / f"{source.stem}_требует_проверки.json"


def process_file(path: Path, agent_config: dict[str, Any], qwen_config: dict[str, Any]) -> bool:
    context = TaskContext(path)
    db = KnowledgeBase()
    try:
        log(f"Обрабатываю ТЗ: {path.name}")
        knowledge_stats = initialize_knowledge(db)
        context.save("knowledge.json", knowledge_stats)
        qwen = QwenClient(qwen_config, logger=log)
        items = parse_tz(path, qwen, db)
        context.save("parsed_items.json", [asdict(item) for item in items])
        log(f"Извлечено позиций: {len(items)}")
        priced, unresolved, invalid = price_items(items, agent_config, db, logger=log)
        context.save("calculation.json", {
            "priced": [asdict(item) for item in priced],
            "unresolved": [asdict(item) for item in unresolved],
            "invalid": [asdict(item) for item in invalid],
        })
        if unresolved or not priced:
            report = {
                "status": "requires_review",
                "source": path.name,
                "reason": "Есть позиции без проверенного ценового правила",
                "unresolved": [asdict(item) for item in unresolved],
                "invalid": [asdict(item) for item in invalid],
            }
            _review_report(path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            context.save("result.json", report)
            log("КП не создано: требуется проверенное ценовое правило. Исходное ТЗ сохранено.")
            return False
        output = create_quote_pdf(path, priced, agent_config)
        review = review_quote(output, priced, unresolved, invalid, agent_config)
        context.save("review.json", asdict(review))
        if not review.ok:
            rejected_dir = OUTPUT_DIR / "rejected"
            rejected_dir.mkdir(exist_ok=True)
            rejected = rejected_dir / output.name
            shutil.move(str(output), rejected)
            report = {"status": "rejected", "quote": str(rejected), **asdict(review)}
            _review_report(path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            context.save("result.json", report)
            log(f"Проверяющий отклонил КП: {len(review.errors)} ошибок. ТЗ сохранено.")
            return False
        old_report = _review_report(path)
        if old_report.exists():
            old_report.unlink()
        context.save("result.json", {"status": "success", "quote": str(output), "review": asdict(review)})
        log(f"КП создано и прошло проверку: {output.relative_to(OUTPUT_DIR.parent)}")
        if path.parent.resolve() == INPUT_DIR.resolve():
            path.unlink()
            log(f"Исходное ТЗ удалено из input после успеха: {path.name}")
        return True
    except Exception as error:
        context.save("result.json", {"status": "error", "error": f"{type(error).__name__}: {error}"})
        log(f"Ошибка: {type(error).__name__}: {error}")
        return False
    finally:
        db.close()
