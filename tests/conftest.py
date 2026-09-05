from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from labreceipt.contracts import Contract, contract_from_dict


@pytest.fixture
def contract_dict() -> dict[str, Any]:
    return {
        "schema_version": "1",
        "contract_id": "demo",
        "status": "confirmed",
        "reviewed_by": "alice",
        "artifacts": [
            {"id": "source", "path": "source.txt", "depends_on": [], "max_bytes": 4096},
            {"id": "report", "path": "report.json", "depends_on": ["source"], "max_bytes": 4096},
        ],
        "rules": [
            {"id": "source_exists", "type": "exists", "artifact": "source", "config": {}},
            {"id": "source_utf8", "type": "utf8", "artifact": "source", "config": {}},
            {
                "id": "report_schema",
                "type": "json_schema",
                "artifact": "report",
                "config": {
                    "schema": {
                        "type": "object",
                        "required": ["answer"],
                        "properties": {"answer": {"type": "integer"}},
                    }
                },
            },
        ],
    }


@pytest.fixture
def contract(contract_dict: dict[str, Any]) -> Contract:
    return contract_from_dict(contract_dict)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "source.txt").write_text("input\n", encoding="utf-8")
    (tmp_path / "report.json").write_text('{"answer":42}\n', encoding="utf-8")
    return tmp_path


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
