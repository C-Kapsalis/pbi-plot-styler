"""FMT001: a hidden, locked report filter selects the format-selector item."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from .. import qx
from ..canvas import FormatSelectorSection, dig, read_json
from . import RuleContext, rewrite_json


def _targets(flt: Any, cfg: FormatSelectorSection) -> bool:
    column = dig(flt, "field", "Column")
    return (
        isinstance(column, dict)
        and dig(column, "Expression", "SourceRef", "Entity") == cfg.table
        and column.get("Property") == cfg.column
    )


def _selected(flt: dict) -> Any:
    """The first non-empty literal across the In rows of the filter."""
    for where in dig(flt, "filter", "Where") or []:
        for row in dig(where, "Condition", "In", "Values") or []:
            for cell in row if isinstance(row, list) else []:
                value = dig(cell, "Literal", "Value")
                if value not in (None, ""):
                    return value
    return None


def _problem(data: Any, cfg: FormatSelectorSection) -> str | None:
    """Why the report is not compliant, or ``None`` when it is."""
    if not isinstance(data, dict):
        return "report.json cannot be read"
    filters = dig(data, "filterConfig", "filters")
    targeting = [f for f in filters or [] if isinstance(f, dict) and _targets(f, cfg)]
    if not targeting:
        return f"no filter selects {cfg.table}[{cfg.column}]"
    if len(targeting) > 1:
        return f"{len(targeting) - 1} duplicate filter(s) on {cfg.table}[{cfg.column}]"
    only = targeting[0]
    want = _wanted(cfg.item)
    got = _selected(only)
    if got != want:
        return f"the filter selects {got!r} instead of {want}"
    if not only.get("isHiddenInViewMode"):
        return "the filter is not hidden in view mode"
    if not only.get("isLockedInViewMode"):
        return "the filter is not locked in view mode"
    return None


def _wanted(item: str) -> str:
    """The literal text of a filter that selects ``item``."""
    return qx.quoted(item)


def _active(ctx: RuleContext) -> bool:
    cfg = ctx.settings.format_selector
    if ctx.model is None:
        ctx.missing_model("format-selector")
        return False
    if ctx.model.table_named(cfg.table) is None:
        ctx.skip(f"format-selector: the paired model has no {cfg.table!r} table")
        return False
    return True


def check_format_selector(ctx: RuleContext) -> None:
    if not _active(ctx):
        return
    cfg = ctx.settings.format_selector
    path = ctx.report_dir / "definition" / "report.json"
    if not path.is_file():
        ctx.skip("format-selector: the report has no definition/report.json")
        return
    problem = _problem(read_json(path), cfg)
    ctx.checked["format-selector"] = 1
    if problem:
        ctx.add("FMT001", path, cfg.table,
                f"{problem}; measures fall back to their raw format strings",
                fixable=True)


def canonical_filter(cfg: FormatSelectorSection, name: str) -> dict:
    """The hidden, locked report filter selecting the format item."""
    alias = qx.alias_of(cfg.table)
    target = qx.field_ref("Column", cfg.column, alias=alias)
    condition = qx.in_values(target, [qx.quoted(cfg.item)])
    flt: dict = {"name": name, "ordinal": 0}
    flt["field"] = qx.column(cfg.table, cfg.column)
    flt["type"] = "Categorical"
    flt["filter"] = qx.filter_body(alias, cfg.table, condition)
    flt["howCreated"] = "User"
    flt["isHiddenInViewMode"] = True
    flt["isLockedInViewMode"] = True
    return flt


def fix_format_selector(ctx: RuleContext) -> list[tuple[Path, str]]:
    if not _active(ctx):
        return []
    cfg = ctx.settings.format_selector
    path = ctx.report_dir / "definition" / "report.json"
    if not path.is_file():
        return []
    data = read_json(path)
    if not isinstance(data, dict) or _problem(data, cfg) is None:
        return []
    new = copy.deepcopy(data)
    config = new.setdefault("filterConfig", {})
    filters = config.get("filters") if isinstance(config.get("filters"), list) else []
    targeting = [f for f in filters if isinstance(f, dict) and _targets(f, cfg)]
    name = targeting[0].get("name") if targeting and targeting[0].get("name") else cfg.filter_name
    config["filters"] = [canonical_filter(cfg, name)] + [
        f for f in filters if not (isinstance(f, dict) and _targets(f, cfg))
    ]
    if rewrite_json(path, new):
        return [(path, f"set the {cfg.table}[{cfg.column}] = '{cfg.item}' report filter")]
    return []
