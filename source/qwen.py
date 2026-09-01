from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class QwenClient:
    def __init__(self, settings: dict[str, Any], logger=print) -> None:
        self.settings = settings
        self.log = logger

    def extract_items(self, records: list[dict[str, Any]], rag_context: str = "") -> list[dict[str, Any]]:
        if not records:
            return []
        result: list[dict[str, Any]] = []
        batch_size = int(self.settings.get("batch_size", 6))
        total_batches = (len(records) + batch_size - 1) // batch_size
        for start in range(0, len(records), batch_size):
            batch = records[start:start + batch_size]
            self.log(f"Qwen: разбираю пачку {start // batch_size + 1}/{total_batches} ({len(batch)} записей).")
            parsed = self._extract_batch(batch, rag_context)
            if not parsed:
                self.log("Qwen не ответил корректно; использую детерминированный разбор для оставшихся позиций.")
                break
            result.extend(parsed)
        return result

    def _extract_batch(self, records: list[dict[str, Any]], rag_context: str) -> list[dict[str, Any]]:
        prompt = """Извлеки позиции ТЗ для расчёта солнцезащитных систем.
Верни JSON-объект с единственным полем items — массивом позиций. Поля каждой позиции:
source_ref, name, quantity, width_m, height_m, area_m2, system, fabric, color, opacity, split_into.
Обязательны name и quantity. Размер может быть ширина+высота ИЛИ площадь.
Не путай подписи ШхВ и ВхШ. Не выдумывай отсутствующие данные. split_into>1 только при явном указании.
Входные записи:\n""" + json.dumps(records, ensure_ascii=False)
        if rag_context:
            prompt += "\nКраткие прецеденты. Используй только для понимания структуры, не копируй из них числа:\n" + rag_context
        payload = {
            "model": self.settings["model"],
            "stream": False,
            "format": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "source_ref": {"type": "string"},
                                "name": {"type": "string"},
                                "quantity": {"type": ["integer", "null"]},
                                "width_m": {"type": ["number", "null"]},
                                "height_m": {"type": ["number", "null"]},
                                "area_m2": {"type": ["number", "null"]},
                                "system": {"type": ["string", "null"]},
                                "fabric": {"type": ["string", "null"]},
                                "color": {"type": ["string", "null"]},
                                "opacity": {"type": ["string", "null"]},
                                "split_into": {"type": ["integer", "null"]},
                            },
                            "required": ["source_ref", "name", "quantity", "width_m", "height_m", "area_m2", "system", "fabric", "color", "opacity", "split_into"],
                        },
                    }
                },
                "required": ["items"],
            },
            "think": bool(self.settings.get("think", False)),
            "messages": [
                {"role": "system", "content": "Ты извлекаешь факты из ТЗ. Отвечай строго JSON без пояснений."},
                {"role": "user", "content": prompt},
            ],
            "options": {
                "temperature": float(self.settings.get("temperature", 0)),
                "num_ctx": int(self.settings.get("num_ctx", 4096)),
                "num_predict": int(self.settings.get("num_predict", 900)),
            },
        }
        request = urllib.request.Request(
            self.settings["url"],
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=int(self.settings.get("timeout_seconds", 8))) as response:
                content = json.loads(response.read().decode("utf-8"))["message"]["content"]
            parsed = json.loads(content)
            if isinstance(parsed, dict) and isinstance(parsed.get("items"), list):
                return parsed["items"]
            if isinstance(parsed, list):
                return parsed
            # Совместимость с одиночным объектом у старых версий Ollama.
            if isinstance(parsed, dict) and parsed.get("source_ref"):
                return [parsed]
            return []
        except (urllib.error.URLError, TimeoutError, KeyError, ValueError, json.JSONDecodeError) as error:
            self.log(f"Qwen недоступен или вернул ошибку: {error}")
            return []
