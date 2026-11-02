"""JSON-file backed stand-in for the CRM, billing system and incident feed."""

import json
from functools import cached_property
from pathlib import Path
from typing import Any


class MockDatabase:
    def __init__(self, data_dir: Path) -> None:
        self._dir = data_dir / "mock_db"

    def _load(self, filename: str) -> Any:
        return json.loads((self._dir / filename).read_text(encoding="utf-8"))

    @cached_property
    def customers(self) -> dict[str, dict[str, Any]]:
        return self._load("customers.json")

    @cached_property
    def billing(self) -> dict[str, dict[str, Any]]:
        return self._load("billing.json")

    @cached_property
    def incidents(self) -> list[dict[str, Any]]:
        return self._load("incidents.json")
