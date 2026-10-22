"""``bookmarks build``: answer bookmarks rendered from a working base bookmark.

A page bookmark is a full capture of the page's exploration state; a
hand-written one easily misses a piece Power BI needs. The builder starts
from a bookmark that already behaves in the same report and changes only
what an entry asks for: slicer picks, the matrix and chart captures, which
visuals show, the analysis-category filter, the date filter and the drill
level. Every entry is built in memory first; one invalid entry writes
nothing.

Builder settings come from the ``[bookmarks]`` section of plotstyler.toml::

    [bookmarks]
    base = "<bookmark name>"
    matrix = "<visual id>"
    chart = "<visual id>"
    row_picker = "<picker key>"
    row_dropdowns = ["<picker key>", ...]
    category_column = "Analysis Category"
    calendar_table = "__Calendar"
    calendar_hierarchy = "Calendar Hierarchy"
    pickers = {<key> = "<slicer visual id>", ...}
    wells = {matrix_rows = [...], matrix_values = [...], chart_y = [...],
             chart_y2 = [...], chart_series = [...]}
"""
from __future__ import annotations

import copy
import json
import re
import secrets
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import qx
from .canvas import dig, first_in_condition, read_json, slicer_filter
from .textio import Layout, dump_json, load_json, load_toml

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on Python 3.10
    import tomli as tomllib


class BuildError(ValueError):
    """An entry or the builder settings are invalid; nothing was written."""


_WELL_KEYS = ("matrix_rows", "matrix_values", "chart_y", "chart_y2", "chart_series")


@dataclass(frozen=True)
class BuilderSettings:
    base: str | None = None
    matrix: str | None = None
    chart: str | None = None
    row_picker: str | None = None
    row_dropdowns: tuple[str, ...] = ()
    category_column: str = "Analysis Category"
    calendar_table: str = "__Calendar"
    calendar_hierarchy: str = "Calendar Hierarchy"
    pickers: dict[str, str] = field(default_factory=dict)
    wells: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: Legacy layout: the picker whose picks fill the matrix Values well.
    legacy_measures: str = "x_selector_1"

    def well(self, key: str) -> tuple[str, ...]:
        return self.wells.get(key, ())

    @property
    def values_slicers(self) -> dict[str, str]:
        """values-slicer key -> the key of the dimension picker it lists.

        ``y_values_slicer_<N>`` lists the values of the dimension chosen in
        ``y_selector_<N>`` (N = 2..6; axis 1 has none). Only keys present in
        ``pickers`` count.
        """
        return {f"y_values_slicer_{n}": f"y_selector_{n}" for n in range(2, 7)
                if f"y_values_slicer_{n}" in self.pickers}

    @property
    def picker_keys(self) -> tuple[str, ...]:
        """The keys of ``pickers`` that are real pickers (not values slicers)."""
        skip = self.values_slicers
        return tuple(k for k in self.pickers if k not in skip)


def load_builder_settings(path: Path | None) -> BuilderSettings:
    if path is None or not Path(path).is_file():
        return BuilderSettings()
    try:
        raw = load_toml(Path(path))
    except tomllib.TOMLDecodeError as exc:
        raise BuildError(f"{path} is not valid TOML: {exc}") from exc
    body = raw.get("bookmarks") or {}
    known = {f for f in BuilderSettings.__dataclass_fields__}
    unknown = set(body) - known
    if unknown:
        raise BuildError(f"{path} has unknown key(s) under [bookmarks]: "
                         f"{', '.join(sorted(unknown))}")
    values = dict(body)
    if "row_dropdowns" in values:
        values["row_dropdowns"] = tuple(values["row_dropdowns"])
    if "pickers" in values:
        values["pickers"] = dict(values["pickers"])
    if "wells" in values:
        unknown_wells = set(values["wells"]) - set(_WELL_KEYS)
        if unknown_wells:
            raise BuildError(f"[bookmarks] wells has unknown key(s) {sorted(unknown_wells)}; "
                             f"valid keys: {', '.join(_WELL_KEYS)}")
        values["wells"] = {k: tuple(v) for k, v in values["wells"].items()}
    return BuilderSettings(**values)


# -- small builders -----------------------------------------------------------------
def _ref(kind: str, table: str, column: str) -> dict:
    return qx.field_ref(kind, column, table)


def _pick_literal(pick: dict) -> str:
    """The saved selection of a field-parameter row, both quoting levels escaped.

    Same spelling as :func:`~pbi_plot_styler.rename.literal_name`: an
    apostrophe is written four times and a closing bracket twice.
    """
    from .rename import literal_name

    table = pick["table"].replace("'", "'" * 4)
    return "'''" + table + "''[" + literal_name(pick["column"]) + "]'"


def _as_list(value: Any) -> list:
    """One string as a one-item list; any other value as a list (None: [])."""
    return [value] if isinstance(value, str) else list(value or [])


def _absent(value: Any) -> bool:
    """``None``, an empty string or an empty list: the entry does not set it."""
    return value is None or value == "" or value == []


def _pick_key(pick: dict) -> tuple[str, str]:
    return pick["table"], pick["column"]


def _validate_pick(pick: Any, where: str) -> dict:
    if not isinstance(pick, dict) or not isinstance(pick.get("table"), str) \
            or not isinstance(pick.get("column"), str):
        raise BuildError(f"{where}: each pick needs a 'table' and a 'column'")
    return {"label": pick["column"], **pick}


_DIRECTIONS = {"ascending": 1, "asc": 1, "descending": 2, "desc": 2}


def _direction(display: str, value: Any) -> int:
    """A sort direction as Power BI stores it (1 ascending, 2 descending)."""
    if isinstance(value, bool):
        raise BuildError(f"{display!r}: matrix_sort direction {value!r} is not 1 or 2")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in _DIRECTIONS:
            return _DIRECTIONS[text]
        if text.lstrip("-").isdigit():
            return int(text)
    raise BuildError(f"{display!r}: matrix_sort direction {value!r} is not 1 or 2")


def _sort_target(display: str, sort: Any) -> tuple[int, dict]:
    """``(direction, expression)`` of a ``matrix_sort`` value.

    Two spellings: ``{measure: {table, column}}`` / ``{column: {...}}`` with
    an optional ``direction``, or the flat ``{table, column, direction,
    kind}`` where ``kind`` is ``measure`` (the default) or ``column``.
    """
    if not isinstance(sort, dict):
        raise BuildError(f"{display!r}: matrix_sort must be an object")
    direction = _direction(display, sort.get("direction", 2))
    if "measure" in sort or "column" in sort and isinstance(sort.get("column"), dict):
        kind = "Measure" if "measure" in sort else "Column"
        target = sort.get(kind.lower())
        if not isinstance(target, dict) or not isinstance(target.get("table"), str) \
                or not isinstance(target.get("column"), str):
            raise BuildError(f"{display!r}: matrix_sort needs a 'measure' or 'column' "
                             f"with a table and a column")
        return direction, _ref(kind, target["table"], target["column"])
    if isinstance(sort.get("table"), str) and isinstance(sort.get("column"), str):
        kind = str(sort.get("kind") or "measure").strip().lower()
        if kind not in ("measure", "column"):
            raise BuildError(f"{display!r}: matrix_sort kind {kind!r} is not measure or column")
        return direction, _ref(kind.capitalize(), sort["table"], sort["column"])
    raise BuildError(f"{display!r}: matrix_sort needs a 'measure' or 'column'")


@dataclass
class _Built:
    name: str
    display: str
    data: dict
    group: str | None
    rerendered: bool
    notes: list[str] = field(default_factory=list)


class Builder:
    def __init__(self, report: Path, settings: BuilderSettings, *, base: str | None,
                 group: str | None, keep_ids: bool, legacy: bool) -> None:
        self.report = report
        self.settings = settings
        self.dir = report / "definition" / "bookmarks"
        self.group = group
        self.keep_ids = keep_ids
        self.legacy = legacy
        self.index = read_json(self.dir / "bookmarks.json")
        self.existing: dict[str, tuple[Path, dict]] = {}
        for path in sorted(self.dir.glob("*.bookmark.json")):
            data = read_json(path)
            if isinstance(data, dict):
                self.existing[path.name[: -len(".bookmark.json")]] = (path, data)
        self.base_id = base or settings.base
        self.base = self._find(self.base_id) if self.base_id else None
        if self.base_id and self.base is None:
            if base:
                raise BuildError(f"base bookmark {self.base_id} not found in {self.dir}")
            raise BuildError(f"no base bookmark {self.base_id} in {self.dir}")
        self.groups = {
            item.get("name"): item for item in dig(self.index, "items") or []
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        self.taken = set(self.existing) | {d.get("name") for _, d in self.existing.values()}

    def _find(self, bookmark_id: str) -> dict | None:
        if bookmark_id in self.existing:
            return self.existing[bookmark_id][1]
        for _, data in self.existing.values():
            if data.get("name") == bookmark_id:
                return data
        return None

    def _by_display(self, display: str) -> dict | None:
        found = [(path, d) for path, d in self.existing.values() if d.get("displayName") == display]
        if len(found) > 1:
            names = ", ".join(sorted(str(d.get("name") or path.name) for path, d in found))
            raise BuildError(f"{display!r}: several existing bookmarks share this display "
                             f"name ({names}); rename or delete all but one to re-render it")
        return found[0][1] if found else None

    def _fresh_name(self) -> str:
        while True:
            name = secrets.token_hex(10)
            if name not in self.taken:
                self.taken.add(name)
                return name

    def _page_visuals(self, section_id: Any) -> set[str] | None:
        """Ids of the visuals saved on page ``section_id`` (``None``: unknown page)."""
        if not isinstance(section_id, str):
            return None
        folder = self.report / "definition" / "pages" / section_id / "visuals"
        if not folder.is_dir():
            return None
        ids = set()
        for child in folder.iterdir():
            if (child / "visual.json").is_file():
                ids.add(child.name)
                name = dig(read_json(child / "visual.json"), "name")
                if isinstance(name, str):
                    ids.add(name)
        return ids

    # -- one entry ----------------------------------------------------------------
    def build(self, entry: Any) -> _Built:
        if not isinstance(entry, dict) or not isinstance(entry.get("displayName"), str) \
                or not entry["displayName"]:
            raise BuildError(f"every entry needs a displayName: {entry!r}")
        display = entry["displayName"]
        notes: list[str] = []
        pickers = entry.get("pickers") or {}
        if not isinstance(pickers, dict):
            raise BuildError(f"{display!r}: 'pickers' must map picker keys to lists of picks")
        for key in pickers:
            if key in self.settings.values_slicers:
                raise BuildError(f"{display!r}: {key!r} is a values slicer, not a picker; "
                                 f"pick the dimension in {self.settings.values_slicers[key]!r}")
            if key not in self.settings.pickers:
                raise BuildError(f"{display!r}: picker {key!r} is not in [bookmarks] pickers")
        picks = {
            key: [_validate_pick(p, f"{display!r} picker {key!r}") for p in value or []]
            for key, value in pickers.items()
        }
        group = entry.get("group") or self.group
        if group is not None and group not in self.groups:
            raise BuildError(f"bookmark group {group} not found")

        existing = self._by_display(display) if self.keep_ids else None
        rerendered = existing is not None
        if rerendered:
            source = existing
        elif entry.get("base"):
            source = self._find(entry["base"])
            if source is None:
                raise BuildError(f"base bookmark {entry['base']} not found in {self.dir}")
        elif self.base is not None:
            source = self.base
        else:
            raise BuildError(f"{display!r}: no base bookmark: pass --base, set [bookmarks] "
                             f"base or give the entry a 'base'")
        data = copy.deepcopy(source)
        name = data.get("name") if rerendered else self._fresh_name()
        data["displayName"] = display
        data["name"] = name
        options = data.get("options") if isinstance(data.get("options"), dict) else {}
        targets = list(entry.get("target_visuals") or [])
        if not targets and self.legacy and self.settings.matrix:
            targets = [self.settings.matrix]
        options["targetVisualNames"] = targets
        data["options"] = options

        state = data.get("explorationState")
        section_id = dig(state, "activeSection")
        section = dig(state, "sections", section_id)
        if not isinstance(section, dict):
            raise BuildError(f"{display!r}: the base bookmark has no active section")
        containers = section.setdefault("visualContainers", {})

        self._visibility(entry, section, containers)
        if not _absent(entry.get("analysis_category")):
            self._category(display, section, entry["analysis_category"])
        if entry.get("date_filter") is not None:
            self._date(display, section, entry["date_filter"])
        if not _absent(entry.get("drill_level")):
            chart = self._container(display, containers, self.settings.chart, "chart")
            levels = dig(chart, "singleVisual", "activeProjections", "Category")
            if not isinstance(dig(levels, 0, "HierarchyLevel"), dict):
                raise BuildError(f"{display!r}: the chart capture has no drillable Category")
            levels[0]["HierarchyLevel"]["Level"] = entry["drill_level"]

        mentioned = set(picks)
        if not self.legacy:
            # every built section carries the group-visibility map
            section.setdefault("visualContainerGroups", {})
            chart = containers.get(self.settings.chart or "")
            if isinstance(chart, dict):
                single = chart.setdefault("singleVisual", {})
                single.setdefault("projections", {})
                single.setdefault("parameters", {})
        if self.legacy:
            self._legacy_checks(entry, picks)
        else:
            self._mirror_rows(display, picks, mentioned)
        if entry.get("unhide_matrix", True):
            if self.legacy:
                self._legacy_matrix(display, containers, picks, section_id, notes)
            else:
                self._matrix(display, containers, picks, entry.get("matrix_sort"))
        self._chart(display, containers, picks, mentioned)
        for key in self.settings.picker_keys:
            if picks.get(key):
                self._set_picker(display, containers, key, picks[key])
            elif key in picks or self.legacy:
                self._empty_picker(containers, key)
        if self.legacy:
            self._sync_values_slicers(containers, picks)
        for flt_name in entry.get("clear_filters") or []:
            for holder in (state, section):
                for flt in dig(holder, "filters", "byExpr") or []:
                    if isinstance(flt, dict) and flt.get("name") == flt_name:
                        flt.pop("filter", None)
        return _Built(name, display, data, group, rerendered, notes)

    def _visibility(self, entry: dict, section: dict, containers: dict) -> None:
        for hidden, key in ((False, "show"), (True, "hide")):
            for vid in entry.get(key) or []:
                single = containers.setdefault(vid, {}).setdefault("singleVisual", {})
                if hidden:
                    single["display"] = {"mode": "hidden"}
                else:
                    single.pop("display", None)
        group_hidden = {gid: False for gid in _as_list(entry.get("show_groups"))}
        group_hidden.update({gid: True for gid in _as_list(entry.get("hide_groups"))})
        if group_hidden:
            groups = section.setdefault("visualContainerGroups", {})
            for gid, hidden in group_hidden.items():
                groups.setdefault(gid, {})["isHidden"] = hidden

    def _category(self, display: str, section: dict, value: Any) -> None:
        """Set the category filter, wherever the section keeps it.

        The filter may sit in the ``byExpr`` list or in the ``byName`` map;
        every match is updated. The default layout needs one; the legacy
        layout leaves a base without one as it is.
        """
        values = _as_list(value)
        column = self.settings.category_column
        filters = dig(section, "filters") or {}
        candidates = [f for f in filters.get("byExpr") or [] if isinstance(f, dict)]
        by_name = filters.get("byName")
        if isinstance(by_name, dict):
            candidates += [f for f in by_name.values() if isinstance(f, dict)]
        found = False
        for flt in candidates:
            if dig(flt, "expression", "Column", "Property") != column:
                continue
            cond = first_in_condition(flt.get("filter"))
            if cond is None:
                continue
            cond["Values"] = [[qx.lit(qx.quoted(v))] for v in values]
            found = True
        if not found and not self.legacy:
            raise BuildError(f"{display}: base bookmark has no {column} filter slot")

    def _date(self, display: str, section: dict, value: Any) -> None:
        if value != "this_year":
            raise BuildError(f"{display!r}: date_filter {value!r} is not supported (use 'this_year')")
        cal, hierarchy = self.settings.calendar_table, self.settings.calendar_hierarchy
        for flt in dig(section, "filters", "byExpr") or []:
            if isinstance(flt, dict) and flt.get("type") == "RelativeDate":
                # the alias is the table's first character, as Power BI names it
                alias = cal[:1].lower() or "c"
                hier = {"Expression": qx.source(alias=alias)}
                hier["Hierarchy"] = hierarchy
                level = {"Expression": {"Hierarchy": hier}, "Level": "Date"}
                this_year = {"DateSpan": dict(Expression={"Now": {}}, TimeUnit=3)}
                flt["filter"] = qx.filter_body(
                    alias, cal, qx.comparison(0, {"HierarchyLevel": level}, this_year)
                )
                flt["howCreated"] = 1
                return
        raise BuildError(f"{display}: base bookmark has no RelativeDate filter slot")

    def _container(self, display: str, containers: dict, vid: str | None, what: str) -> dict:
        if not vid or not isinstance(containers.get(vid), dict):
            if what == "matrix":
                raise BuildError(f"{display}: base bookmark does not capture the Main Matrix")
            raise BuildError(f"{display}: base bookmark does not capture the {what} {vid}")
        return containers[vid]

    def _parameter_name(self, key: str) -> str:
        """The field parameter a picker slicer filters (the key when unknown)."""
        expr = self._parameter_expr(dig(self.base, "explorationState", "sections",
                                        dig(self.base, "explorationState", "activeSection"),
                                        "visualContainers") or {}, key)
        entity = dig(expr, "Column", "Expression", "SourceRef", "Entity")
        return entity if isinstance(entity, str) else key

    def _dropdown_span(self) -> str:
        """The row dropdowns as ``y-Selector 3..6``: first name, then the last number."""
        names = [self._parameter_name(k) for k in self.settings.row_dropdowns]
        if not names:
            return ""
        if len(names) == 1:
            return names[0]
        tail = re.search(r"(\d+)$", names[-1])
        return f"{names[0]}..{tail.group(1) if tail else names[-1]}"

    def _mirror_rows(self, display: str, picks: dict, mentioned: set[str]) -> None:
        """Give every row pick a dropdown (default layout only).

        A dropdown the entry sets itself is kept as written; the row picks it
        does not already hold go, in order, to the dropdowns the entry left
        free. A free dropdown that receives no row keeps the base bookmark's
        pick, so no captured dropdown is left selecting nothing.
        """
        row, dropdowns = self.settings.row_picker, self.settings.row_dropdowns
        if not row or row not in picks:
            return
        if len(picks[row]) > len(dropdowns):
            raise BuildError(f"{display}: {len(picks[row])} row dimensions but only "
                             f"{len(dropdowns)} dropdown filters ({self._dropdown_span()}) "
                             f"to carry them")
        held = {_pick_key(p) for d in dropdowns for p in picks.get(d, [])}
        waiting = [p for p in picks[row] if _pick_key(p) not in held]
        free = [d for d in dropdowns if d not in picks]
        for dropdown, pick in zip(free, waiting):
            picks[dropdown] = [pick]
            mentioned.add(dropdown)

    def _legacy_checks(self, entry: dict, picks: dict) -> None:
        category = entry.get("analysis_category")
        if isinstance(category, list):
            category = ", ".join(str(c) for c in category)
        label = category if category else entry["displayName"]
        measures = picks.get(self.settings.legacy_measures, [])
        rows = picks.get(self.settings.row_picker or "", [])
        if len(measures) < 3:
            raise BuildError(f"{label}: need >=3 measures, got {len(measures)}")
        if not 1 <= len(rows) <= 3:
            raise BuildError(f"{label}: y1 drilldown picks = {len(rows)}, expected 1-3")

    def _parameter_expr(self, containers: dict, key: str) -> dict | None:
        """The slot expression of picker ``key``: the parameter's display column.

        The picker slicer filters on the parameter's hidden fields column;
        the slot names the table behind that filter (its alias resolved) and
        the display column, which is named like the table.
        """
        flt = slicer_filter(containers.get(self.settings.pickers.get(key, "")))
        cond = first_in_condition(flt)
        column = dig(cond, "Expressions", 0, "Column")
        if not isinstance(column, dict):
            return None
        aliases = {s.get("Name"): s.get("Entity") for s in (flt or {}).get("From") or []
                   if isinstance(s, dict)}
        source = dig(column, "Expression", "SourceRef", "Source")
        entity = aliases.get(source) or dig(column, "Expression", "SourceRef", "Entity")
        return _ref("Column", entity, entity) if isinstance(entity, str) and entity else None

    def _well(self, display: str, containers: dict, keys: tuple[str, ...], kind: str,
              picks: dict, role: str) -> tuple[list, list]:
        """Projections and slot map of one well.

        Every picker of the well gets a slot at the running index, with
        length 0 when it has no picks; only the entry's own picks (and the
        rows mirrored into dropdowns) count.
        """
        projections, parameters = [], []
        seen: dict[tuple[str, str], str] = {}
        for key in keys:
            chosen = picks.get(key) or []
            for pick in chosen:
                owner = seen.get(_pick_key(pick))
                if owner is not None and owner != key:
                    raise BuildError(
                        f"{display}: {pick['column']!r} is selected in both {owner} and {key}; "
                        f"distribute the measure set across the {role} parameters instead of "
                        f"repeating it")
                if owner is not None:
                    raise BuildError(f"{display}: {pick['table']}[{pick['column']}] is "
                                     f"picked twice in one well")
                seen[_pick_key(pick)] = key
            expr = self._parameter_expr(containers, key)
            if expr is not None:
                parameters.append({"expr": expr, "index": len(projections),
                                   "length": len(chosen)})
            projections += [_ref(kind, p["table"], p["column"]) for p in chosen]
        return projections, parameters

    def _matrix(self, display: str, containers: dict, picks: dict, sort: Any) -> None:
        matrix = self._container(display, containers, self.settings.matrix, "matrix")
        single = matrix.setdefault("singleVisual", {})
        for key in ("display", "expansionStates", "prototypeQuery"):
            single.pop(key, None)
        rows, row_params = self._well(display, containers, self.settings.well("matrix_rows"),
                                      "Column", picks, "Rows")
        values, value_params = self._well(display, containers,
                                          self.settings.well("matrix_values"), "Measure", picks,
                                          "Values")
        if not rows and not values:
            for key in ("projections", "parameters", "activeProjections"):
                single.pop(key, None)
        else:
            single["projections"] = {k: v for k, v in (("Rows", rows), ("Values", values)) if v}
            single["parameters"] = {
                k: v for k, v in (("Rows", row_params if rows else []),
                                  ("Values", value_params if values else [])) if v
            }
            single["activeProjections"] = {"Rows": [rows[0]]} if rows else {}
        if sort:
            direction, expression = _sort_target(display, sort)
            single["orderBy"] = [{"Direction": direction, "Expression": expression}]

    def _relocate_matrix(self, display: str, containers: dict, section_id: Any,
                         notes: list[str]) -> None:
        """Legacy layout: move a matrix captured under a stale visual id.

        When the configured matrix is not captured but exactly one other
        captured container is matrix-shaped (rows and values projections)
        and names no visual on the page, that capture is the matrix.
        """
        vid = self.settings.matrix
        if not vid or isinstance(containers.get(vid), dict):
            return
        on_page = self._page_visuals(section_id)
        if on_page is None:
            return
        candidates = [
            cid for cid, container in containers.items()
            if cid not in on_page and isinstance(container, dict)
            and isinstance(dig(container, "singleVisual", "projections", "Rows"), list)
            and isinstance(dig(container, "singleVisual", "projections", "Values"), list)
        ]
        if len(candidates) != 1:
            return
        old = candidates[0]
        containers[vid] = containers.pop(old)
        notes.append(f"{display!r}: the matrix was captured under the stale id {old}; "
                     f"moved to {vid}")

    @staticmethod
    def _slot_in_place(single: dict, role: str, expr: dict | None, length: int) -> None:
        """Update the base slot of a one-picker well, keeping its other keys."""
        params = single.get("parameters")
        if not isinstance(params, dict):
            params = single["parameters"] = {}
        slots = params.get(role)
        if not isinstance(slots, list):
            slots = params[role] = []
        entity = dig(expr, "Column", "Expression", "SourceRef", "Entity")
        slot = next((s for s in slots if isinstance(s, dict) and dig(
            s, "expr", "Column", "Expression", "SourceRef", "Entity") == entity), None)
        if slot is None:
            slot = next((s for s in slots if isinstance(s, dict)), None)
        if slot is None:
            if expr is None:
                return
            slot = {}
            slots.append(slot)
        if expr is not None:
            slot["expr"] = expr
        slot["index"] = 0
        slot["length"] = length

    def _legacy_matrix(self, display: str, containers: dict, picks: dict,
                       section_id: Any, notes: list[str]) -> None:
        """Legacy layout: edit the base matrix capture in place.

        Only the Rows and Values projections, their slots, the first sort
        entry, the active rows and the first container filter change; the
        display mode, expansion states, prototype query and other roles stay
        as the base had them.
        """
        self._relocate_matrix(display, containers, section_id, notes)
        matrix = self._container(display, containers, self.settings.matrix, "matrix")
        single = matrix.setdefault("singleVisual", {})
        row_key, measure_key = self.settings.row_picker or "", self.settings.legacy_measures
        rows = [_ref("Column", p["table"], p["column"]) for p in picks.get(row_key, [])]
        values = [_ref("Measure", p["table"], p["column"]) for p in picks.get(measure_key, [])]
        for well in (rows, values):
            keys = [_pick_key({"table": dig(r, k, "Expression", "SourceRef", "Entity"),
                               "column": dig(r, k, "Property")})
                    for r in well for k in r]
            if len(set(keys)) != len(keys):
                raise BuildError(f"{display!r}: a field is picked twice in one well")
        projections = single.get("projections")
        if not isinstance(projections, dict):
            projections = single["projections"] = {}
        projections["Rows"] = rows
        projections["Values"] = values
        self._slot_in_place(single, "Rows", self._parameter_expr(containers, row_key), len(rows))
        self._slot_in_place(single, "Values", self._parameter_expr(containers, measure_key),
                            len(values))
        active = single.get("activeProjections")
        if not isinstance(active, dict):
            active = single["activeProjections"] = {}
        active["Rows"] = copy.deepcopy(rows)
        first = copy.deepcopy(values[0])
        order = single.get("orderBy")
        if isinstance(order, list) and order and isinstance(order[0], dict):
            order[0]["Expression"] = first
        else:
            single["orderBy"] = [{"Direction": 2, "Expression": first}]
        container_filters = dig(matrix, "filters", "byExpr")
        if isinstance(container_filters, list) and container_filters \
                and isinstance(container_filters[0], dict):
            container_filters[0]["expression"] = copy.deepcopy(values[0])

    def _chart(self, display: str, containers: dict, picks: dict, mentioned: set[str]) -> None:
        plan = (("chart_y", "Y", "Measure"), ("chart_y2", "Y2", "Measure"),
                ("chart_series", "Series", "Column"))
        for well, role, kind in plan:
            keys = self.settings.well(well)
            if not any(k in mentioned for k in keys):
                continue
            chart = self._container(display, containers, self.settings.chart, "chart")
            single = chart.setdefault("singleVisual", {})
            projections, parameters = self._well(display, containers, keys, kind, picks, role)
            single.setdefault("projections", {})[role] = projections
            if parameters:
                single.setdefault("parameters", {})[role] = parameters
            elif isinstance(single.get("parameters"), dict):
                single["parameters"].pop(role, None)

    def _set_picker(self, display: str, containers: dict, key: str, picks: list[dict]) -> None:
        vid = self.settings.pickers[key]
        container = containers.get(vid)
        if not isinstance(container, dict):
            raise BuildError(f"{display}: picker {key} ({vid}) not captured by base bookmark")
        flt = slicer_filter(container)
        if flt is None:
            raise BuildError(f"{display}: picker visual carries no general filter to rewrite")
        if not isinstance(flt.get("Where"), list) or not flt["Where"]:
            raise BuildError(f"{display}: picker visual filter has no Where clause")
        cond = first_in_condition(flt)
        if cond is None:
            raise BuildError(f"{display}: picker visual filter has no In condition")
        cond["Values"] = [[qx.lit(_pick_literal(p))] for p in picks]
        single = container["singleVisual"]
        cached = single.get("cachedFilterDisplayItems")
        if isinstance(cached, list) and cached:
            template = cached[0]
            items = []
            for pick in picks:
                item = copy.deepcopy(template)
                right = dig(item, "id", "scopeId", "Comparison", "Right", "Literal")
                if isinstance(right, dict):
                    right["Value"] = _pick_literal(pick)
                item["displayName"] = pick.get("label", pick["column"])
                items.append(item)
            single["cachedFilterDisplayItems"] = items

    def _sync_values_slicers(self, containers: dict, picks: dict) -> None:
        """Legacy layout: clear each values slicer, then point it at its dimension.

        The slicer's preselection is always dropped. When the entry gives
        the paired dimension picker picks, the slicer's column (first
        ``Values`` projection, first active ``Values`` entry, and every
        column-valued ``filters.byExpr`` expression) becomes that picker's
        first pick. A slicer the base bookmark does not capture is skipped.
        """
        for key, dimension in self.settings.values_slicers.items():
            container = containers.get(self.settings.pickers[key])
            if not isinstance(container, dict):
                continue
            flt = slicer_filter(container)
            if flt is not None:
                flt["Where"] = []
            chosen = picks.get(dimension) or []
            if not chosen:
                continue
            column = _ref("Column", chosen[0]["table"], chosen[0]["column"])["Column"]
            single = container.get("singleVisual") if isinstance(
                container.get("singleVisual"), dict) else {}
            firsts = [dig(single, "projections", "Values", 0),
                      dig(single, "activeProjections", "Values", 0)]
            firsts += [flt.get("expression") for flt in dig(container, "filters", "byExpr") or []
                       if isinstance(flt, dict)]
            for node in firsts:
                if isinstance(node, dict) and isinstance(node.get("Column"), dict):
                    node["Column"] = copy.deepcopy(column)

    def _empty_picker(self, containers: dict, key: str) -> None:
        """A picker without picks keeps its slicer's shape.

        Default layout: the In condition stays, with no values. Legacy
        layout: the conditions go. Either way the cached display list is
        kept, empty.
        """
        container = containers.get(self.settings.pickers.get(key, ""))
        flt = slicer_filter(container)
        if flt is None:
            return
        single = container["singleVisual"]
        if self.legacy:
            flt["Where"] = []
            single["cachedFilterDisplayItems"] = []
            return
        cond = first_in_condition(flt)
        if cond is not None:
            cond["Values"] = []
        if "cachedFilterDisplayItems" in single:
            single["cachedFilterDisplayItems"] = []


@dataclass
class BuildResult:
    written: list[Path]
    registered: dict[str, list[str]]
    #: one ``(path, display name, id kept)`` per written bookmark.
    details: list[tuple[Path, str, bool]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


#: the ``registered`` key for bookmarks listed outside any group.
TOP_LEVEL = "(top level)"


def build_bookmarks(report: Path, entries_path: Path, settings: BuilderSettings, *,
                    base: str | None = None, group: str | None = None,
                    keep_ids: bool = False, legacy: bool = False,
                    dry_run: bool = False) -> BuildResult:
    try:
        entries = load_json(entries_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BuildError(f"{entries_path} is not a JSON list of entries: {exc}") from exc
    if not isinstance(entries, list):
        raise BuildError(f"{entries_path} must hold a JSON list of entries")
    builder = Builder(report, settings, base=base, group=group, keep_ids=keep_ids, legacy=legacy)
    built = [builder.build(entry) for entry in entries]

    index = copy.deepcopy(builder.index) if isinstance(builder.index, dict) else None
    registered: dict[str, list[str]] = {}
    front: dict[str, list[str]] = {}
    if index is None:
        index = {"items": []}
    top_level = index.setdefault("items", [])
    for item in built:
        if item.rerendered:
            continue  # a kept bookmark keeps its place in the index
        if item.group is None:
            # no group: the bookmark is its own top-level entry
            if not any(i.get("name") == item.name for i in top_level):
                top_level.append({"name": item.name})
                registered.setdefault(TOP_LEVEL, []).append(item.name)
            continue
        group_item = next(i for i in top_level if i.get("name") == item.group)
        children = group_item.setdefault("children", [])
        if item.name in children:
            continue
        if keep_ids:
            front.setdefault(item.group, []).append(item.name)
        else:
            children.append(item.name)
        registered.setdefault(item.group, []).append(item.name)
    for group_name, names in front.items():
        group_item = next(i for i in index["items"] if i.get("name") == group_name)
        group_item["children"] = names + group_item["children"]

    notes = [note for item in built for note in item.notes]
    details = [(builder.dir / f"{b.name}.bookmark.json", b.display, b.rerendered) for b in built]
    if dry_run:
        return BuildResult([d[0] for d in details], registered, details, notes)
    written: list[Path] = []
    for item in built:
        path = builder.dir / f"{item.name}.bookmark.json"
        path.write_bytes(Layout.of_file(path).encode(dump_json(item.data)))
        written.append(path)
    if registered:
        from .rules import rewrite_json
        index_path = builder.dir / "bookmarks.json"
        if index_path.is_file():
            rewrite_json(index_path, index)
        else:
            index_path.write_bytes(Layout().encode(dump_json(index)))
    return BuildResult(written, registered, details, notes)


def builder_self_test(report: Path, settings: BuilderSettings, *, base: str | None = None,
                      legacy: bool = False) -> list[str]:
    """Build one synthetic entry in memory and check it; returns the lines to print.

    Default layout: one pick in the first matrix-values picker must become that
    picker's only selection and cached label, under a fresh name. Legacy
    layout: three measures and one row must give 3 Values and 1 Rows
    projection. Raises :class:`BuildError` when a check fails.
    """
    builder = Builder(report, settings, base=base, group=None, keep_ids=False, legacy=legacy)
    if legacy:
        measures = [{"table": "Self Test Measures", "column": c, "label": c}
                    for c in ("Self Test A", "Self Test B", "Self Test C")]
        row = [{"table": "Self Test Rows", "column": "Self Test Row", "label": "Self Test Row"}]
        entry = {"displayName": "Self test", "analysis_category": "Self test",
                 "pickers": {settings.legacy_measures: measures, settings.row_picker or "": row}}
    else:
        keys = settings.well("matrix_values") or settings.picker_keys
        if not keys:
            raise BuildError("self-test: [bookmarks] has no picker to fill")
        pick = {"table": "Self Test Measures", "column": "Self Test #", "label": "Self Test #"}
        entry = {"displayName": "Self test", "pickers": {keys[0]: [pick]}}
    built = builder.build(entry)
    section = dig(built.data, "explorationState", "sections",
                  dig(built.data, "explorationState", "activeSection"))
    containers = dig(section, "visualContainers") or {}
    if built.name == builder.base_id or built.name in builder.existing:
        raise BuildError("self-test FAIL: the built bookmark reuses an existing name")
    if legacy:
        matrix = dig(containers, settings.matrix or "", "singleVisual") or {}
        values = dig(matrix, "projections", "Values") or []
        rows = dig(matrix, "projections", "Rows") or []
        if len(values) != 3 or len(rows) != 1:
            raise BuildError(f"self-test FAIL: matrix holds {len(values)} value(s) and "
                             f"{len(rows)} row(s)")
        return ["self-test PASS"]
    key = next(iter(entry["pickers"]))
    container = containers.get(settings.pickers[key])
    cond = first_in_condition(slicer_filter(container))
    values = [dig(row, 0, "Literal", "Value") for row in (cond or {}).get("Values") or []]
    if values != [_pick_literal(entry["pickers"][key][0])]:
        raise BuildError(f"self-test FAIL: picker {key} holds {values}")
    matrix = dig(containers, settings.matrix or "", "singleVisual") or {}
    rows = dig(matrix, "projections", "Rows") or []
    names = [dig(v, "Measure", "Property") for v in dig(matrix, "projections", "Values") or []]
    return ["self-test PASS", f"  generated: {built.name}", f"  measures: {names}",
            f"  matrix projections.Rows count: {len(rows)}"]
