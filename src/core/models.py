"""
Core data contracts shared between agents.

These dataclasses are the "interfaces" between pipeline stages. No agent
should reach into another agent's internals -- they only pass these
objects back and forth. Keeping this file small and stable is what makes
the rest of the codebase easy to modify safely.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class IssueSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class Issue:
    """A single loggable problem or note, always traceable to a location."""
    severity: IssueSeverity
    sheet: str
    message: str
    row: Optional[int] = None          # 1-indexed source row in the sheet
    column: Optional[str] = None       # raw header text, if applicable

    def to_dict(self) -> dict:
        return {
            "severity": self.severity.value,
            "sheet": self.sheet,
            "row": self.row,
            "column": self.column,
            "message": self.message,
        }


@dataclass
class MergedRegion:
    sheet: str
    range_str: str          # e.g. "A1:C1"
    anchor_value: Any       # the value openpyxl keeps in the top-left cell


@dataclass
class SheetProfile:
    """Structural facts about one worksheet, gathered before any data is
    trusted or transformed."""
    name: str
    n_rows: int
    n_cols: int
    header_row_index: Optional[int]     # 0-indexed row within the raw grid
    candidate_header_rows: list[int]    # other rows considered, for transparency
    merged_regions: list[MergedRegion] = field(default_factory=list)
    hidden_row_indices: list[int] = field(default_factory=list)
    hidden_col_letters: list[str] = field(default_factory=list)
    has_formulas: bool = False
    is_sparse: bool = False             # >70% empty cells
    notes: list[str] = field(default_factory=list)


@dataclass
class FieldMapping:
    """Result of mapping one raw header string to a canonical schema field."""
    raw_header: str
    canonical_field: Optional[str]      # None if unmapped
    confidence: float                   # 0.0 - 1.0
    method: str                         # "exact" | "fuzzy" | "llm" | "unmapped"

    def to_dict(self) -> dict:
        return {
            "raw_header": self.raw_header,
            "canonical_field": self.canonical_field,
            "confidence": round(self.confidence, 3),
            "method": self.method,
        }


@dataclass
class Record:
    """One extracted, cleaned row -- always traceable back to its source."""
    data: dict[str, Any]
    source_sheet: str
    source_row: int             # 1-indexed row number in the original sheet
    record_issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        out = dict(self.data)
        out["_source_sheet"] = self.source_sheet
        out["_source_row"] = self.source_row
        if self.record_issues:
            out["_issues"] = self.record_issues
        return out


@dataclass
class ValidationReport:
    sheet: str
    raw_row_count: int
    extracted_record_count: int
    dropped_row_count: int
    dropped_reasons: dict[str, int]         # reason -> count
    duplicate_count: int
    duplicate_row_refs: list[tuple[int, int]]  # (row_a, row_b) pairs
    suspicious_value_count: int
    field_confidence: dict[str, float]      # canonical_field -> avg confidence

    def to_dict(self) -> dict:
        return {
            "sheet": self.sheet,
            "raw_row_count": self.raw_row_count,
            "extracted_record_count": self.extracted_record_count,
            "dropped_row_count": self.dropped_row_count,
            "dropped_reasons": self.dropped_reasons,
            "duplicate_count": self.duplicate_count,
            "duplicate_row_refs": self.duplicate_row_refs,
            "suspicious_value_count": self.suspicious_value_count,
            "field_confidence": {k: round(v, 3) for k, v in self.field_confidence.items()},
        }


@dataclass
class ExtractionContext:
    """The single object that flows through the whole pipeline. Each agent
    reads what it needs from here and writes its results back onto it."""
    input_path: str
    output_dir: str
    sheet_profiles: dict[str, SheetProfile] = field(default_factory=dict)
    schema_maps: dict[str, dict[str, FieldMapping]] = field(default_factory=dict)  # sheet -> {header: mapping}
    records: list[Record] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    validation_reports: list[ValidationReport] = field(default_factory=list)

    def add_issue(self, severity: IssueSeverity, sheet: str, message: str,
                  row: Optional[int] = None, column: Optional[str] = None) -> None:
        self.issues.append(Issue(severity=severity, sheet=sheet, message=message,
                                  row=row, column=column))
