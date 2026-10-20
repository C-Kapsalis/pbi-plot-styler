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
    calendar_hierarchy = "Date Hierarchy"
    pickers = {<key> = "<slicer visual id>", ...}
    wells = {matrix_rows = [...], matrix_values = [...], chart_y = [...],
             chart_y2 = [...], chart_series = [...]}
"""
from __future__ import annotations

import copy
import json
import secrets
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import qx
from .canvas import dig, first_in_condition, read_json, selections, slicer_filter
from .textio import Layout, load_json, load_toml

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on Python 3.10
    import tomli as tomllib


class BuildError(ValueError):
    """An entry or the builder settings are invalid; nothing was written."""


_WELL_KEYS = ("matrix_rows", "matrix_values", "chart_y", "chart_y2", "chart_series")
_ENTRY_KEYS = {
    "displayName", "pickers", "show", "hide", "show_groups", "hide_groups",
    "target_visuals", "analysis_category", "date_filter", "drill_level",
    "unhide_matrix", "matrix_sort", "group", "clear_filters",
}


@dataclass(frozen=True)
class BuilderSettings:
    base: str | None = None
    matrix: str | None = None
    chart: str | None = None
    row_picker: str | None = None
    row_dropdowns: tuple[str, ...] = ()
    category_column: str = "Analysis Category"
    calendar_table: str = "__Calendar"
    calendar_hierarchy: str = "Date Hierarchy"
    pickers: dict[str, str] = field(default_factory=dict)
    wells: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: Legacy layout: the picker whose picks fill the matrix Values well.
    legacy_measures: str = "x_selector_1"
    #: Legacy layout: pickers emptied and then set to the first measure pick.
    legacy_values_slicers: tuple[str, ...] = ()

    def well(self, key: str) -> tuple[str, ...]:
        return self.wells.get(key, ())


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
    for key in ("row_dropdowns", "legacy_values_slicers"):
        if key in values:
            values[key] = tuple(values[key])
    if "pickers" in values:
        values["pickers"] = dict(values["pickers"])
    if "wells" in values:
        unknown_wells = set(values["wells"]) - set(_WELL_KEYS)
        if unknown_wells:
            raise BuildError(f"[bookmarks] wells has unknown key(s) {sorted(unknown_wells)}; "
                             f"valid keys: {', '.join(_WELL_KEYS)}")
        values["wells"] = {k: tuple(v) for k, v in values["wells"].items()}
    settings = BuilderSettings(**values)
    stray = [k for k in settings.legacy_values_slicers if k not in settings.pickers]
    if stray:
        raise BuildError(f"[bookmarks] legacy_values_slicers names unknown picker(s) "
                         f"{stray}; list keys of [bookmarks] pickers")
    return settings


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


def _pick_key(pick: dict) -> tuple[str, str]:
    return pick["table"], pick["column"]


def _validate_pick(pick: Any, where: str) -> dict:
    if not isinstance(pick, dict) or not isinstance(pick.get("table"), str) \
            or not isinstance(pick.get("column"), str):
        raise BuildError(f"{where}: each pick needs a 'table' and a 'column'")
    return {"label": pick["column"], **pick}


@dataclass
class _Built:
    name: str
    data: dict
    group: str | None
    rerendered: bool


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
        base_id = base or settings.base
        if not base_id:
            raise BuildError("no base bookmark: pass --base or set [bookmarks] base")
        self.base = self._find(base_id)
        if self.base is None:
            raise BuildError(f"base bookmark {base_id!r} not found in {self.dir}")
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
        return next((d for _, d in self.existing.values() if d.get("displayName") == display), None)

    def _fresh_name(self) -> str:
        while True:
            name = secrets.token_hex(10)
            if name not in self.taken:
                self.taken.add(name)
                return name

    # -- one entry ----------------------------------------------------------------
    def build(self, entry: Any) -> _Built:
        if not isinstance(entry, dict) or not isinstance(entry.get("displayName"), str) \
                or not entry["displayName"]:
            raise BuildError(f"every entry needs a displayName: {entry!r}")
        display = entry["displayName"]
        unknown = set(entry) - _ENTRY_KEYS
        if unknown:
            raise BuildError(f"{display!r}: unknown key(s) {sorted(unknown)}")
        pickers = entry.get("pickers") or {}
        if not isinstance(pickers, dict):
            raise BuildError(f"{display!r}: 'pickers' must map picker keys to lists of picks")
        for key in pickers:
            if key not in self.settings.pickers:
                raise BuildError(f"{display!r}: picker {key!r} is not in [bookmarks] pickers")
        picks = {
            key: [_validate_pick(p, f"{display!r} picker {key!r}") for p in value or []]
            for key, value in pickers.items()
        }
        group = entry.get("group") or self.group
        if group is not None and group not in self.groups:
            raise BuildError(f"{display!r}: group {group!r} is not in bookmarks.json")

        existing = self._by_display(display) if self.keep_ids else None
        rerendered = existing is not None
        data = copy.deepcopy(existing if rerendered else self.base)
        name = data.get("name") if rerendered else self._fresh_name()
        data["displayName"] = display
        data["name"] = name
        options = data.get("options") if isinstance(data.get("options"), dict) else {}
        options["targetVisualNames"] = list(entry.get("target_visuals") or [])
        data["options"] = options

        state = data.get("explorationState")
        section = dig(state, "sections", dig(state, "activeSection"))
        if not isinstance(section, dict):
            raise BuildError(f"{display!r}: the base bookmark has no active section")
        containers = section.setdefault("visualContainers", {})

        self._visibility(entry, section, containers)
        if "analysis_category" in entry:
            self._category(display, section, entry["analysis_category"])
        if "date_filter" in entry:
            self._date(display, section, entry["date_filter"])
        if "drill_level" in entry:
            chart = self._container(display, containers, self.settings.chart, "chart")
            levels = dig(chart, "singleVisual", "activeProjections", "Category")
            if not isinstance(dig(levels, 0, "HierarchyLevel"), dict):
                raise BuildError(f"{display!r}: the chart capture has no drillable Category")
            levels[0]["HierarchyLevel"]["Level"] = entry["drill_level"]

        mentioned = set(picks)
        self._mirror_rows(display, picks, mentioned)
        if self.legacy:
            self._legacy_checks(display, picks)
        effective = {
            key: picks[key] if key in picks else self._base_picks(containers, key)
            for key in self.settings.pickers
        }
        if entry.get("unhide_matrix", True):
            self._matrix(display, containers, effective, entry.get("matrix_sort"))
        self._chart(display, containers, effective, mentioned)
        axis = picks.get(self.settings.legacy_measures) or []
        for key in self.settings.pickers:
            if picks.get(key):
                self._set_picker(display, containers, key, picks[key])
            elif self.legacy and key in self.settings.legacy_values_slicers and axis:
                # cleared of whatever the base held, then synced to the axis
                self._set_picker(display, containers, key, axis[:1])
            elif key in picks or self.legacy:
                self._empty_picker(containers, key)
        if rerendered:
            for flt_name in entry.get("clear_filters") or []:
                for holder in (state, section):
                    for flt in dig(holder, "filters", "byExpr") or []:
                        if isinstance(flt, dict) and flt.get("name") == flt_name:
                            flt.pop("filter", None)
        return _Built(name, data, group, rerendered)

    def _visibility(self, entry: dict, section: dict, containers: dict) -> None:
        for hidden, key in ((False, "show"), (True, "hide")):
            for vid in entry.get(key) or []:
                single = containers.setdefault(vid, {}).setdefault("singleVisual", {})
                if hidden:
                    single["display"] = {"mode": "hidden"}
                else:
                    single.pop("display", None)
        for hidden, key in ((False, "show_groups"), (True, "hide_groups")):
            ids = entry.get(key) or []
            if ids:
                groups = section.setdefault("visualContainerGroups", {})
                for gid in ids:
                    groups.setdefault(gid, {})["isHidden"] = hidden

    def _category(self, display: str, section: dict, value: Any) -> None:
        values = [value] if isinstance(value, str) else list(value or [])
        column = self.settings.category_column
        for flt in dig(section, "filters", "byExpr") or []:
            if dig(flt, "expression", "Column", "Property") == column:
                cond = first_in_condition(flt.get("filter"))
                if cond is None:
                    break
                cond["Values"] = [[qx.lit(qx.quoted(v))] for v in values]
                return
        raise BuildError(f"{display!r}: the base bookmark has no [{column}] filter with an In condition")

    def _date(self, display: str, section: dict, value: Any) -> None:
        if value != "this_year":
            raise BuildError(f"{display!r}: date_filter {value!r} is not supported (use 'this_year')")
        cal, hierarchy = self.settings.calendar_table, self.settings.calendar_hierarchy
        for flt in dig(section, "filters", "byExpr") or []:
            if isinstance(flt, dict) and flt.get("type") == "RelativeDate":
                alias = qx.alias_of(cal, "c")
                hier = {"Expression": qx.source(alias=alias)}
                hier["Hierarchy"] = hierarchy
                level = {"Expression": {"Hierarchy": hier}, "Level": "Date"}
                this_year = {"DateSpan": dict(Expression={"Now": {}}, TimeUnit=3)}
                flt["filter"] = qx.filter_body(
                    alias, cal, qx.comparison(0, {"HierarchyLevel": level}, this_year)
                )
                flt["howCreated"] = 1
                return
        raise BuildError(f"{display!r}: the base bookmark has no RelativeDate filter")

    def _container(self, display: str, containers: dict, vid: str | None, what: str) -> dict:
        if not vid or not isinstance(containers.get(vid), dict):
            raise BuildError(f"{display!r}: the {what} {vid!r} is not captured in the base bookmark")
        return containers[vid]

    def _mirror_rows(self, display: str, picks: dict, mentioned: set[str]) -> None:
        """Give every row pick a dropdown, and clear dropdowns left without one.

        A dropdown the entry sets itself is kept as written; the row picks it
        does not already hold go, in order, to the dropdowns the entry left
        free (when every dropdown is set explicitly, the entry's choice
        stands). Free dropdowns that receive no row are emptied, so a pick
        inherited from the base bookmark cannot linger.
        """
        row, dropdowns = self.settings.row_picker, self.settings.row_dropdowns
        if not row or row not in picks:
            return
        if len(picks[row]) > len(dropdowns):
            raise BuildError(f"{display!r}: {len(picks[row])} row pick(s) but only "
                             f"{len(dropdowns)} row dropdown(s) to mirror them into")
        held = {_pick_key(p) for d in dropdowns for p in picks.get(d, [])}
        waiting = [p for p in picks[row] if _pick_key(p) not in held]
        free = [d for d in dropdowns if d not in picks]
        for position, dropdown in enumerate(free):
            picks[dropdown] = waiting[position:position + 1]
            mentioned.add(dropdown)

    def _legacy_checks(self, display: str, picks: dict) -> None:
        measures = picks.get(self.settings.legacy_measures, [])
        rows = picks.get(self.settings.row_picker or "", [])
        if len(measures) < 3:
            raise BuildError(f"{display!r}: the legacy layout needs at least 3 measures")
        if not 1 <= len(rows) <= 3:
            raise BuildError(f"{display!r}: the legacy layout needs 1 to 3 row picks")

    def _base_picks(self, containers: dict, key: str) -> list[dict]:
        vid = self.settings.pickers.get(key)
        return [{"table": t, "column": c, "label": c}
                for t, c in selections(containers.get(vid))] if vid else []

    def _parameter_expr(self, containers: dict, key: str) -> dict | None:
        flt = slicer_filter(containers.get(self.settings.pickers.get(key, "")))
        cond = first_in_condition(flt)
        column = dig(cond, "Expressions", 0, "Column")
        if not isinstance(column, dict):
            return None
        aliases = {s.get("Name"): s.get("Entity") for s in (flt or {}).get("From") or []
                   if isinstance(s, dict)}
        source = dig(column, "Expression", "SourceRef", "Source")
        entity = aliases.get(source) or dig(column, "Expression", "SourceRef", "Entity")
        return _ref("Column", entity, column.get("Property")) if entity else None

    def _well(self, display: str, containers: dict, keys: tuple[str, ...], kind: str,
              effective: dict) -> tuple[list, list]:
        projections, parameters, seen = [], [], set()
        for key in keys:
            picks = effective.get(key) or []
            if not picks:
                continue
            for pick in picks:
                if _pick_key(pick) in seen:
                    raise BuildError(f"{display!r}: {pick['table']}[{pick['column']}] is "
                                     f"picked twice in one well")
                seen.add(_pick_key(pick))
            expr = self._parameter_expr(containers, key)
            if expr is not None:
                parameters.append({"expr": expr, "index": len(projections), "length": len(picks)})
            projections += [_ref(kind, p["table"], p["column"]) for p in picks]
        return projections, parameters

    def _matrix(self, display: str, containers: dict, effective: dict, sort: Any) -> None:
        matrix = self._container(display, containers, self.settings.matrix, "matrix")
        single = matrix.setdefault("singleVisual", {})
        for key in ("display", "expansionStates", "prototypeQuery"):
            single.pop(key, None)
        if self.legacy:
            rows_keys = (self.settings.row_picker,) if self.settings.row_picker else ()
            value_keys = (self.settings.legacy_measures,)
        else:
            rows_keys = self.settings.well("matrix_rows")
            value_keys = self.settings.well("matrix_values")
        rows, row_params = self._well(display, containers, rows_keys, "Column", effective)
        values, value_params = self._well(display, containers, value_keys, "Measure", effective)
        if not rows and not values:
            for key in ("projections", "parameters", "activeProjections"):
                single.pop(key, None)
        else:
            single["projections"] = {k: v for k, v in (("Rows", rows), ("Values", values)) if v}
            single["parameters"] = {
                k: v for k, v in (("Rows", row_params), ("Values", value_params)) if v
            }
            single["activeProjections"] = {"Rows": [rows[0]]} if rows else {}
        if self.legacy and values:
            sort = {"measure": {"table": dig(values, 0, "Measure", "Expression", "SourceRef",
                                             "Entity"),
                                "column": dig(values, 0, "Measure", "Property")}}
        if sort:
            kind = "Measure" if "measure" in sort else "Column"
            target = sort.get(kind.lower())
            if not isinstance(target, dict):
                raise BuildError(f"{display!r}: matrix_sort needs a 'measure' or 'column'")
            single["orderBy"] = [{"Direction": sort.get("direction", 2),
                                  "Expression": _ref(kind, target["table"], target["column"])}]

    def _chart(self, display: str, containers: dict, effective: dict, mentioned: set[str]) -> None:
        plan = (("chart_y", "Y", "Measure"), ("chart_y2", "Y2", "Measure"),
                ("chart_series", "Series", "Column"))
        for well, role, kind in plan:
            keys = self.settings.well(well)
            if not any(k in mentioned for k in keys):
                continue
            chart = self._container(display, containers, self.settings.chart, "chart")
            single = chart.setdefault("singleVisual", {})
            projections, parameters = self._well(display, containers, keys, kind, effective)
            single.setdefault("projections", {})[role] = projections
            if parameters:
                single.setdefault("parameters", {})[role] = parameters

    def _set_picker(self, display: str, containers: dict, key: str, picks: list[dict]) -> None:
        vid = self.settings.pickers[key]
        container = containers.get(vid)
        if not isinstance(container, dict):
            raise BuildError(f"{display!r}: picker {key!r} ({vid}) is not captured in the base bookmark")
        cond = first_in_condition(slicer_filter(container))
        if cond is None:
            raise BuildError(f"{display!r}: picker {key!r} has no general filter with an In condition")
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

    def _empty_picker(self, containers: dict, key: str) -> None:
        container = containers.get(self.settings.pickers.get(key, ""))
        flt = slicer_filter(container)
        if flt is None:
            return
        flt["Where"] = []
        container["singleVisual"].pop("cachedFilterDisplayItems", None)


@dataclass
class BuildResult:
    written: list[Path]
    registered: dict[str, list[str]]


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

    written: list[Path] = []
    if dry_run:
        return BuildResult([builder.dir / f"{b.name}.bookmark.json" for b in built], registered)
    for item in built:
        path = builder.dir / f"{item.name}.bookmark.json"
        path.write_bytes(Layout.of_file(path).encode(json.dumps(item.data, indent=2)))
        written.append(path)
    if registered:
        from .rules import rewrite_json
        index_path = builder.dir / "bookmarks.json"
        if index_path.is_file():
            rewrite_json(index_path, index)
        else:
            index_path.write_bytes(Layout().encode(json.dumps(index, indent=2)))
    return BuildResult(written, registered)
