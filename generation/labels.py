"""Source-label hygiene: drop citations the model invented and attach source metadata."""
from __future__ import annotations

from typing import Any

from prompt_engine.context_manager import SourceBundle


def clean_labels(data: Any, valid: set[str]) -> int:
    """Remove unknown labels from every `source_labels` list in place; returns how many were removed."""
    removed = 0
    if isinstance(data, dict):
        for key, value in data.items():
            if key == "source_labels" and isinstance(value, list):
                normalized = []
                for label in value:
                    lab = str(label).strip().strip("[]").upper()
                    if lab in valid:
                        normalized.append(lab)
                    else:
                        removed += 1
                data[key] = list(dict.fromkeys(normalized))
            else:
                removed += clean_labels(value, valid)
    elif isinstance(data, list):
        for item in data:
            removed += clean_labels(item, valid)
    return removed


def sources_payload(*bundles: SourceBundle) -> dict[str, dict[str, str]]:
    payload: dict[str, dict[str, str]] = {}
    for b in bundles:
        for label, chunk_id in b.label_map.items():
            payload[label] = {"chunk_id": chunk_id, "ref": b.references.get(label, "")}
    return payload
