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
    Bookmark,
    Page,
    Visual,
    dig,
    read_json,
    selection_literals,
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
    #: parameter table -> the main-page slicers that could be its slicer,
    #: kept when discovery found none or several.
    candidates: dict[str, list[str]] = dc_field(default_factory=dict)
    row_param: str | None = None
    row_dropdowns: list[str] = dc_field(default_factory=list)
    #: main-page slicers whose query references exactly one selector table.
    selector_slicers: list[str] = dc_field(default_factory=list)

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
        """Every picker whose capture must select something.

        The main-page selector slicers, the row dropdowns and every slicer
        known for a parameter (configured or discovered).
        """
        ids = {sid for sid in self.slicer_for.values() if sid}
        ids.update(self.selector_slicers)
        ids.update(self.row_dropdowns)
        return sorted(ids)


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
            and {e for e in v.query_entities() if _is_selector(ctx, e)} == {table}
        ]
        scope.slicer_for[table] = matches[0] if len(matches) == 1 else None
        if len(matches) != 1:
            scope.candidates[table] = matches
    scope.selector_slicers = [
        v.folder for v in main.visuals
        if v.vtype == "slicer"
        and len({e for e in v.query_entities() if _is_selector(ctx, e)}) == 1
    ]
    rows = scope.declared("Rows")
    scope.row_param = rows[0] if rows else None
    if cfg.row_dropdowns is not None:
        scope.row_dropdowns = list(cfg.row_dropdowns)
    else:
        filters = set(ctx.settings.panel.filter_tables)
        scope.row_dropdowns = [
            v.folder for v in main.visuals
            if v.vtype == "slicer" and filters & set(
                    slicer_selector_tables(v, ctx.settings, ctx.field_parameters()))
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
    if scope.row_param and scope.row_slicer is None:
        found = scope.candidates.get(scope.row_param, [])
        which = (f"several slicers could be it ({', '.join(found)})" if found
                 else "no main-page slicer references only that table")
        raise RuleError(
            f"{ctx.label}: cannot tell which slicer picks the matrix rows "
            f"({scope.row_param!r}): {which}; set it in [answer_bookmarks] slicers "
            f"(\"{scope.row_param}\" = \"<slicer visual id>\")"
        )
    if not scope.row_param:
        ctx.skip("answer-bookmarks: the matrix declares no row parameter, so ABK004 "
                 "(rows are the bookmark's own) and ABK010 (rows in the dropdowns) "
                 "were not run")
    report_unreadable(ctx, [scope.main.path / "visuals"])
    answers = _answer_bookmarks(ctx)
    ctx.checked["answer-bookmarks"] = len(answers)
    ctx.details["answer-bookmarks"] = {"answer bookmarks": len(answers)}
    if not answers:
        ctx.add("ABK000", ctx.report_dir / "definition" / "bookmarks", "prefixes",
                f"no whole-page category bookmarks matched [answer_bookmarks] prefixes, so "
                f"every check passed on an empty set. Either the naming convention changed "
                f"or the report moved. Prefixes currently expected: {list(cfg.prefixes)!r}")
    else:
        submenu_children = _submenu_children(ctx)
        for bookmark in answers:
            _check_bookmark(ctx, scope, bookmark, submenu_children)
    # page-level findings come after every bookmark's
    _check_page_wells(ctx, scope)


def report_unreadable(ctx: RuleContext, visual_dirs: list[Path] = ()) -> None:
    """``JSN001`` for every bookmark file, and visual under ``visual_dirs``, that does not parse.

    The rules read only what parses; an unreadable file must still fail the
    run instead of being passed over.
    """
    files = sorted((ctx.report_dir / "definition" / "bookmarks").glob("*.json"))
    for folder in visual_dirs:
        files += sorted(Path(folder).glob("*/visual.json"))
    for path in files:
        try:
            load_json(path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            ctx.add("JSN001", path, path.name, f"not valid JSON: {exc}")


def _submenu_children(ctx: RuleContext) -> set[str]:
    prefix = ctx.settings.answer_bookmarks.submenu_prefix
    index = read_json(ctx.report_dir / "definition" / "bookmarks" / "bookmarks.json")
    children: set[str] = set()
    for item in dig(index, "items") or []:
        name = item.get("displayName") if isinstance(item, dict) else None
        if isinstance(name, str) and name.startswith(prefix):
            children.update(c for c in item.get("children") or [] if isinstance(c, str))
    return children


def _family(parameter: str | None) -> str:
    """``y-Selector`` for ``y-Selector 2``: the parameter name without its number."""
    return re.sub(r"\s*\d+$", "", parameter or "") or "y-Selector"


def _dropdown_span(ctx: RuleContext, scope: _Scope) -> str:
    """The row dropdowns' parameters as ``y-Selector 3/4/5/6``."""
    visuals = {v.folder: v for v in scope.main.visuals}
    names = []
    for vid in scope.row_dropdowns:
        visual = visuals.get(vid)
        tables = (slicer_selector_tables(visual, ctx.settings,
                                         ctx.field_parameters())
                 if visual else [])
        names.append(tables[0] if tables else vid)
    if not names:
        return "the row dropdowns"
    names = sorted(names)
    tails = []
    for name in names[1:]:
        match = re.search(r"(\d+)$", name)
        tails.append(match.group(1) if match else name)
    return "/".join([names[0], *tails])


def _picker_label(ctx: RuleContext, vid: str) -> str:
    """The ``[bookmarks] pickers`` key of a slicer, or its visual id."""
    return (ctx.options.get("picker_labels") or {}).get(vid, vid)


def _check_bookmark(ctx: RuleContext, scope: _Scope, bm: Bookmark, submenu: set[str]) -> None:
    """One answer bookmark, in the order T1, T3, T4, T9, T4 inherited, T5, T6, T10, T7, T8."""
    dn, path = bm.display_name, bm.path
    cfg = ctx.settings.answer_bookmarks
    options = bm.data.get("options")
    has_key = isinstance(options, dict) and "targetVisualNames" in options
    targets = options.get("targetVisualNames") if has_key else None
    if not has_key or targets != []:
        ctx.add("ABK001", path, dn,
                f"{dn}: not all-visuals targeting ({json.dumps(targets, ensure_ascii=False)})")

    section = bm.active_section
    containers = bm.containers()
    rows = _fields(_container_picks(bm, scope.row_slicer))

    # T3: the matrix is captured and visible
    matrix = containers.get(scope.matrix_id)
    single = None
    if not isinstance(matrix, dict):
        ctx.add("ABK003", path, dn, f"{dn}: Main Matrix not captured (cannot be made visible)")
    else:
        single = matrix.get("singleVisual") if isinstance(matrix.get("singleVisual"), dict) else {}
        if dig(single, "display", "mode") == "hidden":
            ctx.add("ABK003", path, dn, f"{dn}: Main Matrix captured as hidden")
    if single is not None:
        # T4: rows are this bookmark's own
        got = _properties(dig(single, "projections", "Rows"), "Column")
        if rows and got != rows:
            ctx.add("ABK004", path, dn, f"{dn}: matrix Rows {got} != "
                    f"{_family(scope.row_param)} selection {rows}")
        # T9: slot map
        roles = ("Values",) if cfg.slot_mode == "values-only" else ("Rows", "Values")
        for role in roles:
            _check_slots(ctx, scope, bm, single, role, strict=cfg.slot_mode != "values-only")
        # T4: nothing inherited
        captured = json.dumps([single.get(k) for k in ("projections", "activeProjections",
                                                        "prototypeQuery")], ensure_ascii=False)
        for token in cfg.inherited_fingerprints:
            if token in captured:
                ctx.add("ABK004", path, f"{dn} / inherited {token}",
                        f"{dn}: matrix still carries inherited field {token}")
        # T5: capture shape
        if "Values" in (single.get("activeProjections") or {}):
            ctx.add("ABK005", path, f"{dn} / activeProjections",
                    f"{dn}: activeProjections must carry Rows only")
        if single.get("expansionStates"):
            ctx.add("ABK005", path, f"{dn} / expansionStates",
                    f"{dn}: stale matrix expansionStates present")

    # T6: every captured picker selects something
    for picker in scope.picker_ids():
        if picker in containers and not _container_picks(bm, picker):
            ctx.add("ABK006", path, f"{dn} / {picker}",
                    f"{dn}: picker {_picker_label(ctx, picker)} captured with no selection")

    # T10: row dimensions mirrored into the dropdown filters
    if rows:
        have: list[str] = []
        for dropdown in scope.row_dropdowns:
            have += [f for f in _fields(_container_picks(bm, dropdown)) if f not in have]
        missing = [r for r in rows if r not in have]
        if missing:
            found = sorted(have) if have else "nothing"
            ctx.add("ABK010", path, dn,
                    f"{dn}: row dimension(s) {missing} have no dropdown filter — set them in "
                    f"{_dropdown_span(ctx, scope)} (found there: {found})")

    # T7: the analysis category is pinned
    column = ctx.settings.category.column
    category_filters = [
        f for f in dig(section, "filters", "byExpr") or []
        if dig(f, "expression", "Column", "Property") == column
    ]
    if not any("Literal" in json.dumps(f) for f in category_filters):
        ctx.add("ABK007", path, dn, f"{dn}: no {column} pinned")

    # T8: registered under a submenu
    if bm.name not in submenu:
        ctx.add("ABK008", path, dn, f"{dn}: not registered under any {cfg.submenu_prefix} "
                f"group — unreachable in the UI")


def _check_slots(ctx: RuleContext, scope: _Scope, bm: Bookmark, single: dict, role: str,
                 *, strict: bool) -> None:
    dn, path = bm.display_name, bm.path
    declared = scope.declared(role)
    slots = dig(single, "parameters", role)
    if not slots and strict:
        ctx.add("ABK009", path, f"{dn} / {role}",
                f"{dn}: matrix has no parameters slot map for {role} — Power BI cannot "
                f"attribute a projection to a parameter")
        return
    slots = slots if isinstance(slots, list) else []
    entities = [dig(s, "expr", "Column", "Expression", "SourceRef", "Entity") for s in slots]
    if entities != declared:
        ctx.add("ABK009", path, f"{dn} / {role}",
                f"{dn}: {role} slot map covers {entities} but the page well declares {declared}")
        return
    offset, concat, flagged = 0, [], False
    for param, slot in zip(declared, slots):
        slicer = scope.slicer_for.get(param)
        if slicer is None:
            ctx.add("ABK009", path, f"{dn} / {role}:{param}",
                    f"{dn}: {role} declares {param!r} but [answer_bookmarks] slicers has no "
                    f"slicer for it — cannot verify its slots")
            return
        picks = _fields(_container_picks(bm, slicer))
        index, length = slot.get("index"), slot.get("length")
        if index != offset or length != len(picks):
            flagged = True
            start = length if isinstance(length, int) and length >= 0 else 0
            outside = picks[start:] or picks
            ctx.add("ABK009", path, f"{dn} / {role}:{param}",
                    f"{dn}: {role} slot for {param} is (index {index}, length {length}) but "
                    f"its slicer selects {len(picks)} field(s) at offset {offset} — the picks "
                    f"outside the slot render nothing: {outside}")
        concat += picks
        offset += len(picks)
    if flagged and strict:
        return
    kind = "Column" if role == "Rows" else "Measure"
    got = _properties(dig(single, "projections", role), kind)
    if concat and got != concat:
        ctx.add("ABK009", path, f"{dn} / {role} projections",
                f"{dn}: matrix {role} {got} != the concatenated parameter selections {concat}")


def _check_page_wells(ctx: RuleContext, scope: _Scope) -> None:
    slot_table = ctx.settings.placeholders.template_slot_table
    # the bookmark files on disk, parsed or not
    stems = {p.name[: -len(".bookmark.json")]
             for p in (ctx.report_dir / "definition" / "bookmarks").glob("*.bookmark.json")}
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
                        f"{visual.folder}/{role}: raw measure projections beside "
                        f"fieldParameters — renders in EVERY bookmark: {raw}")
    for visual in scope.main.visuals:  # navigators after every well
        if visual.vtype == "bookmarkNavigator":
            text = json.dumps(dig(visual.data, "visual", "objects"))
            match = re.search(r"selectedBookmark.*?'([0-9a-f]{20})'", text)
            if match and match.group(1) not in stems:
                ctx.add("PGW002", visual.path, visual.folder,
                        f"{visual.folder}: navigator selectedBookmark {match.group(1)} "
                        f"does not exist")


# -- picker literals ----------------------------------------------------------------
def _is_selector(ctx: RuleContext, entity: str) -> bool:
    """Is this table one of the model's field parameters?

    The model's own field parameters are detected from its TMDL; the name
    patterns are the fallback when the model could not be read.
    """
    detected = ctx.field_parameters()
    if detected:
        return entity in detected
    return ctx.settings.is_selector_table(entity)


def _registry(ctx: RuleContext) -> dict[str, set[str]]:
    """selector table -> normalized ``'table'[field]`` rows it offers.

    A selector table is one of the model's field parameters (detected from
    its TMDL); the name patterns are the fallback when the model could not
    be read.
    """
    model = ctx.model
    registry: dict[str, set[str]] = {}
    detected = ctx.field_parameters()
    for table in model.raw_by_table:
        if detected:
            if table not in detected:
                continue
        elif not ctx.settings.is_selector_table(table):
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
        tables = {e for e in visual.query_entities() if _is_selector(ctx, e)}
        if len(tables) == 1:
            pickers[visual.folder] = next(iter(tables))
    return pickers


_ELSEWHERE = ("registered elsewhere but NOT in {table!r}: this slicer resolves it to BLANK, "
              "so helpers that parse the selected field name ERROR out. Register the row "
              "in {table}.tmdl or pick the field in a parameter that has it")
_NOWHERE = "not registered in ANY field parameter"


def check_bookmark_literals(ctx: RuleContext) -> None:
    if ctx.model is None:
        ctx.missing_model("bookmark-literals")
        return
    report_unreadable(ctx)
    registry = _registry(ctx)
    pickers = _picker_slicers(ctx)
    only = ctx.options.get("only_display_names")
    checked = scanned = resolved = unresolved = 0
    found_problems: dict[tuple[str, str, str], tuple[str, Path]] = {}
    for bm in ctx.bookmarks:
        if only is not None and bm.display_name not in only:
            continue
        scanned += 1
        for cid, container in bm.containers().items():
            found = sorted({f"'{t}'[{f}]" for t, f in selection_literals(container)})
            for lit in found:
                checked += 1
                table = pickers.get(cid)
                anywhere = [t for t, rows in registry.items() if lit in rows]
                if table is not None:
                    if lit in registry.get(table, set()):
                        resolved += 1
                        continue
                    if anywhere:
                        problem = ("BML001", _ELSEWHERE.format(table=table))
                    else:
                        problem = ("BML002", _NOWHERE)
                elif not anywhere:
                    problem = ("BML002", _NOWHERE)
                else:
                    resolved += 1
                    continue
                unresolved += 1
                found_problems.setdefault((bm.display_name, lit, problem[1]),
                                          (problem[0], bm.path))
    # one finding per (bookmark, literal, reason), sorted by that triple
    for (display, lit, reason), (check_id, path) in sorted(found_problems.items()):
        ctx.add(check_id, path, f"{display} / {lit}",
                f"{display}  ->  {lit}\n{' ' * 16}{reason}")
    ctx.checked["bookmark-literals"] = checked
    ctx.details["bookmark-literals"] = {"bookmarks checked": scanned,
                                        "literals OK": resolved,
                                        "UNREGISTERED": unresolved}


def load_display_name_filter(path: Path) -> set[str]:
    """Display names from a JSON list of names, or of entries with a ``displayName``.

    The second form is the ``bookmarks build`` entries file.
    """
    data = load_json(path)
    if isinstance(data, list):
        if all(isinstance(x, str) for x in data):
            return set(data)
        if all(isinstance(x, dict) and isinstance(x.get("displayName"), str) for x in data):
            return {x["displayName"] for x in data}
    raise ValueError(f"{path} must hold a JSON list of bookmark display names, or a "
                     f"list of entries that each have a displayName")
