from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field


class ChangeResult(BaseModel):
    is_material: bool
    is_terminal: bool = False
    is_critical: bool = False
    changed_fields: list[str] = Field(default_factory=list)
    change_type: str = "unknown"
    reason: str = ""


class ChangeDetector(ABC):
    @abstractmethod
    def detect(self, old_raw: dict, new_raw: dict) -> ChangeResult: ...

    @abstractmethod
    def source_type(self) -> str: ...
