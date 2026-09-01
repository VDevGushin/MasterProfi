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
        self.output_dir = OUTPUT_DIR / self.path.name
        self.output_dir.mkdir(parents=True, exist_ok=False)
        self.save("task.json", {"source": source.name, "created_at": datetime.now().isoformat()})

    def save(self, name: str, payload: Any) -> None:
        (self.path / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _review_report_paths(context: TaskContext) -> tuple[Path, Path]:
    return context.output_dir / "Требуется_уточнение.txt", context.output_dir / "Требуется_уточнение.json"


def _item_size_for_report(item: Any) -> str:
    if item.raw.get("variant") == "angular_unverified":
        raw_text = str(item.raw.get("raw_text", ""))
        upper = raw_text.split("(верхний край)")[0].split()[-1] if "(верхний край)" in raw_text else "—"
        lower = raw_text.split("(нижний край)")[0].split()[-1] if "(нижний край)" in raw_text else "—"
        return f"верх {upper} мм, низ {lower} мм, высота {round(float(item.height_m or 0) * 1000)} мм"
    if item.area_m2 is not None and not (item.width_m and item.height_m):
        return f"площадь {item.area_m2:g} м²"
    if item.width_m and item.height_m:
        return f"{round(item.width_m * 1000)} × {round(item.height_m * 1000)} мм"
    return "размер не указан"


def _required_action(item: Any) -> str:
    if item.raw.get("variant") == "angular_unverified":
        return (
            "Укажите правило расчёта: считать как обычную AMG по максимальной ширине "
            "720 мм или применять отдельную систему/наценку."
        )
    if "ценовая категория" in item.note:
        return "Укажите проверенный аналог из нашего прайса и его ценовую категорию."
    if "система" in item.note:
        return "Укажите точную систему изделия из нашего прайса."
    if "сетка" in item.note:
        return "Проверьте размеры или укажите систему, допускающую такой габарит."
    return "Добавьте или подтвердите правило расчёта для этой позиции."


def requires_review_text(source: Path, priced: list[Any], unresolved: list[Any], invalid: list[Any]) -> str:
    lines = [
        "КП НЕ СФОРМИРОВАНО: ТРЕБУЕТСЯ УТОЧНЕНИЕ",
        "",
        f"ТЗ: {source.name}",
        f"Рассчитано позиций: {len(priced)}.",
        f"Требуют уточнения: {len(unresolved)}.",
        f"Исключено без размеров: {len(invalid)}.",
        "",
    ]
    if unresolved:
        lines.append("ПОЗИЦИИ, ТРЕБУЮЩИЕ РЕШЕНИЯ")
        for index, item in enumerate(unresolved, 1):
            lines.extend([
                "",
                f"{index}. {item.name}",
                f"   Количество: {item.quantity} шт.",
                f"   Размер: {_item_size_for_report(item)}.",
                f"   Комплектация: {item.system or 'не определена'}; {item.fabric or 'ткань не определена'}; {item.color or 'цвет не указан'}.",
                f"   Причина: {item.note}.",
                f"   Что нужно сделать: {_required_action(item)}",
            ])
    if invalid:
        lines.extend(["", "ИСКЛЮЧЕННЫЕ ПОЗИЦИИ"])
        for item in invalid:
            lines.append(f"- {item.name}: {item.note}.")
    lines.extend([
        "",
        "После уточнения перезапустите агента. Исходное ТЗ остаётся в папке input.",
    ])
    return "\n".join(lines) + "\n"


def _write_review_reports(context: TaskContext, report: dict[str, Any], text: str) -> tuple[Path, Path]:
    text_path, json_path = _review_report_paths(context)
    text_path.write_text(text, encoding="utf-8")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return text_path, json_path


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
            text_path, _ = _write_review_reports(context, report, requires_review_text(path, priced, unresolved, invalid))
            context.save("result.json", report)
            log("КП не создано: требуется проверенное ценовое правило. Исходное ТЗ сохранено.")
            log(f"Понятный отчёт для менеджера: {text_path.relative_to(OUTPUT_DIR.parent)}")
            return False
        output = create_quote_pdf(path, priced, agent_config, context.output_dir)
        review = review_quote(output, priced, unresolved, invalid, agent_config)
        context.save("review.json", asdict(review))
        if not review.ok:
            rejected = context.path / f"rejected_{output.name}"
            shutil.move(str(output), rejected)
            report = {"status": "rejected", "quote": str(rejected), **asdict(review)}
            text = (
                "КП НЕ ВЫДАНО ИЗ-ЗА ТЕХНИЧЕСКОЙ ПРОВЕРКИ\n\n"
                f"ТЗ: {path.name}\n"
                "Исходное ТЗ оставлено в папке input. Ничего не исправляйте вручную: "
                "передайте этот отчёт техническому специалисту.\n\n"
                "Причина:\n- " + "\n- ".join(review.errors) + "\n"
            )
            _write_review_reports(context, report, text)
            context.save("result.json", report)
            log(f"Проверяющий отклонил КП: {len(review.errors)} ошибок. ТЗ сохранено.")
            return False
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
