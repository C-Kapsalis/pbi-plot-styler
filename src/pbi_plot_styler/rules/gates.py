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
from . import RuleAbort, RuleContext, RuleError, rewrite_json, user_path


# -- gate shapes ------------------------------------------------------------------
def gate_alias(host: str) -> str:
    """The one ``From`` alias every gate uses: the default host table's letter.

    It stays the same whatever table actually declares the measure.
    """
    return qx.alias_of(host, "g")


def gate_body(table: str, measure: str, alias: str) -> dict:
    """``[measure] > 0`` over ``table``: the active gate condition."""
    left = qx.field_ref("Measure", measure, alias=alias)
    return qx.filter_body(alias, table, qx.comparison(1, left, qx.lit("0L")))


def visual_gate(table: str, measure: str, name: str, alias: str) -> dict:
    gate: dict = {"name": name, "ordinal": 1}
    gate["field"] = qx.measure(table, measure)
    gate["type"] = "Advanced"
    gate["filter"] = gate_body(table, measure, alias)
    gate["howCreated"] = "User"
    return gate


def bookmark_gate(table: str, measure: str, name: str, alias: str) -> dict:
    gate: dict = {"name": name, "type": "Advanced"}
    gate["filter"] = gate_body(table, measure, alias)
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


def _has_active_visual_gate(visual: Visual, measure: str) -> bool:
    """Any filter bound to ``measure`` is active (slicer-gates)."""
    return any(_bound_to(f, measure, "field") and is_active(f.get("filter"))
               for f in _visual_filters(visual))


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
def _set_visual_gate(visual: Visual, table: str, measure: str, alias: str) -> None:
    filters = visual.data.setdefault("filterConfig", {}).setdefault("filters", [])
    for i, existing in enumerate(filters):
        if _bound_to(existing, measure, "field"):
            name = existing.get("name") or _fresh_name(visual.page_id, visual.folder, measure)
            filters[i] = visual_gate(table, measure, name, alias)
            return
    filters.append(visual_gate(table, measure, _fresh_name(visual.page_id, visual.folder, measure),
                               alias))


def _capture_seed(page_id: str, container_id: str) -> str:
    """The seed of a new bookmark gate's name; both gate fixers use it."""
    return f"{page_id}/{container_id}"


def _set_bookmark_gate(container: dict, table: str, measure: str, seed: str, alias: str) -> None:
    by_name = container.setdefault("filters", {}).setdefault("byName", {})
    found = _first_bookmark_gate(container, measure)
    if found is not None:
        key, _entry = found
        by_name[key] = bookmark_gate(table, measure, key, alias)  # the name is the map key
    else:
        name = _fresh_name(seed, measure)
        by_name[name] = bookmark_gate(table, measure, name, alias)


# -- slicer-gates -------------------------------------------------------------------
@dataclass
class _Capture:
    bookmark: Bookmark
    page_id: str
    container_id: str
    container: dict


def _is_selector(ctx: RuleContext, entity) -> bool:
    """Is this table one of the model's field parameters?

    The model's own field parameters are detected from its TMDL; the name
    patterns are the fallback when the model could not be read.
    """
    detected = ctx.field_parameters()
    if detected:
        return entity in detected
    return ctx.settings.is_selector_table(entity)


def _selector_slicers_on_visible_canvas(ctx: RuleContext, *,
                                       heuristic: bool = True) -> list[Visual]:
    """Selector slicers on visible canvas pages.

    With ``heuristic`` (the check only), the optional name heuristic adds
    slicers whose name holds both ``slicer`` and ``selector``; the fixer
    never gates those.
    """
    settings = ctx.settings
    parameters = ctx.field_parameters()
    canvas = set(ctx.index.canvas_page_ids(settings))
    found = []
    for page in ctx.index.pages:
        if page.page_id not in canvas or page.hidden:
            continue
        for visual in page.visuals:
            if visual.vtype != "slicer":
                continue
            named = heuristic and settings.gates.name_heuristic and all(
                token in visual.semantic_name.lower() for token in ("slicer", "selector")
            )
            if slicer_selector_tables(visual, settings, parameters) or named:
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
                if any(_is_selector(ctx, e) for e in entities):
                    yield _Capture(bookmark, page_id, cid, container)


def _capture_has_gate(capture: _Capture, measure: str) -> bool:
    """Any filter of the capture bound to ``measure`` is active."""
    return any(_bound_to(entry, measure, "expression") and is_active(entry.get("filter"))
               for entry in _by_name(capture.container).values())


def check_slicer_gates(ctx: RuleContext) -> None:
    measure = ctx.settings.gates.slicer_measure
    slicers = _selector_slicers_on_visible_canvas(ctx)
    ctx.checked["slicer-gates"] = len(slicers)
    ctx.details["slicer-gates"] = {"selector slicers": len(slicers)}
    for visual in slicers:
        if not _has_active_visual_gate(visual, measure):
            ctx.add("GAT001", visual.path, visual.semantic_name,
                    f"{visual.semantic_name}  ({visual.path.resolve()})", fixable=True)
    for capture in _bookmark_selector_captures(ctx):
        if not _capture_has_gate(capture, measure):
            ctx.add("GAT002", capture.bookmark.path,
                    f"{capture.page_id}/{capture.container_id}",
                    f"{capture.bookmark.path.name} -> page {capture.page_id} "
                    f"vc {capture.container_id}", fixable=True)


def render_slicer_gates(findings, counts, framing, values) -> list[str]:
    """The blocks of a gate check: the visuals, the captures, the counts."""
    seen = counts.get("selector slicers", 0)
    visuals = [f for f in findings if f.check_id == "GAT001"]
    captures = [f for f in findings if f.check_id == "GAT002"]
    lines: list[str] = []
    if values.get("fixing"):
        return [framing(f) for f in findings]
    if seen == 0:
        lines.append(f"No Report field-parameter slicers found under {values['check_path']}")
    if visuals:
        lines.append(f"{len(visuals)}/{seen} visual(s) missing the active gate:")
        lines += [framing(f) for f in visuals]
    if captures:
        lines.append("")
        lines.append(f"{len(captures)} bookmark visualContainer(s) lack the active gate "
                     f"(would erase it on apply):")
        lines += [framing(f) for f in captures]
    if not findings and seen:
        lines.append(f"All {seen} Report slicer(s) carry active `f-Slicer > 0` gates "
                     f"AND all bookmarks restore them faithfully.")
    return lines


def _declaring_table(ctx: RuleContext, measure: str) -> str | None:
    """The table that declares the gate measure, or ``None`` when none does.

    A report the gate cannot be bound in is reported on stderr and left as
    it is; the other reports are still fixed.
    """
    if ctx.model is None:
        reason = ".pbir → .SemanticModel link couldn't be resolved"
    else:
        table = ctx.model.declaring_table(measure)
        if table is not None:
            return table
        reason = (f"no `measure '{measure}'` declaration found under "
                  f"{ctx.model.definition_dir / 'tables'}. The measure isn't defined "
                  f"— fix the model first.")
    ctx.options.setdefault("stderr_lines", []).append(
        f"  ERROR ({user_path(ctx, ctx.report_dir)}): {reason}\n"
        f"    skipping all violating slicers under this report.")
    return None


def fix_slicer_gates(ctx: RuleContext) -> list[tuple[Path, str]]:
    measure = ctx.settings.gates.slicer_measure
    slicers = [
        v for v in _selector_slicers_on_visible_canvas(ctx, heuristic=False)
        if not _has_active_visual_gate(v, measure)
    ]
    captures = [c for c in _bookmark_selector_captures(ctx) if not _capture_has_gate(c, measure)]
    table = _declaring_table(ctx, measure)
    if table is None:
        return []
    alias = gate_alias(ctx.settings.gates.table)
    changes: list[tuple[Path, str]] = []
    for visual in slicers:
        _set_visual_gate(visual, table, measure, alias)
        if rewrite_json(visual.path, visual.data):
            changes.append((visual.path, f"patched visual {visual.semantic_name}"))
    touched: dict[Path, Bookmark] = {}
    for capture in captures:
        _set_bookmark_gate(capture.container, table, measure,
                           _capture_seed(capture.page_id, capture.container_id), alias)
        touched[capture.bookmark.path] = capture.bookmark
    for path, bookmark in touched.items():
        if rewrite_json(path, bookmark.data):
            changes.append((path, f"patched bookmark {path.name}"))
    ctx.options.setdefault("gate_fixes", []).append({
        "report": user_path(ctx, ctx.report_dir),
        "table": table,
        "model": _model_table_path(ctx, table),
        "visuals": len(slicers),
        "seen": len(_selector_slicers_on_visible_canvas(ctx, heuristic=False)),
        "bookmarks": len(touched),
        "files": len(touched),
    })
    return changes


def _model_table_path(ctx: RuleContext, table: str) -> str:
    """Where the gate measure is declared, as the user sees it."""
    model = ctx.model
    if model is None:
        return table
    path = model.definition_dir / "tables" / f"{table}.tmdl"
    try:
        return ctx.rel(path)
    except ValueError:
        return path.as_posix()


def render_slicer_gates_fix(ctx: RuleContext, changes: list[tuple[Path, str]]) -> list[str]:
    """The per-report block of a gate fix."""
    blocks = ctx.options.get("gate_fixes") or []
    if not blocks:
        return []
    block = blocks[-1]
    lines = [f"  {block['report']}: source entity = {block['table']!r}  "
             f"(declared in {block['model']})"]
    for path, description in changes:
        if description.startswith("patched visual"):
            lines.append(f"    {description}")
    for path, description in changes:
        if description.startswith("patched bookmark"):
            lines.append(f"    {description}")
    return lines


def slicer_gates_fix_summary(contexts: dict) -> list[str]:
    """The closing count of a gate fix."""
    blocks = []
    for factory in contexts.values():
        ctx = factory()
        blocks += ctx.options.get("gate_fixes") or []
    if not blocks:
        return []
    patched = sum(b["visuals"] for b in blocks)
    seen = sum(b["seen"] for b in blocks)
    files = sum(b["files"] for b in blocks)
    if not patched and not files:
        return [f"All {seen} Report slicer(s) and bookmarks already gated; nothing to do."]
    return ["", f"Patched {patched}/{seen} visual(s) and {files} bookmark file(s)."]


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
    raise RuleAbort(
        f"!! could not find a table declaring both [{gates.slicer_measure}] and "
        f"[{gates.list_measure}] for {user_path(ctx, ctx.report_dir)}"
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


def _mode_captures(ctx: RuleContext, slicers: list[_ModeSlicer]
                   ) -> Iterator[tuple[Bookmark, str, str, dict, str]]:
    wanted = {s.visual.folder: s.measure for s in slicers}
    for bookmark in ctx.bookmarks:
        for page_id, section in bookmark.sections.items():
            for cid, container in bookmark.containers(section).items():
                if cid in wanted and isinstance(container, dict):
                    yield bookmark, page_id, cid, container, wanted[cid]


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
            used, stale = _gate_sources(current, gate_measures, table)
            for source in flt.get("From") or []:
                if not isinstance(source, dict) or not isinstance(source.get("Entity"), str) \
                        or source["Entity"] == table:
                    continue
                # only an alias a gate reference uses, or one naming the stale table
                if source.get("Name") in used or source["Entity"] in stale:
                    count += 1
                    if repair:
                        source["Entity"] = table
        stack.extend(current.values())
    return count


def _gate_sources(node: Any, gate_measures: set[str], table: str) -> tuple[set[str], set[str]]:
    """``(aliases, stale tables)`` the gate measure references under ``node`` use."""
    aliases: set[str] = set()
    stale: set[str] = set()
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
            if isinstance(ref, dict):
                if isinstance(ref.get("Source"), str):
                    aliases.add(ref["Source"])
                if isinstance(ref.get("Entity"), str) and ref["Entity"] != table:
                    stale.add(ref["Entity"])
        stack.extend(current.values())
    return aliases, stale


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
    visuals = entries = 0
    for slicer in slicers:
        visual = slicer.visual
        state = gate_state(_first_visual_gate(visual, slicer.measure), "field", table)
        if state != "ok":
            visuals += 1
            ctx.add(_STATE_IDS[state], visual.path, visual.folder,
                    f"{state:<12} {slicer_mode(visual):<9} -> {slicer.measure:<9} "
                    f"{visual.page_id}/{visual.folder}", fixable=True)
    for bookmark, _page_id, cid, container, measure in _mode_captures(ctx, slicers):
        found = _first_bookmark_gate(container, measure)
        state = gate_state(found[1] if found else None, "expression", table)
        if state != "ok":
            entries += 1
            ctx.add(_STATE_IDS[state], bookmark.path, f"{cid}",
                    f"bookmark {bookmark.display_name!r} captures {cid!r} with its "
                    f"[{measure}] gate {state}", fixable=True)
    gate_measures = _gate_measures(ctx)
    stale = files = 0
    for path, data in _report_documents(ctx):
        count = _stale_refs(data, gate_measures, table, repair=False)
        if count:
            stale += count
            files += 1
            ctx.add("GAT005", path, "stale gate entities",
                    f"{count} gate reference(s) name a table other than {table!r}",
                    fixable=True)
    ctx.details["slicer-mode-gates"] = {
        "visuals": visuals,
        "bookmark entries": entries,
        "stale references": stale,
        "stale files": files,
        "gate table": table,
    }


def render_mode_gates(findings, counts, framing, values) -> list[str]:
    """The block of a mode-gate check: the source, the findings, the totals."""
    table = counts.get("gate table", "")
    if values.get("fixing"):
        return [framing(finding) for finding in findings]
    lines = [f"  gate source entity (from TMDL): {table!r}"]
    lines += [framing(finding) for finding in findings]
    lines.append(f"  Would patch {counts.get('visuals', 0)} visual(s) and "
                 f"{counts.get('bookmark entries', 0)} bookmark entrie(s)")
    lines.append(f"  Would patch {counts.get('stale references', 0)} stale entity "
                 f"reference(s) -> {table!r} across {counts.get('stale files', 0)} file(s)")
    return lines


def fix_mode_gates(ctx: RuleContext) -> list[tuple[Path, str]]:
    table = gate_host_table(ctx)
    alias = gate_alias(ctx.settings.gates.table)
    slicers = _mode_slicers(ctx)
    dirty: dict[Path, Any] = {}
    states: list[str] = []
    visuals = 0
    for slicer in slicers:
        visual = slicer.visual
        state = gate_state(_first_visual_gate(visual, slicer.measure), "field", table)
        if state != "ok":
            visuals += 1
            states.append(f"{state:<12} {slicer_mode(visual):<9} -> {slicer.measure:<9} "
                          f"{visual.page_id}/{visual.folder}")
            _set_visual_gate(visual, table, slicer.measure, alias)
            dirty[visual.path] = visual.data
    entries = 0
    bookmarks: dict[Path, Any] = {}
    for bookmark, page_id, cid, container, measure in _mode_captures(ctx, slicers):
        found = _first_bookmark_gate(container, measure)
        if gate_state(found[1] if found else None, "expression", table) != "ok":
            entries += 1
            _set_bookmark_gate(container, table, measure, _capture_seed(page_id, cid), alias)
            bookmarks[bookmark.path] = bookmark.data
    dirty.update(bookmarks)
    gate_measures = _gate_measures(ctx)
    stale = stale_files = 0
    for path, data in _report_documents(ctx):
        count = _stale_refs(data, gate_measures, table, repair=True)
        if count:
            dirty[path] = data
    for path, data in _report_documents(ctx):
        count = _stale_refs(data, gate_measures, table, repair=False)
        if count:
            stale += count
            stale_files += 1
    changes = [
        (path, f"slicer gates bound to {table!r}")
        for path, data in dirty.items()
        if rewrite_json(path, data)
    ]
    ctx.options.setdefault("mode_gate_fixes", []).append({
        "table": table,
        "states": states,
        "visuals": visuals,
        "entries": entries,
        "files": len(bookmarks),
        "stale": stale,
        "stale files": stale_files,
        "bookmarks": sorted(bookmarks),
    })
    return changes


def render_mode_gates_fix(ctx: RuleContext, changes: list[tuple[Path, str]]) -> list[str]:
    """The per-report block of a mode-gate fix."""
    blocks = ctx.options.get("mode_gate_fixes") or []
    if not blocks:
        return []
    block = blocks[-1]
    lines = [f"  gate source entity (from TMDL): {block['table']!r}"]
    lines += [f"    {state}" for state in block["states"]]
    for path in block["bookmarks"]:
        lines.append(f"    patched bookmark {path.name}")
    return lines


def mode_gates_fix_summary(contexts: dict) -> list[str]:
    """The closing counts of a mode-gate fix."""
    blocks = []
    for factory in contexts.values():
        ctx = factory()
        blocks += ctx.options.get("mode_gate_fixes") or []
    if not blocks:
        return []
    visuals = sum(b["visuals"] for b in blocks)
    entries = sum(b["entries"] for b in blocks)
    files = sum(b["files"] for b in blocks)
    stale = sum(b["stale"] for b in blocks)
    stale_files = sum(b["stale files"] for b in blocks)
    table = blocks[-1]["table"]
    return [
        f"  Patched {visuals} visual(s) and {entries} bookmark entrie(s) across "
        f"{files} file(s)",
        f"  Patched {stale} stale entity reference(s) -> {table!r} across "
        f"{stale_files} file(s)",
    ]
