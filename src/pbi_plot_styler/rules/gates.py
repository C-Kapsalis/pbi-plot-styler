"""Slicer gates: visual-level ``[f-Slicer] > 0`` / ``[f-All] > 0`` filters.

A canvas stacks several selector slicers and shows only the relevant one:
each slicer carries a visual-level filter on a gate measure that returns 0
when the slicer should hide. Two rules share the gate shapes here:

``slicer-gates`` (GAT001, GAT002)
    every selector slicer on a visible canvas page has an *active* gate on
    the slicer measure, and every bookmark capture of such a slicer keeps it.

``slicer-mode-gates`` (GAT003, GAT004, GAT005)
    each slicer gates on the measure its mode needs (dropdown -> slicer
    measure, vertical list -> list measure), bound to the table that
    declares it, and no gate reference names another table.

Both fixers write byte-identical gate shapes, so running them in either
order gives the same files.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .. import qx
from ..canvas import Bookmark, Visual, dig, slicer_mode, slicer_selector_tables
from ..tmdl import SemanticModel
from . import RuleContext, RuleError, rewrite_json


# -- gate shapes ------------------------------------------------------------------
def gate_body(table: str, measure: str) -> dict:
    """``[measure] > 0`` over ``table``: the active gate condition."""
    alias = qx.alias_of(table, "g")
    left = qx.field_ref("Measure", measure, alias=alias)
    return qx.filter_body(alias, table, qx.comparison(1, left, qx.lit("0L")))


def visual_gate(table: str, measure: str, name: str) -> dict:
    gate: dict = {"name": name, "ordinal": 1}
    gate["field"] = qx.measure(table, measure)
    gate["type"] = "Advanced"
    gate["filter"] = gate_body(table, measure)
    gate["howCreated"] = "User"
    return gate


def bookmark_gate(table: str, measure: str, name: str) -> dict:
    gate: dict = {"name": name, "type": "Advanced"}
    gate["filter"] = gate_body(table, measure)
    gate["expression"] = qx.measure(table, measure)
    gate["howCreated"] = 1
    return gate


def _fresh_name(*parts: str) -> str:
    """A stable 20-hex-character filter name (stable, so reruns agree)."""
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:20]


def is_active(flt: Any) -> bool:
    """Whether a filter body compares the gate against 0 (> 0) or 1 (>= 1)."""
    for where in dig(flt, "Where") or []:
        comparison = dig(where, "Condition", "Comparison")
        if not isinstance(comparison, dict):
            continue
        kind = comparison.get("ComparisonKind")
        value = dig(comparison, "Right", "Literal", "Value")
        if (kind, value) in ((1, "0L"), (2, "1L")):
            return True
    return False


# -- reading gates ----------------------------------------------------------------
def _visual_filters(visual: Visual) -> list:
    filters = dig(visual.data, "filterConfig", "filters")
    return filters if isinstance(filters, list) else []


def _bound_to(entry: Any, measure: str, where: str) -> bool:
    return dig(entry, where, "Measure", "Property") == measure


def _first_visual_gate(visual: Visual, measure: str) -> dict | None:
    return next((f for f in _visual_filters(visual) if _bound_to(f, measure, "field")), None)


def _by_name(container: Any) -> dict:
    found = dig(container, "filters", "byName")
    return found if isinstance(found, dict) else {}


def _first_bookmark_gate(container: Any, measure: str) -> tuple[str, dict] | None:
    for key, entry in _by_name(container).items():
        if _bound_to(entry, measure, "expression"):
            return key, entry
    return None


def gate_state(entry: Any, where: str, table: str | None) -> str:
    """``absent``, ``passive``, ``wrong_entity`` or ``ok`` for one gate entry."""
    if entry is None:
        return "absent"
    if not is_active(entry.get("filter")):
        return "passive"
    entity = dig(entry, where, "Measure", "Expression", "SourceRef", "Entity")
    if table is not None and entity != table:
        return "wrong_entity"
    return "ok"


# -- shared fix steps -------------------------------------------------------------
def _set_visual_gate(visual: Visual, table: str, measure: str) -> None:
    filters = visual.data.setdefault("filterConfig", {}).setdefault("filters", [])
    for i, existing in enumerate(filters):
        if _bound_to(existing, measure, "field"):
            name = existing.get("name") or _fresh_name(visual.page_id, visual.folder, measure)
            filters[i] = visual_gate(table, measure, name)
            return
    filters.append(visual_gate(table, measure, _fresh_name(visual.page_id, visual.folder, measure)))


def _set_bookmark_gate(container: dict, table: str, measure: str, seed: str) -> None:
    by_name = container.setdefault("filters", {}).setdefault("byName", {})
    found = _first_bookmark_gate(container, measure)
    if found is not None:
        key, entry = found
        by_name[key] = bookmark_gate(table, measure, entry.get("name") or key)
    else:
        name = _fresh_name(seed, measure)
        by_name[name] = bookmark_gate(table, measure, name)


# -- slicer-gates -------------------------------------------------------------------
@dataclass
class _Capture:
    bookmark: Bookmark
    page_id: str
    container_id: str
    container: dict


def _selector_slicers_on_visible_canvas(ctx: RuleContext) -> list[Visual]:
    settings = ctx.settings
    canvas = set(ctx.index.canvas_page_ids(settings))
    found = []
    for page in ctx.index.pages:
        if page.page_id not in canvas or page.hidden:
            continue
        for visual in page.visuals:
            if visual.vtype != "slicer":
                continue
            heuristic = settings.gates.name_heuristic and all(
                token in visual.semantic_name.lower() for token in ("slicer", "selector")
            )
            if slicer_selector_tables(visual, settings) or heuristic:
                found.append(visual)
    return found


def _bookmark_selector_captures(ctx: RuleContext) -> Iterator[_Capture]:
    canvas = set(ctx.index.canvas_page_ids(ctx.settings))
    for bookmark in ctx.bookmarks:
        for page_id, section in bookmark.sections.items():
            if page_id not in canvas:
                continue
            for cid, container in bookmark.containers(section).items():
                if dig(container, "singleVisual", "visualType") != "slicer":
                    continue
                values = dig(container, "singleVisual", "activeProjections", "Values") or []
                entities = [dig(v, "Column", "Expression", "SourceRef", "Entity") for v in values]
                if any(ctx.settings.is_selector_table(e) for e in entities):
                    yield _Capture(bookmark, page_id, cid, container)


def _capture_has_gate(capture: _Capture, measure: str) -> bool:
    found = _first_bookmark_gate(capture.container, measure)
    return found is not None and is_active(found[1].get("filter"))


def check_slicer_gates(ctx: RuleContext) -> None:
    measure = ctx.settings.gates.slicer_measure
    slicers = _selector_slicers_on_visible_canvas(ctx)
    ctx.checked["slicer-gates"] = len(slicers)
    if not slicers:
        ctx.skip("slicer-gates: no selector slicer on a visible canvas page")
    for visual in slicers:
        gate = _first_visual_gate(visual, measure)
        if gate is None or not is_active(gate.get("filter")):
            ctx.add("GAT001", visual.path, visual.semantic_name,
                    f"selector slicer {visual.semantic_name!r} has no active "
                    f"[{measure}] > 0 filter, so it is always visible", fixable=True)
    for capture in _bookmark_selector_captures(ctx):
        if not _capture_has_gate(capture, measure):
            ctx.add("GAT002", capture.bookmark.path,
                    f"{capture.page_id}/{capture.container_id}",
                    f"bookmark {capture.bookmark.display_name!r} captures selector "
                    f"slicer {capture.container_id!r} without its [{measure}] gate; "
                    f"applying the bookmark removes the gate", fixable=True)


def _declaring_table(model: SemanticModel | None, measure: str, report: str) -> str:
    table = model.declaring_table(measure) if model is not None else None
    if table is None:
        raise RuleError(
            f"{report}: no table of the paired model declares [{measure}], so the "
            f"gate cannot be bound; nothing was changed"
        )
    return table


def fix_slicer_gates(ctx: RuleContext) -> list[tuple[Path, str]]:
    measure = ctx.settings.gates.slicer_measure
    slicers = [
        v for v in _selector_slicers_on_visible_canvas(ctx)
        if not is_active((_first_visual_gate(v, measure) or {}).get("filter"))
    ]
    captures = [c for c in _bookmark_selector_captures(ctx) if not _capture_has_gate(c, measure)]
    if not slicers and not captures:
        return []
    table = _declaring_table(ctx.model, measure, ctx.label)
    changes: list[tuple[Path, str]] = []
    for visual in slicers:
        _set_visual_gate(visual, table, measure)
        if rewrite_json(visual.path, visual.data):
            changes.append((visual.path, f"active [{measure}] gate on {table!r}"))
    touched: dict[Path, Bookmark] = {}
    for capture in captures:
        _set_bookmark_gate(capture.container, table, measure,
                           f"{capture.page_id}/{capture.container_id}")
        touched[capture.bookmark.path] = capture.bookmark
    for path, bookmark in touched.items():
        if rewrite_json(path, bookmark.data):
            changes.append((path, f"bookmark gate [{measure}] on {table!r}"))
    return changes


# -- slicer-mode-gates ----------------------------------------------------------------
def gate_host_table(ctx: RuleContext) -> str:
    """The first table of the report's model declaring both gate measures.

    The model is the one every other rule uses (``definition.pbir`` or
    ``--model``), so nested report layouts resolve the same way.
    """
    gates = ctx.settings.gates
    if ctx.model is not None:
        for table, measures in ctx.model.measures_by_table.items():
            if gates.slicer_measure in measures and gates.list_measure in measures:
                return table
    raise RuleError(
        f"{ctx.label}: the paired semantic model does not declare both "
        f"[{gates.slicer_measure}] and [{gates.list_measure}] on one table "
        f"(expected {gates.table!r}); nothing was checked or changed"
    )


@dataclass
class _ModeSlicer:
    visual: Visual
    measure: str


def _mode_slicers(ctx: RuleContext) -> list[_ModeSlicer]:
    canvas = set(ctx.index.canvas_page_ids(ctx.settings))
    found = []
    for visual in ctx.index.visuals():
        if visual.page_id not in canvas or visual.vtype != "slicer":
            continue
        measure = ctx.settings.gates.measure_for_mode(slicer_mode(visual))
        if measure is not None:
            found.append(_ModeSlicer(visual, measure))
    return found


def _mode_captures(ctx: RuleContext, slicers: list[_ModeSlicer]) -> Iterator[tuple[Bookmark, str, dict, str]]:
    wanted = {s.visual.folder: s.measure for s in slicers}
    for bookmark in ctx.bookmarks:
        for section in bookmark.sections.values():
            for cid, container in bookmark.containers(section).items():
                if cid in wanted and isinstance(container, dict):
                    yield bookmark, cid, container, wanted[cid]


def _stale_refs(node: Any, gate_measures: set[str], table: str, *, repair: bool) -> int:
    """Count (and optionally repoint) gate references naming another table."""
    count = 0
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, list):
            stack.extend(current)
            continue
        if not isinstance(current, dict):
            continue
        measure = current.get("Measure")
        if isinstance(measure, dict) and measure.get("Property") in gate_measures:
            ref = dig(measure, "Expression", "SourceRef")
            if isinstance(ref, dict) and isinstance(ref.get("Entity"), str) and ref["Entity"] != table:
                count += 1
                if repair:
                    ref["Entity"] = table
        flt = current.get("filter")
        if isinstance(flt, dict) and _mentions(current, gate_measures):
            for source in flt.get("From") or []:
                if isinstance(source, dict) and isinstance(source.get("Entity"), str) \
                        and source["Entity"] != table:
                    count += 1
                    if repair:
                        source["Entity"] = table
        stack.extend(current.values())
    return count


def _mentions(node: Any, gate_measures: set[str]) -> bool:
    text = json.dumps(node, ensure_ascii=False)
    return any(json.dumps(m, ensure_ascii=False) in text for m in gate_measures)


def _gate_measures(ctx: RuleContext) -> set[str]:
    return {ctx.settings.gates.slicer_measure, ctx.settings.gates.list_measure}


def _report_documents(ctx: RuleContext) -> Iterator[tuple[Path, Any]]:
    for visual in ctx.index.visuals():
        yield visual.path, visual.data
    for bookmark in ctx.bookmarks:
        yield bookmark.path, bookmark.data


_STATE_IDS = {"absent": "GAT003", "passive": "GAT003", "wrong_entity": "GAT004"}


def check_mode_gates(ctx: RuleContext) -> None:
    table = gate_host_table(ctx)
    slicers = _mode_slicers(ctx)
    ctx.checked["slicer-mode-gates"] = len(slicers)
    for slicer in slicers:
        visual = slicer.visual
        state = gate_state(_first_visual_gate(visual, slicer.measure), "field", table)
        if state != "ok":
            ctx.add(_STATE_IDS[state], visual.path, visual.folder,
                    f"{slicer_mode(visual)} slicer {visual.folder!r}: [{slicer.measure}] "
                    f"gate is {state.replace('_', ' ')} (expected an active gate on "
                    f"{table!r})", fixable=True)
    for bookmark, cid, container, measure in _mode_captures(ctx, slicers):
        found = _first_bookmark_gate(container, measure)
        state = gate_state(found[1] if found else None, "expression", table)
        if state != "ok":
            ctx.add(_STATE_IDS[state], bookmark.path, f"{cid}",
                    f"bookmark {bookmark.display_name!r} captures {cid!r} with its "
                    f"[{measure}] gate {state.replace('_', ' ')}", fixable=True)
    gate_measures = _gate_measures(ctx)
    for path, data in _report_documents(ctx):
        stale = _stale_refs(data, gate_measures, table, repair=False)
        if stale:
            ctx.add("GAT005", path, "stale gate entities",
                    f"{stale} gate reference(s) name a table other than {table!r}",
                    fixable=True)


def fix_mode_gates(ctx: RuleContext) -> list[tuple[Path, str]]:
    table = gate_host_table(ctx)
    slicers = _mode_slicers(ctx)
    dirty: dict[Path, Any] = {}
    for slicer in slicers:
        visual = slicer.visual
        if gate_state(_first_visual_gate(visual, slicer.measure), "field", table) != "ok":
            _set_visual_gate(visual, table, slicer.measure)
            dirty[visual.path] = visual.data
    for bookmark, cid, container, measure in _mode_captures(ctx, slicers):
        found = _first_bookmark_gate(container, measure)
        if gate_state(found[1] if found else None, "expression", table) != "ok":
            _set_bookmark_gate(container, table, measure, cid)
            dirty[bookmark.path] = bookmark.data
    gate_measures = _gate_measures(ctx)
    for path, data in _report_documents(ctx):
        if _stale_refs(data, gate_measures, table, repair=True):
            dirty[path] = data
    return [
        (path, f"slicer gates bound to {table!r}")
        for path, data in dirty.items()
        if rewrite_json(path, data)
    ]
