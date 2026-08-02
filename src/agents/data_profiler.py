"""
Data Profiler Agent.

Generates column-level summary statistics, data distribution metrics, null counts,
value ranges for numeric/date fields, and overall quality scores.
"""

from __future__ import annotations

from collections import Counter
import datetime
import logging
import re
from typing import Any

from src.core.models import ColumnProfile, ExtractionContext

logger = logging.getLogger("excel_agent.data_profiler")

DATE_ISO_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}")


class DataProfilerAgent:
    def profile(self, ctx: ExtractionContext) -> None:
        if not ctx.records:
            ctx.column_profiles = []
            return

        all_fields: set[str] = set()
        for r in ctx.records:
            for k in r.data.keys():
                if not k.startswith("_"):
                    all_fields.add(k)

        sorted_fields = sorted(all_fields)
        profiles: list[ColumnProfile] = []

        total_records = len(ctx.records)

        invalid_counts: dict[str, int] = {}
        for issue in ctx.issues:
            if issue.column:
                invalid_counts[issue.column] = invalid_counts.get(issue.column, 0) + 1

        for field_name in sorted_fields:
            raw_vals = [r.data.get(field_name) for r in ctx.records]
            null_count = sum(
                1 for v in raw_vals
                if v is None or (isinstance(v, str) and v.strip() == "")
            )
            null_pct = (null_count / total_records * 100.0) if total_records > 0 else 0.0

            non_nulls = [
                v for v in raw_vals
                if v is not None and not (isinstance(v, str) and v.strip() == "")
            ]

            unique_count = len(set(str(v).strip() for v in non_nulls))

            str_counts = Counter(str(v).strip() for v in non_nulls)
            top_values = str_counts.most_common(5)

            invalid_cnt = invalid_counts.get(field_name, 0)
            invalid_pct = (invalid_cnt / total_records * 100.0) if total_records > 0 else 0.0

            quality_score = max(0.0, round(100.0 - (null_pct * 0.5 + invalid_pct * 0.5), 1))

            min_val, max_val, mean_val = None, None, None
            nums: list[float] = []
            for v in non_nulls:
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    nums.append(float(v))
                elif isinstance(v, str):
                    try:
                        clean_v = v.replace(",", "").strip()
                        nums.append(float(clean_v))
                    except ValueError:
                        pass

            if nums and len(nums) >= len(non_nulls) * 0.5:
                min_val = round(min(nums), 2)
                max_val = round(max(nums), 2)
                mean_val = round(sum(nums) / len(nums), 2)

            min_date, max_date = None, None
            dates: list[str] = []
            for v in non_nulls:
                if isinstance(v, (datetime.date, datetime.datetime)):
                    dates.append(v.strftime("%Y-%m-%d"))
                elif isinstance(v, str) and DATE_ISO_REGEX.match(v.strip()):
                    dates.append(v.strip()[:10])

            if dates and len(dates) >= len(non_nulls) * 0.5:
                min_date = min(dates)
                max_date = max(dates)

            profiles.append(
                ColumnProfile(
                    field_name=field_name,
                    total_count=total_records,
                    null_count=null_count,
                    null_percentage=null_pct,
                    unique_count=unique_count,
                    top_values=top_values,
                    min_value=min_val,
                    max_value=max_val,
                    mean_value=mean_val,
                    min_date=min_date,
                    max_date=max_date,
                    invalid_count=invalid_cnt,
                    invalid_percentage=invalid_pct,
                    quality_score=quality_score,
                )
            )

        ctx.column_profiles = profiles
        logger.info("Generated data profile for %d columns.", len(profiles))
