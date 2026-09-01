from pathlib import Path

from source.config import ROOT, load_agent_config, load_qwen_config
from source.agent import requires_review_text
from source.dialogue import apply_supported_answer
from source.knowledge import KnowledgeBase, initialize_knowledge
from source.parser import extract_records, parse_tz
from source.qwen import QwenClient
from source.reviewer import _contains_temporary_service
from source.tools import price_items


def silent(*_args, **_kwargs):
    return None


def test_format_extractors() -> None:
    examples = ROOT / "ПримерыТЗ"
    solar = extract_records(examples / "шторы Солнечногорск.xlsx")
    assert len(solar) == 30
    assert solar[0]["width_m"] == 0.86 and solar[0]["height_m"] == 2.64 and solar[0]["quantity"] == 3

    vertical = extract_records(examples / "ЖАЛЮЗИ 1.docx")
    # 27 изделий; доставка и монтаж из исходного бланка намеренно не импортируются.
    assert len(vertical) == 27
    assert vertical[0]["area_m2"] == 9.25 and vertical[0]["quantity"] == 2

    procurement = extract_records(examples / "ТЗ_рулонные шторы 2026 (2) (1).docx")
    assert len(procurement) == 10
    assert procurement[0]["width_m"] == 1.51 and procurement[0]["height_m"] == 1.775

    technical = extract_records(examples / "Техническое_задание_на_изготовление_рулонных_штор_коррект.pdf")
    assert len(technical) >= 30


def test_pricing_without_delivery_or_installation() -> None:
    agent_config = load_agent_config()
    qwen_config = {**load_qwen_config(), "url": "http://127.0.0.1:1/api/chat", "timeout_seconds": 1}
    db = KnowledgeBase()
    try:
        initialize_knowledge(db)
        client = QwenClient(qwen_config, logger=silent)
        items = parse_tz(ROOT / "ПримерыТЗ" / "шторы Солнечногорск.xlsx", client, db)
        priced, unresolved, invalid = price_items(items, agent_config, db, logger=silent)
        assert len(priced) == 29
        assert not unresolved
        assert len(invalid) == 1
        assert sum(item.line_total for item in priced) == 862325
        assert "quote_template" not in agent_config
        assert "discount_percent" not in agent_config
        assert "installation" not in agent_config
        assert "delivery" not in agent_config
        assert agent_config["warranty_text"] == "Гарантия на изделия 1 год."
        assert agent_config["production_days"] == 10
    finally:
        db.close()


def test_vertical_blinds_area_pricing() -> None:
    agent_config = load_agent_config()
    qwen_config = {**load_qwen_config(), "url": "http://127.0.0.1:1/api/chat", "timeout_seconds": 1}
    db = KnowledgeBase()
    try:
        initialize_knowledge(db)
        items = parse_tz(ROOT / "ПримерыТЗ" / "ЖАЛЮЗИ 1.docx", QwenClient(qwen_config, logger=silent), db)
        priced, unresolved, invalid = price_items(items, agent_config, db, logger=silent)
        assert len(priced) == 27
        assert not unresolved
        assert not invalid
        assert all(item.price_source for item in priced)
        assert sum(item.category == "E" for item in priced) == 26
        assert sum(item.category == "комплектация" and item.price_rub == 0 for item in priced) == 1
    finally:
        db.close()


def test_procurement_docx_requires_only_angular_rule() -> None:
    agent_config = load_agent_config()
    qwen_config = {**load_qwen_config(), "url": "http://127.0.0.1:1/api/chat", "timeout_seconds": 1}
    db = KnowledgeBase()
    try:
        initialize_knowledge(db)
        items = parse_tz(
            ROOT / "ПримерыТЗ" / "ТЗ_рулонные шторы 2026 (2) (1).docx",
            QwenClient(qwen_config, logger=silent),
            db,
        )
        priced, unresolved, invalid = price_items(items, agent_config, db, logger=silent)
        assert len(items) == 10
        assert len(priced) == 9
        assert len(unresolved) == 1
        assert not invalid
        assert unresolved[0].name == "Штора (угловая)"
        assert unresolved[0].width_m == 0.72
        assert "угловой шторы" in unresolved[0].note
        text = requires_review_text(ROOT / "ПримерыТЗ" / "ТЗ_рулонные шторы 2026 (2) (1).docx", priced, unresolved, invalid)
        assert "КП НЕ СФОРМИРОВАНО" in text
        assert "верх 590 мм, низ 720 мм, высота 1720 мм" in text
        assert "Укажите правило расчёта" in text
    finally:
        db.close()


def test_bnt_electrics_pdf_pricing() -> None:
    agent_config = load_agent_config()
    qwen_config = {**load_qwen_config(), "url": "http://127.0.0.1:1/api/chat", "timeout_seconds": 1}
    db = KnowledgeBase()
    try:
        initialize_knowledge(db)
        items = parse_tz(ROOT / "ПримерыТЗ" / "ЗН Восток.pdf", QwenClient(qwen_config, logger=silent), db)
        priced, unresolved, invalid = price_items(items, agent_config, db, logger=silent)
        assert len(items) == 8
        assert len(priced) == 8
        assert not unresolved
        assert not invalid
        assert items[0].raw["component_widths_m"] == [1.447, 1.496, 0.898]
        assert items[2].raw["component_widths_m"] == [1.496, 1.496, 0.87]
        assert [item.price_rub for item in priced] == [78856, 69414, 78896, 59305, 63318, 69705, 3413, 2560]
        assert sum(item.line_total for item in priced) == 425467
        assert all(item.price_source for item in priced)
    finally:
        db.close()


def test_mounting_profile_is_not_installation_service() -> None:
    assert _contains_temporary_service("Рулонная штора с монтажным профилем") is None
    assert _contains_temporary_service("Монтаж изделий — 1 услуга") == "монтаж"


def test_user_can_confirm_safe_angular_amg_rule() -> None:
    agent_config = load_agent_config()
    db = KnowledgeBase()
    try:
        initialize_knowledge(db)
        items = parse_tz(
            ROOT / "ПримерыТЗ" / "ТЗ_рулонные шторы 2026 (2) (1).docx",
            QwenClient({**load_qwen_config(), "url": "http://127.0.0.1:1/api/chat", "timeout_seconds": 1}, logger=silent),
            db,
        )
        _, unresolved, _ = price_items(items, agent_config, db, logger=silent)
        assert len(unresolved) == 1
        assert apply_supported_answer(unresolved, "1") == 1
        priced, unresolved, invalid = price_items(items, agent_config, db, logger=silent)
        assert len(priced) == 10
        assert not unresolved
        assert not invalid
    finally:
        db.close()


if __name__ == "__main__":
    test_format_extractors()
    test_pricing_without_delivery_or_installation()
    test_vertical_blinds_area_pricing()
    test_procurement_docx_requires_only_angular_rule()
    test_bnt_electrics_pdf_pricing()
    test_mounting_profile_is_not_installation_service()
    test_user_can_confirm_safe_angular_amg_rule()
    print("OK")
