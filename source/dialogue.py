from __future__ import annotations

import re
import sys
from dataclasses import asdict
from typing import Any, Callable

from .models import QuoteItem
from .qwen import QwenClient


def _is_angular_amg(item: QuoteItem) -> bool:
    return item.raw.get("variant") == "angular_unverified" and item.system == "AMG"


def _angular_question(item: QuoteItem) -> str:
    width_mm = round(float(item.width_m or 0) * 1000)
    height_mm = round(float(item.height_m or 0) * 1000)
    return (
        f"Для угловой шторы AMG {width_mm}×{height_mm} мм нет отдельного правила в прайсе. "
        "Можно ли для этого ТЗ считать её как обычную AMG по максимальной ширине?\n"
        "Введите 1 — да, рассчитать как обычную AMG; 2 — нет, оставить позицию на уточнении."
    )


def ask_user(
    unresolved: list[QuoteItem],
    qwen: QwenClient,
    logger: Callable[[str], None],
    reader: Callable[[str], str] = input,
) -> dict[str, Any] | None:
    """Conduct one terminal clarification without letting the model invent a price rule."""
    if not sys.stdin.isatty():
        logger("Диалог с пользователем пропущен: агент запущен без интерактивного Терминала.")
        return None

    if len(unresolved) == 1 and _is_angular_amg(unresolved[0]):
        fallback = _angular_question(unresolved[0])
    else:
        fallback = "Для указанных позиций нет подтверждённого правила цены. Уточните систему, аналог или правило расчёта."

    qwen_question = qwen.clarification_question([asdict(item) for item in unresolved], fallback)
    # Модель улучшает формулировку, но фиксированный текст сохраняет все
    # допустимые варианты и не позволяет потерять важное ограничение расчёта.
    question = fallback if qwen_question == fallback else f"{qwen_question}\n\n{fallback}"
    print("\n--- Вопрос агента ---", flush=True)
    print(question, flush=True)
    try:
        answer = reader("Ваш ответ (Enter — пропустить): ").strip()
    except (EOFError, KeyboardInterrupt):
        answer = ""
    logger("Ответ пользователя получен." if answer else "Пользователь не дал ответ; оставляю ТЗ на уточнении.")
    return {"question": question, "answer": answer, "resolved_count": apply_supported_answer(unresolved, answer)}


def apply_supported_answer(unresolved: list[QuoteItem], answer: str) -> int:
    """Apply only a predetermined, auditable rule explicitly selected by the user."""
    normalized = re.sub(r"\s+", " ", answer.strip().lower())
    accepts_regular_amg = normalized in {
        "1",
        "да",
        "обычная amg",
        "amg по максимальной ширине",
        "считать как обычную amg",
    }
    if not accepts_regular_amg:
        return 0
    resolved = 0
    for item in unresolved:
        if _is_angular_amg(item):
            item.raw["variant"] = "angular_as_regular_amg"
            item.note = "По подтверждению пользователя: рассчитано как обычная AMG по максимальной ширине"
            resolved += 1
    return resolved
