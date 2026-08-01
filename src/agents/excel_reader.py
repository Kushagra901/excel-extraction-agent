"""
Excel Reader Agent.

Responsible for turning a raw .xlsx workbook into:
  1. A SheetProfile per sheet (structural facts: header row, merged cells,
     hidden rows/cols, formulas, sparsity).
  2. A raw grid (list of lists) per sheet, with merged-cell values
     propagated to every cell in the merged region so downstream agents
     never have to deal with None-filled merge artifacts.

This agent does NOT clean or interpret data -- it only describes structure
and hands over the raw grid. Interpretation is the Schema Mapping Agent's
and Data Cleaning Agent's job.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.utils import range_boundaries

from src.core.models import IssueSeverity, MergedRegion, SheetProfile

logger = logging.getLogger("excel_agent.excel_reader")

MAX_HEADER_SEARCH_ROWS = 15


class ExcelReaderAgent:
    def __init__(self, sparse_row_threshold: float = 0.9):
        self.sparse_row_threshold = sparse_row_threshold

    def read_workbook(self, path: Path) -> tuple[dict[str, SheetProfile], dict[str, list[list[Any]]]]:
        """Returns (sheet_profiles, raw_grids) keyed by sheet name."""
        # data_only=True resolves formulas to their last calculated value.
        # data_only=False keeps formula strings so we can detect their presence.
        wb_values = openpyxl.load_workbook(path, data_only=True)
        wb_formulas = openpyxl.load_workbook(path, data_only=False)

        profiles: dict[str, SheetProfile] = {}
        grids: dict[str, list[list[Any]]] = {}

        for sheet_name in wb_values.sheetnames:
            ws_values = wb_values[sheet_name]
            ws_formulas = wb_formulas[sheet_name]

            grid = self._build_grid(ws_values)
            merged_regions = self._extract_merged_regions(ws_values, grid, sheet_name)
            self._propagate_merged_values(grid, merged_regions, ws_values)

            hidden_rows = [
                r for r in range(1, ws_values.max_row + 1)
                if ws_values.row_dimensions[r].hidden
            ]
            hidden_cols = [
                letter for letter, dim in ws_values.column_dimensions.items()
                if dim.hidden
            ]
            has_formulas = self._detect_formulas(ws_formulas)

            header_row_idx, candidates = self._detect_header_row(grid)
            is_sparse = self._is_sparse(grid)

            notes = []
            if header_row_idx is None:
                notes.append("Could not confidently detect a header row; "
                             "falling back to row 0 -- verify manually.")
            if is_sparse:
                notes.append("Sheet is >{:.0f}% empty cells overall.".format(
                    self.sparse_row_threshold * 100))

            profiles[sheet_name] = SheetProfile(
                name=sheet_name,
                n_rows=len(grid),
                n_cols=max((len(r) for r in grid), default=0),
                header_row_index=header_row_idx if header_row_idx is not None else 0,
                candidate_header_rows=candidates,
                merged_regions=merged_regions,
                hidden_row_indices=hidden_rows,
                hidden_col_letters=hidden_cols,
                has_formulas=has_formulas,
                is_sparse=is_sparse,
                notes=notes,
            )
            grids[sheet_name] = grid

            logger.info(
                "Sheet '%s': %d rows x %d cols | header row (0-indexed): %s | "
                "merged regions: %d | hidden rows: %d | hidden cols: %d | formulas: %s",
                sheet_name, profiles[sheet_name].n_rows, profiles[sheet_name].n_cols,
                header_row_idx, len(merged_regions), len(hidden_rows), len(hidden_cols),
                has_formulas,
            )
            for note in notes:
                logger.warning("Sheet '%s': %s", sheet_name, note)

        wb_values.close()
        wb_formulas.close()
        return profiles, grids

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_grid(ws) -> list[list[Any]]:
        grid: list[list[Any]] = []
        for row in ws.iter_rows(values_only=True):
            grid.append(list(row))
        return grid

    @staticmethod
    def _extract_merged_regions(ws, grid: list[list[Any]], sheet_name: str) -> list[MergedRegion]:
        regions = []
        for merged_range in ws.merged_cells.ranges:
            min_col, min_row, max_col, max_row = range_boundaries(str(merged_range))
            anchor_value = None
            if 0 <= min_row - 1 < len(grid) and 0 <= min_col - 1 < len(grid[min_row - 1]):
                anchor_value = grid[min_row - 1][min_col - 1]
            regions.append(MergedRegion(sheet=sheet_name, range_str=str(merged_range),
                                         anchor_value=anchor_value))
        return regions

    @staticmethod
    def _propagate_merged_values(grid: list[list[Any]], regions: list[MergedRegion], ws) -> None:
        """Fill every cell in a merged region with the anchor's value so
        downstream code never has to special-case None-from-merge."""
        for region in regions:
            min_col, min_row, max_col, max_row = range_boundaries(region.range_str)
            for r in range(min_row, max_row + 1):
                for c in range(min_col, max_col + 1):
                    ri, ci = r - 1, c - 1
                    if 0 <= ri < len(grid) and 0 <= ci < len(grid[ri]):
                        grid[ri][ci] = region.anchor_value

    @staticmethod
    def _detect_formulas(ws_formulas) -> bool:
        for row in ws_formulas.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    return True
        return False

    def _detect_header_row(self, grid: list[list[Any]]) -> tuple[int | None, list[int]]:
        """
        Heuristic header-row scoring:
          - higher fraction of non-empty cells that are strings -> more header-like
          - higher fraction of unique values -> more header-like (headers repeat rarely)
          - fully-numeric rows score low (usually data, not headers)
        Only searches the first MAX_HEADER_SEARCH_ROWS rows -- headers deep
        below that are rare and usually indicate a report needing manual review.
        """
        best_idx, best_score = None, 0.0
        candidates: list[int] = []
        search_limit = min(MAX_HEADER_SEARCH_ROWS, len(grid))

        for idx in range(search_limit):
            row = grid[idx]
            non_empty = [c for c in row if c is not None and str(c).strip() != ""]
            if not non_empty:
                continue

            str_ratio = sum(1 for c in non_empty if isinstance(c, str)) / len(non_empty)
            unique_ratio = len(set(str(c).strip().lower() for c in non_empty)) / len(non_empty)
            fill_ratio = len(non_empty) / max(len(row), 1)

            score = (str_ratio * 0.5) + (unique_ratio * 0.3) + (fill_ratio * 0.2)

            if score >= 0.55:
                candidates.append(idx)
            if score > best_score:
                best_score, best_idx = score, idx

        if best_score < 0.4:
            return None, candidates
        return best_idx, candidates

    def _is_sparse(self, grid: list[list[Any]]) -> bool:
        total = sum(len(row) for row in grid)
        if total == 0:
            return True
        empty = sum(
            1 for row in grid for c in row if c is None or str(c).strip() == ""
        )
        return (empty / total) >= self.sparse_row_threshold
