"""Whole-page answer bookmarks (ABK*, PGW*) and picker literals (BML*).

An answer bookmark (one per recurring question, display name
``<Analysis Category> | <Aspect>``) drives the whole canvas: the picker
selections, the category filter and the matrix capture. A bookmark whose
literals all resolve can still do nothing, so the checks here look at what
the bookmark actually persists:

=======  ==============================================================
ABK000   no bookmark matches the configured prefixes (vacuity guard)
ABK001   ``options.targetVisualNames`` missing or not exactly ``[]``
ABK003   the matrix is not captured, or captured as hidden
ABK004   the matrix rows are not this bookmark's row picks, or the capture
         carries a field inherited from the bookmark it was cloned from
ABK005   the capture keeps active Values projections or expansion states
ABK006   a captured picker selects nothing
ABK007   the analysis category is not pinned with a literal
ABK008   the bookmark is not a child of a submenu group
ABK009   the matrix slot map does not match the picks
ABK010   a row dimension is missing from the dropdown filters
PGW001   a field-parameter well on the main page projects a raw measure
PGW002   a bookmark navigator on the main page names a missing bookmark
=======  ==============================================================

``bookmark-literals`` (BML001, BML002) checks that each saved selection
literal is a row of the field parameter behind that very slicer.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path
from typing import Any

from ..canvas import (
    SELECTION_IN_TEXT,
    Bookmark,
    Page,
    Visual,
    dig,
    read_json,
    selections,
    slicer_selector_tables,
)
from . import RuleContext, RuleError
from ..textio import load_json


# -- scope ------------------------------------------------------------------------
@dataclass
class _Scope:
    main: Page
    matrix_id: str
    matrix: Visual | None
    slicer_for: dict[str, str | None] = dc_field(default_factory=dict)
    row_param: str | None = None
    row_dropdowns: list[str] = dc_field(default_factory=list)

    def declared(self, role: str) -> list[str]:
        if self.matrix is None:
            return []
        block = self.matrix.query_state.get(role) or {}
        found = []
        for param in block.get("fieldParameters") or []:
            entity = dig(param, "parameterExpr", "Column", "Expression", "SourceRef", "Entity")
            if isinstance(entity, str):
                found.append(entity)
        return found

    @property
    def row_slicer(self) -> str | None:
        return self.slicer_for.get(self.row_param) if self.row_param else None

    def picker_ids(self) -> list[str]:
        return sorted({sid for sid in self.slicer_for.values() if sid})


def _resolve_scope(ctx: RuleContext) -> _Scope:
    cfg = ctx.settings.answer_bookmarks
    index = ctx.index
    if cfg.main_page:
        main = index.page(cfg.main_page)
        if main is None:
            raise RuleError(f"{ctx.label}: [answer_bookmarks] main_page "
                            f"{cfg.main_page!r} is not a page of this report")
    else:
        main = index.main_page(ctx.settings)
        if main is None:
            raise RuleError(
                f"{ctx.label}: no canvas main page found (a page with "
                f"{ctx.settings.panel.min_slicers}+ slicers, a combo chart and a "
                f"matrix); set [answer_bookmarks] main_page"
            )
    visuals = {v.folder: v for v in main.visuals}
    if cfg.matrix:
        matrix_id = cfg.matrix
    else:
        candidates = [v.folder for v in main.visuals if v.vtype == "pivotTable"]
        if len(candidates) != 1:
            raise RuleError(
                f"{ctx.label}: page {main.page_id} has {len(candidates)} matrix "
                f"visual(s) {candidates}; set [answer_bookmarks] matrix"
            )
        matrix_id = candidates[0]
    scope = _Scope(main, matrix_id, visuals.get(matrix_id))

    configured = dict(cfg.slicers)
    wanted = list(dict.fromkeys(scope.declared("Rows") + scope.declared("Values")))
    for table in list(configured) + [t for t in wanted if t not in configured]:
        if table in configured:
            scope.slicer_for[table] = configured[table]
            continue
        matches = [
            v.folder for v in main.visuals
            if v.vtype == "slicer"
            and {e for e in v.query_entities() if ctx.settings.is_selector_table(e)} == {table}
        ]
        scope.slicer_for[table] = matches[0] if len(matches) == 1 else None
    rows = scope.declared("Rows")
    scope.row_param = rows[0] if rows else None
    if cfg.row_dropdowns is not None:
        scope.row_dropdowns = list(cfg.row_dropdowns)
    else:
        filters = set(ctx.settings.panel.filter_tables)
        scope.row_dropdowns = [
            v.folder for v in main.visuals
            if v.vtype == "slicer" and filters & set(slicer_selector_tables(v, ctx.settings))
        ]
    return scope


def _answer_bookmarks(ctx: RuleContext) -> list[Bookmark]:
    prefixes = ctx.settings.answer_bookmarks.prefixes
    return [b for b in ctx.bookmarks if b.display_name.startswith(prefixes)]


def _fields(picks: list[tuple[str, str]]) -> list[str]:
    return [f for _, f in picks]


def _container_picks(bookmark: Bookmark, container_id: str | None) -> list[tuple[str, str]]:
    if not container_id:
        return []
    return selections(bookmark.containers().get(container_id))


def _properties(items: Any, kind: str) -> list[Any]:
    return [dig(item, kind, "Property") for item in items or []]


# -- the checks -------------------------------------------------------------------
def check_answer_bookmarks(ctx: RuleContext) -> None:
    cfg = ctx.settings.answer_bookmarks
    if not cfg.prefixes:
        raise RuleError(
            "the answer-bookmarks rule needs [answer_bookmarks] prefixes in the "
            "config file (the display-name prefixes of the answer bookmarks)"
        )
    scope = _resolve_scope(ctx)
    _check_page_wells(ctx, scope)
    answers = _answer_bookmarks(ctx)
    ctx.checked["answer-bookmarks"] = len(answers)
    if not answers:
        ctx.add("ABK000", ctx.report_dir / "definition" / "bookmarks", "prefixes",
                f"no bookmark display name starts with any of "
                f"{', '.join(repr(p) for p in cfg.prefixes)}; the suite would "
                f"pass without checking anything")
        return
    submenu_children = _submenu_children(ctx)
    for bookmark in answers:
        _check_bookmark(ctx, scope, bookmark, submenu_children)


def _submenu_children(ctx: RuleContext) -> set[str]:
    prefix = ctx.settings.answer_bookmarks.submenu_prefix
    index = read_json(ctx.report_dir / "definition" / "bookmarks" / "bookmarks.json")
    children: set[str] = set()
    for item in dig(index, "items") or []:
        name = item.get("displayName") if isinstance(item, dict) else None
        if isinstance(name, str) and name.startswith(prefix):
            children.update(c for c in item.get("children") or [] if isinstance(c, str))
    return children


def _check_bookmark(ctx: RuleContext, scope: _Scope, bm: Bookmark, submenu: set[str]) -> None:
    dn, path = bm.display_name, bm.path
    cfg = ctx.settings.answer_bookmarks
    options = bm.data.get("options")
    targets = options.get("targetVisualNames", None) if isinstance(options, dict) else None
    if not isinstance(options, dict) or "targetVisualNames" not in options:
        ctx.add("ABK001", path, dn, f"{dn!r}: options.targetVisualNames is missing, "
                "so the menu entry cannot be clicked; it must be []")
    elif targets != []:
        ctx.add("ABK001", path, dn, f"{dn!r}: options.targetVisualNames is "
                f"{targets!r}, which scopes the bookmark to those visuals; it must be []")

    section = bm.active_section
    containers = bm.containers()

    # T7: the analysis category is pinned
    column = ctx.settings.category.column
    category_filters = [
        f for f in dig(section, "filters", "byExpr") or []
        if dig(f, "expression", "Column", "Property") == column
    ]
    if not any("Literal" in json.dumps(f) for f in category_filters):
        ctx.add("ABK007", path, dn, f"{dn!r} does not pin [{column}] to a value")

    # T8: registered under a submenu
    if bm.name not in submenu:
        ctx.add("ABK008", path, dn, f"{dn!r} is not a child of any "
                f"{cfg.submenu_prefix!r} group in bookmarks.json, so no menu entry renders")

    # T6: every captured picker selects something
    for picker in scope.picker_ids():
        if picker in containers and not _container_picks(bm, picker):
            ctx.add("ABK006", path, f"{dn} / {picker}",
                    f"{dn!r}: picker {picker!r} is captured with no selection")

    # T10: row dimensions mirrored into the dropdown filters
    rows = _fields(_container_picks(bm, scope.row_slicer))
    if rows:
        have: list[str] = []
        for dropdown in scope.row_dropdowns:
            have += [f for f in _fields(_container_picks(bm, dropdown)) if f not in have]
        missing = [r for r in rows if r not in have]
        if missing:
            ctx.add("ABK010", path, dn, f"{dn!r}: row field(s) {missing} have no dropdown "
                    f"filter (the dropdowns hold {have})")

    # T3: the matrix is captured and visible
    matrix = containers.get(scope.matrix_id)
    if not isinstance(matrix, dict):
        ctx.add("ABK003", path, dn, f"{dn!r} does not capture the matrix "
                f"{scope.matrix_id!r}, which stays hidden")
        return
    single = matrix.get("singleVisual") if isinstance(matrix.get("singleVisual"), dict) else {}
    if dig(single, "display", "mode") == "hidden":
        ctx.add("ABK003", path, dn, f"{dn!r} captures the matrix as hidden")

    # T4: rows are this bookmark's own, nothing inherited
    got = _properties(dig(single, "projections", "Rows"), "Column")
    if rows and got != rows:
        ctx.add("ABK004", path, dn, f"{dn!r}: matrix rows are {got}, but the row "
                f"picker selects {rows}")
    captured = json.dumps([single.get(k) for k in ("projections", "activeProjections",
                                                    "prototypeQuery")], ensure_ascii=False)
    for token in cfg.inherited_fingerprints:
        if token in captured:
            ctx.add("ABK004", path, f"{dn} / inherited {token}",
                    f"{dn!r}: the matrix capture carries inherited field {token!r}")

    # T5: capture shape
    if "Values" in (single.get("activeProjections") or {}):
        ctx.add("ABK005", path, f"{dn} / activeProjections",
                f"{dn!r}: activeProjections holds Values")
    if single.get("expansionStates"):
        ctx.add("ABK005", path, f"{dn} / expansionStates",
                f"{dn!r}: the matrix capture keeps expansionStates")

    # T9: slot map
    roles = ("Values",) if cfg.slot_mode == "values-only" else ("Rows", "Values")
    for role in roles:
        _check_slots(ctx, scope, bm, single, role, strict=cfg.slot_mode != "values-only")


def _check_slots(ctx: RuleContext, scope: _Scope, bm: Bookmark, single: dict, role: str,
                 *, strict: bool) -> None:
    dn, path = bm.display_name, bm.path
    declared = scope.declared(role)
    slots = dig(single, "parameters", role)
    if slots is None and strict:
        ctx.add("ABK009", path, f"{dn} / {role}", f"{dn!r}: no {role} slot map")
        return
    slots = slots if isinstance(slots, list) else []
    entities = [dig(s, "expr", "Column", "Expression", "SourceRef", "Entity") for s in slots]
    if entities != declared:
        ctx.add("ABK009", path, f"{dn} / {role}",
                f"{dn!r}: {role} slot map names {entities}, the page declares {declared}")
        return
    offset, concat, flagged = 0, [], False
    for param, slot in zip(declared, slots):
        slicer = scope.slicer_for.get(param)
        if slicer is None and strict:
            ctx.add("ABK009", path, f"{dn} / {role}:{param}",
                    f"{dn!r}: no known slicer for parameter {param!r}")
            return
        picks = _fields(_container_picks(bm, slicer))
        if slot.get("index") != offset or slot.get("length") != len(picks):
            flagged = True
            ctx.add("ABK009", path, f"{dn} / {role}:{param}",
                    f"{dn!r}: {param!r} owns slots ({slot.get('index')}, "
                    f"{slot.get('length')}) but its {len(picks)} pick(s) start at {offset}")
        concat += picks
        offset += len(picks)
    if flagged and strict:
        return
    kind = "Column" if role == "Rows" else "Measure"
    got = _properties(dig(single, "projections", role), kind)
    if concat and got != concat:
        ctx.add("ABK009", path, f"{dn} / {role} projections",
                f"{dn!r}: {role} projections are {got}, the picks are {concat}")


def _check_page_wells(ctx: RuleContext, scope: _Scope) -> None:
    slot_table = ctx.settings.placeholders.template_slot_table
    stems = {b.path.name[: -len(".bookmark.json")] for b in ctx.bookmarks}
    for visual in scope.main.visuals:
        for role, block in visual.query_state.items():
            if not isinstance(block, dict) or not block.get("fieldParameters"):
                continue
            raw = [
                dig(p, "field", "Measure", "Property")
                for p in block.get("projections") or []
                if isinstance(dig(p, "field", "Measure"), dict)
                and dig(p, "field", "Measure", "Expression", "SourceRef", "Entity") != slot_table
            ]
            if raw:
                ctx.add("PGW001", visual.path, f"{visual.folder}/{role}",
                        f"{visual.folder}/{role} projects raw measure(s) {raw} beside its "
                        f"field parameters; they render in every bookmark")
        if visual.vtype == "bookmarkNavigator":
            text = json.dumps(dig(visual.data, "visual", "objects"))
            match = re.search(r"selectedBookmark.*?[\"']([0-9a-fA-F]{20})[\"']", text)
            if match and match.group(1) not in stems:
                ctx.add("PGW002", visual.path, visual.folder,
                        f"navigator {visual.folder!r} selects bookmark "
                        f"{match.group(1)!r}, which has no file")


# -- picker literals ----------------------------------------------------------------
def _registry(ctx: RuleContext) -> dict[str, set[str]]:
    """selector table -> normalized ``'table'[field]`` rows it offers."""
    model = ctx.model
    registry: dict[str, set[str]] = {}
    for table in model.raw_by_table:
        if not ctx.settings.is_selector_table(table):
            continue
        rows: set[str] = set()
        for ref in model.nameof_refs(table):
            if not ref.in_tuple:
                continue
            home = ref.qualifier or model.home_table(ref.name)
            if home:
                rows.add(f"'{home}'[{ref.name}]")
        registry[table] = rows
    return registry


def _picker_slicers(ctx: RuleContext) -> dict[str, str]:
    pickers: dict[str, str] = {}
    for visual in ctx.index.visuals():
        if visual.vtype != "slicer":
            continue
        tables = {e for e in visual.query_entities() if ctx.settings.is_selector_table(e)}
        if len(tables) == 1:
            pickers[visual.folder] = next(iter(tables))
    return pickers


def check_bookmark_literals(ctx: RuleContext) -> None:
    if ctx.model is None:
        ctx.missing_model("bookmark-literals")
        return
    registry = _registry(ctx)
    pickers = _picker_slicers(ctx)
    only = ctx.options.get("only_display_names")
    checked = 0
    for bm in ctx.bookmarks:
        if only is not None and bm.display_name not in only:
            continue
        for cid, container in bm.containers().items():
            text = json.dumps(container, ensure_ascii=False)
            found = sorted({f"'{t}'[{f}]" for t, f in SELECTION_IN_TEXT.findall(text)})
            for lit in found:
                checked += 1
                table = pickers.get(cid)
                anywhere = [t for t, rows in registry.items() if lit in rows]
                subject = f"{bm.display_name} / {cid} / {lit}"
                if table is not None:
                    if lit in registry.get(table, set()):
                        continue
                    if anywhere:
                        ctx.add("BML001", bm.path, subject,
                                f"{lit} is registered in {', '.join(anywhere)} but not in "
                                f"{table}, the field parameter behind picker {cid!r}")
                    else:
                        ctx.add("BML002", bm.path, subject,
                                f"{lit} (picker {cid!r}) is not registered in any field "
                                f"parameter")
                elif not anywhere:
                    ctx.add("BML002", bm.path, subject,
                            f"{lit} (container {cid!r}) is not registered in any field "
                            f"parameter")
    ctx.checked["bookmark-literals"] = checked


def load_display_name_filter(path: Path) -> set[str]:
    data = load_json(path)
    if not isinstance(data, list) or not all(isinstance(x, str) for x in data):
        raise ValueError(f"{path} must hold a JSON list of bookmark display names")
    return set(data)
