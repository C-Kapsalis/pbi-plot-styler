"""FMT001: a hidden, locked report filter selects the format-selector item."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from .. import qx
from ..canvas import FormatSelectorSection, dig
from ..textio import load_json
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
        return f"no report-level filter on {cfg.table}[{cfg.column}]"
    if len(targeting) > 1:
        return f"{len(targeting)} duplicate filters on the same field"
    only = targeting[0]
    want = _wanted(cfg.item)
    got = _selected(only)
    if got != want:
        return (f"filter value is {got!r}, expected {want!r} - the calc group's "
                f"'{cfg.item}' item won't be in scope.")
    if not only.get("isHiddenInViewMode"):
        return "filter is not hidden (isHiddenInViewMode != true)"
    if not only.get("isLockedInViewMode"):
        return "filter is not locked (isLockedInViewMode != true)"
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


def _report_json(ctx: RuleContext) -> tuple[Path, Any, str | None]:
    """The report's ``report.json``, its content and the read error, if any."""
    path = ctx.report_dir / "definition" / "report.json"
    if not path.is_file():
        return path, None, None
    try:
        return path, load_json(path), None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return path, None, str(exc)


def check_format_selector(ctx: RuleContext) -> None:
    if not _active(ctx):
        return
    cfg = ctx.settings.format_selector
    path, data, error = _report_json(ctx)
    if not path.is_file():
        ctx.skip("format-selector: the report has no definition/report.json")
        ctx.details["format-selector"] = {"reports": 0, "active": 1}
        return
    ctx.checked["format-selector"] = 1
    ctx.details["format-selector"] = {"reports": 1, "active": 1}
    if error is not None:
        ctx.add("FMT001", path, cfg.table,
                f"{path.resolve()}: could not parse {path.resolve()}: {error}",
                fixable=True)
        return
    problem = _problem(data, cfg)
    if problem:
        ctx.add("FMT001", path, cfg.table, f"{path.resolve()}: {problem}", fixable=True)


def render_format_selector(findings, counts, framing, values) -> list[str]:
    """The block of a format-selector check: the header, the findings, the count."""
    if values.get("fixing"):
        return [framing(f) for f in findings]
    if not counts.get("active"):
        return []
    seen = counts.get("reports", 0)
    lines: list[str] = []
    if not findings:
        if seen:
            lines.append(f"All {seen} report(s) carry the z-Selector Format filter "
                         f"correctly.")
        else:
            lines.append(f"No *.Report directories found under {values['check_path']}")
        return lines
    lines.append(f"{len(findings)}/{seen} report(s) missing or misconfigured filter:")
    lines += [framing(f) for f in findings]
    return lines


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
    path, data, error = _report_json(ctx)
    if not path.is_file():
        return []
    ctx.checked.setdefault("format-selector", 1)
    ctx.details.setdefault("format-selector", {})["reports"] = 1
    if error is not None:
        ctx.options.setdefault("read_errors", []).append(
            (path, f"  ERROR reading {path.resolve()}: {error}"))
        return []
    reason = _problem(data, cfg)
    if reason is None:
        ctx.options.setdefault("format_fixes", []).append({"patched": 0, "seen": 1})
        return []
    new = copy.deepcopy(data)
    config = new.setdefault("filterConfig", {})
    filters = config.get("filters") if isinstance(config.get("filters"), list) else []
    targeting = [f for f in filters if isinstance(f, dict) and _targets(f, cfg)]
    name = targeting[0].get("name") if targeting and targeting[0].get("name") else cfg.filter_name
    config["filters"] = [canonical_filter(cfg, name)] + [
        f for f in filters if not (isinstance(f, dict) and _targets(f, cfg))
    ]
    written = rewrite_json(path, new)
    ctx.options.setdefault("format_fixes", []).append(
        {"patched": 1 if written else 0, "seen": 1})
    if written:
        return [(path, f"patched ({reason})")]
    return []


def render_format_selector_fix(ctx: RuleContext, changes: list[tuple[Path, str]]) -> list[str]:
    """The per-report line of a format-selector fix."""
    lines = []
    for path, description in changes:
        lines.append(f"  {path.resolve()}: {description}")
    return lines


def format_selector_fix_summary(contexts: dict) -> list[str]:
    """The closing count of a format-selector fix."""
    blocks = []
    for factory in contexts.values():
        ctx = factory()
        blocks += ctx.options.get("format_fixes") or []
    if not blocks:
        return []
    patched = sum(b["patched"] for b in blocks)
    seen = sum(b["seen"] for b in blocks)
    if patched:
        return ["", f"Patched {patched}/{seen} report(s)."]
    if seen:
        return [f"All {seen} report(s) already compliant; nothing to do."]
    return ["All 0 report(s) already compliant; nothing to do."]
