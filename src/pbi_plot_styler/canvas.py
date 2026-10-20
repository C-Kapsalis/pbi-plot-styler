"""Shared vocabulary for the canvas conventions.

A "canvas" is the standardized report page the convention rules look after:
a matrix plus a line-and-stacked-column chart, driven by selector (field
parameter) slicers. The names involved (selector table patterns, the gate
measures, the category table, the filter-panel group, ...) all come from
:class:`Settings`, which reads optional sections of ``plotstyler.toml`` and
falls back to generic defaults.

This module also owns the read-only report index the rules share: pages,
visuals, their semantic names, and the helpers that answer "is this a canvas
page", "which slicers are selector slicers" and "what does this bookmark's
slicer select".
"""
from __future__ import annotations

import dataclasses
import fnmatch
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator
from .textio import Layout, dump_json, load_toml

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on Python 3.10
    import tomli as tomllib


class SettingsError(ValueError):
    """A malformed canvas section in the config file."""


# -- settings -----------------------------------------------------------------
@dataclass(frozen=True)
class CanvasSection:
    matrix_types: tuple[str, ...] = ("pivotTable", "matrix")
    combo_types: tuple[str, ...] = ("lineStackedColumnComboChart",)
    excluded_page_fragments: tuple[str, ...] = ("cohort", "ltv")
    selector_tables: tuple[str, ...] = ("x-*", "y-*")
    measure_selector_tables: tuple[str, ...] = ("x-*",)
    dimension_selector_tables: tuple[str, ...] = ("y-*",)
    exclude_reports: tuple[str, ...] = ("M.Report", "-M.Report")


@dataclass(frozen=True)
class GatesSection:
    table: str = "f-Filters"
    slicer_measure: str = "f-Slicer"
    list_measure: str = "f-All"
    mode_map: tuple[tuple[str, str], ...] = (
        ("Dropdown", "slicer_measure"),
        ("Basic", "list_measure"),
    )
    name_heuristic: bool = False

    def measure_for_mode(self, mode: str | None) -> str | None:
        for literal, role in self.mode_map:
            if literal == mode:
                return getattr(self, role)
        return None


@dataclass(frozen=True)
class CategorySection:
    table: str = "z-Map Dimension-Measure Groupings"
    column: str = "Analysis Category"
    chrome_words: tuple[str, ...] = (
        "info", "overview", "menu", "edit", "year", "quarter", "month",
        "week", "day",
    )
    chrome_prefixes: tuple[str, ...] = ("<", "++")


@dataclass(frozen=True)
class PlaceholdersSection:
    blank_dimension_table: str = "#Report Measures"
    template_slot_table: str = "Helper Measures"


@dataclass(frozen=True)
class PanelSection:
    group_name: str = "y_filters_group"
    filter_tables: tuple[str, ...] = (
        "y-Selector 3", "y-Selector 4", "y-Selector 5", "y-Selector 6",
    )
    min_slicers: int = 6
    min_combos: int = 1
    min_matrices: int = 1


@dataclass(frozen=True)
class FormatSelectorSection:
    table: str = "z-Selector Format"
    column: str = "Selector Format"
    item: str = "Format"
    filter_name: str = "format_selector_filter"


@dataclass(frozen=True)
class AnswerBookmarksSection:
    prefixes: tuple[str, ...] = ()
    main_page: str | None = None
    matrix: str | None = None
    slicers: tuple[tuple[str, str], ...] = ()
    row_dropdowns: tuple[str, ...] | None = None
    inherited_fingerprints: tuple[str, ...] = ()
    submenu_prefix: str = "Submenu"
    slot_mode: str = "all-roles"
    #: accepted-findings file used when the run names no --baseline
    #: (relative to the config file).
    baseline: str | None = None


@dataclass(frozen=True)
class Settings:
    """Every name the convention rules depend on, with generic defaults."""

    canvas: CanvasSection = CanvasSection()
    gates: GatesSection = GatesSection()
    category: CategorySection = CategorySection()
    placeholders: PlaceholdersSection = PlaceholdersSection()
    panel: PanelSection = PanelSection()
    format_selector: FormatSelectorSection = FormatSelectorSection()
    answer_bookmarks: AnswerBookmarksSection = AnswerBookmarksSection()

    # -- table classification ------------------------------------------------
    def is_selector_table(self, name: str | None) -> bool:
        return _matches(name, self.canvas.selector_tables)

    def is_measure_selector(self, name: str | None) -> bool:
        return _matches(name, self.canvas.measure_selector_tables)

    def is_dimension_selector(self, name: str | None) -> bool:
        return _matches(name, self.canvas.dimension_selector_tables)


def _matches(name: str | None, patterns: Iterable[str]) -> bool:
    """Whether ``name`` matches one of the shell-style patterns, ignoring case."""
    if not isinstance(name, str):
        return False
    lowered = name.lower()
    return any(fnmatch.fnmatchcase(lowered, p.lower()) for p in patterns)


#: TOML section -> (Settings attribute, section class)
_SECTIONS = {
    "canvas": ("canvas", CanvasSection),
    "gates": ("gates", GatesSection),
    "category": ("category", CategorySection),
    "placeholders": ("placeholders", PlaceholdersSection),
    "panel": ("panel", PanelSection),
    "format_selector": ("format_selector", FormatSelectorSection),
    "answer_bookmarks": ("answer_bookmarks", AnswerBookmarksSection),
}

#: Keys accepted for compatibility but not used by any rule.
_IGNORED_KEYS: dict[str, set[str] | None] = {"caption": None}

#: Sections of plotstyler.toml that belong to other commands.
FOREIGN_SECTIONS = {"tables", "targets", "style", "bookmarks", "caption"}



def _coerce(section: str, key: str, default: Any, value: Any) -> Any:
    where = f"[{section}] {key}"
    if isinstance(default, bool):
        if not isinstance(value, bool):
            raise SettingsError(f"{where} must be true or false.")
        return value
    if isinstance(default, int):
        if isinstance(value, bool) or not isinstance(value, int):
            raise SettingsError(f"{where} must be an integer.")
        return value
    if key in ("slicers", "mode_map"):
        if not isinstance(value, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in value.items()
        ):
            raise SettingsError(f"{where} must be a table of string = string pairs.")
        return tuple(value.items())
    if isinstance(default, tuple) or key == "row_dropdowns":
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise SettingsError(f"{where} must be a list of strings.")
        return tuple(value)
    if not isinstance(value, str):
        raise SettingsError(f"{where} must be a string.")
    return value


def settings_from_mapping(raw: dict[str, Any], source: str = "config") -> Settings:
    """Build :class:`Settings` from parsed TOML, ignoring foreign sections."""
    values: dict[str, Any] = {}
    unknown_sections = set(raw) - set(_SECTIONS) - FOREIGN_SECTIONS
    if unknown_sections:
        raise SettingsError(
            f"{source} has unknown section(s): {', '.join(sorted(unknown_sections))}. "
            f"Valid sections are {', '.join(sorted(set(_SECTIONS) | FOREIGN_SECTIONS))}."
        )
    for section, body in raw.items():
        if section in FOREIGN_SECTIONS:
            continue
        if not isinstance(body, dict):
            raise SettingsError(f"{source}: [{section}] must be a table.")
        attr, cls = _SECTIONS[section]
        defaults = {f.name: f.default for f in dataclasses.fields(cls)}
        ignored = _IGNORED_KEYS.get(section) or set()
        unknown = set(body) - set(defaults) - ignored
        if unknown:
            raise SettingsError(
                f"{source} has unknown key(s) under [{section}]: "
                f"{', '.join(sorted(unknown))}. Valid keys are: "
                f"{', '.join(sorted(defaults))}."
            )
        kwargs = {
            key: _coerce(section, key, defaults[key], value)
            for key, value in body.items()
            if key not in ignored
        }
        values[attr] = cls(**kwargs)
    return Settings(**values)


def load_settings(path: Path | None) -> Settings:
    """Read the canvas sections of a ``plotstyler.toml`` (defaults if None)."""
    if path is None:
        return Settings()
    try:
        raw = load_toml(Path(path))
    except tomllib.TOMLDecodeError as exc:
        raise SettingsError(f"{path} is not valid TOML: {exc}.") from exc
    return settings_from_mapping(raw, str(path))


# -- small JSON helpers ----------------------------------------------------------
def read_json(path: Path) -> Any:
    """Parsed JSON of ``path``, or ``None`` when missing or unreadable."""
    try:
        return json.loads(path.read_bytes().decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def write_json(path: Path, data: Any, *, trailing_newline: bool = True) -> None:
    """Write ``data`` as 2-space JSON.

    An existing file keeps its BOM, line endings and final newline; a new
    file is written with LF endings and ``trailing_newline``.
    """
    layout = Layout.of_file(path) if path.exists() else Layout(final_newline=trailing_newline)
    path.write_bytes(layout.encode(dump_json(data)))


def dig(node: Any, *keys: Any) -> Any:
    """Follow dict keys / list indexes; ``None`` as soon as one is missing."""
    for key in keys:
        if isinstance(key, int):
            if not isinstance(node, list) or not -len(node) <= key < len(node):
                return None
            node = node[key]
        else:
            if not isinstance(node, dict):
                return None
            node = node.get(key)
    return node


def source_entity(expr_holder: Any) -> str | None:
    """``Entity`` of a ``{"Expression": {"SourceRef": {"Entity": ...}}}`` node."""
    entity = dig(expr_holder, "Expression", "SourceRef", "Entity")
    return entity if isinstance(entity, str) else None


def walk(node: Any, depth: int = 0, limit: int = 10_000) -> Iterator[Any]:
    """Every dict and list below ``node`` (pre-order)."""
    if depth > limit:
        return
    yield node
    if isinstance(node, dict):
        for value in node.values():
            yield from walk(value, depth + 1, limit)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value, depth + 1, limit)


def literal(value: str) -> dict:
    return {"expr": {"Literal": {"Value": value}}}


# -- the report index -----------------------------------------------------------
@dataclass
class Visual:
    """One ``visual.json`` of a page."""

    page_id: str
    folder: str
    path: Path
    data: Any

    @property
    def name(self) -> str:
        raw = self.data.get("name") if isinstance(self.data, dict) else None
        return raw if isinstance(raw, str) else self.folder

    @property
    def is_group(self) -> bool:
        return isinstance(self.data, dict) and isinstance(self.data.get("visualGroup"), dict)

    @property
    def semantic_name(self) -> str:
        if self.is_group:
            display = self.data["visualGroup"].get("displayName")
            if isinstance(display, str) and display:
                return display
        return self.name

    @property
    def vtype(self) -> str:
        if self.is_group:
            return "group"
        kind = dig(self.data, "visual", "visualType")
        return kind if isinstance(kind, str) else "unknown"

    @property
    def parent(self) -> str | None:
        raw = self.data.get("parentGroupName") if isinstance(self.data, dict) else None
        return raw if isinstance(raw, str) else None

    @property
    def query_state(self) -> dict:
        state = dig(self.data, "visual", "query", "queryState")
        return state if isinstance(state, dict) else {}

    def query_entities(self) -> set[str]:
        """Every ``Entity`` string inside the visual's query."""
        query = dig(self.data, "visual", "query")
        found: set[str] = set()
        for node in walk(query):
            if isinstance(node, dict) and isinstance(node.get("Entity"), str):
                found.add(node["Entity"])
        return found


@dataclass
class Page:
    page_id: str
    path: Path
    data: Any
    visuals: list[Visual] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        raw = self.data.get("displayName") if isinstance(self.data, dict) else None
        return raw if isinstance(raw, str) else ""

    @property
    def hidden(self) -> bool:
        return isinstance(self.data, dict) and self.data.get("visibility") == "HiddenInViewMode"

    def count(self, predicate) -> int:
        return sum(1 for v in self.visuals if predicate(v.vtype))


@dataclass
class ReportIndex:
    report_dir: Path
    pages: list[Page]

    @classmethod
    def load(cls, report_dir: Path) -> "ReportIndex":
        pages_dir = Path(report_dir) / "definition" / "pages"
        pages: list[Page] = []
        if pages_dir.is_dir():
            for page_dir in sorted(p for p in pages_dir.iterdir() if p.is_dir()):
                page = Page(page_dir.name, page_dir, read_json(page_dir / "page.json"))
                for visual_json in sorted(page_dir.glob("visuals/*/visual.json")):
                    data = read_json(visual_json)
                    if isinstance(data, dict):
                        page.visuals.append(
                            Visual(page_dir.name, visual_json.parent.name, visual_json, data)
                        )
                pages.append(page)
        return cls(Path(report_dir), pages)

    def page(self, page_id: str) -> Page | None:
        return next((p for p in self.pages if p.page_id == page_id), None)

    def visuals(self) -> Iterator[Visual]:
        for page in self.pages:
            yield from page.visuals

    def semantic_names(self) -> dict[str, str]:
        """raw visual ``name`` -> semantic name, across all pages."""
        return {v.name: v.semantic_name for v in self.visuals()}

    # -- canvas pages --------------------------------------------------------
    def is_canvas_page(self, page: Page, settings: Settings) -> bool:
        cfg = settings.canvas
        if not page.count(lambda t: t in cfg.matrix_types):
            return False
        if not page.count(lambda t: t in cfg.combo_types):
            return False
        lowered = page.display_name.lower()
        return not any(fragment.lower() in lowered for fragment in cfg.excluded_page_fragments)

    def canvas_page_ids(self, settings: Settings) -> list[str]:
        return [p.page_id for p in self.pages if self.is_canvas_page(p, settings)]

    def main_page(self, settings: Settings) -> Page | None:
        """The canvas main page: enough slicers, a combo chart and a matrix.

        Several candidates: the one with most slicers, ties broken by the
        larger page folder name.
        """
        panel = settings.panel
        best: tuple[int, str] | None = None
        chosen: Page | None = None
        for page in self.pages:
            slicers = page.count(lambda t: t == "slicer")
            combos = page.count(lambda t: "Combo" in t)
            matrices = page.count(lambda t: t == "pivotTable")
            if slicers < panel.min_slicers or combos < panel.min_combos or matrices < panel.min_matrices:
                continue
            rank = (slicers, page.page_id)
            if best is None or rank > best:
                best, chosen = rank, page
        return chosen


def canvas_pages(report_dir: Path, settings: Settings | None = None) -> list[str]:
    """Folder names of the report's canvas ("typical template") pages."""
    settings = settings or Settings()
    return ReportIndex.load(report_dir).canvas_page_ids(settings)


@dataclass(frozen=True)
class SelectorSlicer:
    page_id: str
    visual_id: str
    path: Path
    tables: tuple[str, ...]


def slicer_selector_tables(visual: Visual, settings: Settings) -> list[str]:
    """Selector tables bound in a slicer's ``Values`` projections."""
    tables: list[str] = []
    values = visual.query_state.get("Values") or {}
    for projection in values.get("projections") or []:
        entity = source_entity(dig(projection, "field", "Column"))
        if settings.is_selector_table(entity) and entity not in tables:
            tables.append(entity)
    return tables


def selector_slicers(
    report_dir: Path,
    canvas_only: bool = True,
    settings: Settings | None = None,
    index: ReportIndex | None = None,
) -> list[SelectorSlicer]:
    """Slicer visuals bound to a selector table (canvas pages only by default)."""
    settings = settings or Settings()
    index = index or ReportIndex.load(report_dir)
    allowed = set(index.canvas_page_ids(settings)) if canvas_only else None
    found: list[SelectorSlicer] = []
    for visual in index.visuals():
        if allowed is not None and visual.page_id not in allowed:
            continue
        if visual.vtype != "slicer":
            continue
        tables = slicer_selector_tables(visual, settings)
        if tables:
            found.append(SelectorSlicer(visual.page_id, visual.folder, visual.path, tuple(tables)))
    return found


# -- bookmark helpers -----------------------------------------------------------
@dataclass
class Bookmark:
    path: Path
    data: dict

    @property
    def name(self) -> str:
        raw = self.data.get("name")
        return raw if isinstance(raw, str) else self.path.name[: -len(".bookmark.json")]

    @property
    def display_name(self) -> str:
        raw = self.data.get("displayName")
        return raw if isinstance(raw, str) else self.name

    @property
    def state(self) -> dict:
        state = self.data.get("explorationState")
        return state if isinstance(state, dict) else {}

    @property
    def sections(self) -> dict:
        sections = self.state.get("sections")
        return sections if isinstance(sections, dict) else {}

    @property
    def active_section(self) -> dict:
        active = self.state.get("activeSection")
        section = self.sections.get(active) if isinstance(active, str) else None
        return section if isinstance(section, dict) else {}

    def containers(self, section: dict | None = None) -> dict:
        section = self.active_section if section is None else section
        found = section.get("visualContainers") if isinstance(section, dict) else None
        return found if isinstance(found, dict) else {}


def load_bookmarks(report_dir: Path) -> list[Bookmark]:
    found: list[Bookmark] = []
    for path in sorted((Path(report_dir) / "definition" / "bookmarks").glob("*.bookmark.json")):
        data = read_json(path)
        if isinstance(data, dict):
            found.append(Bookmark(path, data))
    return found


# A slicer selection literal: '''<table>''[<field>]' (table: shortest match,
# field: greedy).
#: A saved field-parameter pick, ``'''T''[C]'``: inside the outer quotes an
#: apostrophe of the table or column name is written four times and a closing
#: bracket of the column name twice.
_SELECTION = re.compile(r"^'''((?:[^']|'''')+)''\[((?:[^\]]|\]\])+)\]'$", re.DOTALL)
# The same literal anywhere inside a serialized container.


def parse_selection(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, str):
        return None
    match = _SELECTION.match(value)
    if not match:
        return None
    four = "'" * 4
    table = match.group(1).replace(four, "'")
    column = match.group(2).replace("]]", "]").replace(four, "'")
    return table, column


def selection_literals(node: Any) -> list[tuple[str, str]]:
    """Every ``(table, field)`` pick held by a ``Literal`` anywhere in ``node``.

    Names come back unescaped; each pick is listed once, in document order.
    """
    found: list[tuple[str, str]] = []
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            parsed = parse_selection(dig(current, "Literal", "Value"))
            if parsed and parsed not in found:
                found.append(parsed)
            stack.extend(reversed(list(current.values())))
        elif isinstance(current, list):
            stack.extend(reversed(current))
    return found


def slicer_filter(container: Any) -> dict | None:
    flt = dig(container, "singleVisual", "objects", "merge", "general", 0,
              "properties", "filter", "filter")
    return flt if isinstance(flt, dict) else None


def first_in_condition(flt: Any) -> dict | None:
    if not isinstance(flt, dict):
        return None
    for where in flt.get("Where") or []:
        cond = dig(where, "Condition", "In")
        if isinstance(cond, dict):
            return cond
    return None


def selections(container: Any) -> list[tuple[str, str]]:
    """``(table, field)`` picks a bookmark stores for one slicer container.

    Only the authoritative filter is read (never the cached display items).
    Unparseable values are dropped and duplicates kept once.
    """
    cond = first_in_condition(slicer_filter(container))
    picks: list[tuple[str, str]] = []
    for row in (cond or {}).get("Values") or []:
        value = dig(row, 0, "Literal", "Value")
        parsed = parse_selection(value)
        if parsed and parsed not in picks:
            picks.append(parsed)
    return picks


def slicer_mode(visual: Visual) -> str | None:
    """The first single-quoted word of the slicer's ``data`` mode."""
    for entry in dig(visual.data, "visual", "objects", "data") or []:
        value = dig(entry, "properties", "mode", "expr", "Literal", "Value")
        if isinstance(value, str):
            match = re.search(r"'(\w+)'", value)
            if match:
                return match.group(1)
    return None
