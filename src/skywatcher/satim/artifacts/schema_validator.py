from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
import json
from jsonschema import Draft202012Validator

@dataclass(frozen=True)
class ValidationIssue:
    path: str
    message: str

class ArtifactSchemaValidator:
    def __init__(self, schema_path: str | Path):
        self.schema_path = Path(schema_path)
        self.schema = json.loads(self.schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(self.schema)
        self._validator = Draft202012Validator(self.schema)

    def validate(self, payload: Mapping[str, Any]) -> list[ValidationIssue]:
        issues=[]
        for error in sorted(self._validator.iter_errors(payload), key=lambda e: list(e.absolute_path)):
            path = "/" + "/".join(str(x) for x in error.absolute_path)
            issues.append(ValidationIssue(path or "/", error.message))
        return issues

    def require_valid(self, payload: Mapping[str, Any]) -> None:
        issues=self.validate(payload)
        if issues:
            joined="; ".join(f"{i.path}: {i.message}" for i in issues)
            raise ValueError(f"invalid SATIM artifact assessment: {joined}")
