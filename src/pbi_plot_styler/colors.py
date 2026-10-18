"""``colors sync`` / ``colors reset``: one colour per measure, from the model.

The colour rule lives in the model as a palette measure (default
``'w-Colors'[c-Measure Color]``)::

    VAR _order = SELECTEDVALUE ( 'x-Selector 1'[x-Selector 1 Order] )
    VAR _slot = MOD ( _order + <offset>, <modulus> ) + <base>
    RETURN SWITCH ( _slot, 1, "#RRGGBB", 2, "#RRGGBB", ... )

so a measure's colour is the slot its row's sort order lands on in the
picker field parameter. ``sync`` stamps that colour wherever the measure
renders as a column series or a matrix column, including measures that only
a multi-series bookmark shows; ``reset`` reverts what ``sync`` wrote.

Exit codes: 0 when there are changes, 2 when there are none, 3 when the
palette or the picker cannot be read (nothing is written).
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from . import qx
from .canvas import Bookmark, dig, load_bookmarks, read_json
from .rules import rewrite_json
from .tmdl import SemanticModel, strip_dax_comments

BAR_TYPES = (
    "clusteredColumnChart", "stackedColumnChart", "hundredPercentStackedColumnChart",
    "clusteredBarChart", "stackedBarChart", "hundredPercentStackedBarChart",
    "lineChart", "areaChart", "stackedAreaChart",
    "lineClusteredColumnComboChart", "lineStackedColumnComboChart",
)
TABLE_TYPES = ("pivotTable", "tableEx")
BLACK = "#000000"
_TABLE_OWNED = ("fontColor", "styleValues", "styleHeader", "styleTotal")


class PaletteError(ValueError):
    """The palette measure or its picker cannot be read (exit 3)."""


@dataclass(frozen=True)
class Palette:
    picker: str
    offset: int
    modulus: int
    base: int
    slots: dict[int, str]

    def colour(self, order: int) -> str:
        """The colour of the slot a picker row's sort order lands on."""
        shifted = order + self.offset
        return self.slots[self.base + shifted % self.modulus]

    @property
    def colours(self) -> set[str]:
        return {c.lower() for c in self.slots.values()}


_DECL = r"^(?P<indent>[ \t]+)measure\s+(?:'{q}'|\"{d}\"|{b})\s*="
_NEXT_OBJECT = re.compile(r"^[ \t]+(?:measure|partition|column)\b", re.MULTILINE)
_PICKER = re.compile(r"SELECTEDVALUE\s*\(\s*(?:'((?:[^']|'')+)'|([A-Za-z_][\w \-]*?))\s*\[")
_MOD = re.compile(
    r"MOD\s*\(\s*[^,()]+?(?:\+\s*(-?\d+)\s*)?,\s*(\d+)\s*\)\s*\+\s*(-?\d+)", re.IGNORECASE
)
_SLOT = re.compile(r"(\d+)\s*,\s*\"(#[0-9A-Fa-f]{6})\"")


def _measure_body(model: SemanticModel, measure: str, host: str) -> str:
    tables = sorted(model.raw_by_table, key=lambda t: t != host)
    escaped = re.escape(measure)
    decl = re.compile(
        _DECL.format(q=escaped.replace("'", "''"), d=escaped, b=escaped), re.MULTILINE
    )
    for table in tables:
        text = model.raw_by_table[table]
        match = decl.search(text)
        if match:
            following = _NEXT_OBJECT.search(text, match.end())
            return text[match.start(): following.start() if following else len(text)]
    raise PaletteError(f"no table declares the palette measure [{measure}]")


def parse_palette(model: SemanticModel, measure: str, host: str) -> Palette:
    body = strip_dax_comments(_measure_body(model, measure, host))
    picker = _PICKER.search(body)
    if not picker:
        raise PaletteError(f"[{measure}] has no SELECTEDVALUE('<picker>'[...]) call")
    mod = _MOD.search(body)
    if not mod:
        raise PaletteError(f"[{measure}] has no MOD(<order> + offset, modulus) + base")
    offset, modulus, base = int(mod.group(1) or 0), int(mod.group(2)), int(mod.group(3))
    slots = {int(n): colour.lower() for n, colour in _SLOT.findall(body)}
    if modulus <= 0 or len(slots) != modulus:
        raise PaletteError(
            f"[{measure}] declares {len(slots)} colour slot(s) for modulus {modulus}"
        )
    missing = [n for n in range(base, base + modulus) if n not in slots]
    if missing:
        raise PaletteError(f"[{measure}] has no colour for slot(s) {missing}")
    name = picker.group(1).replace("''", "'") if picker.group(1) else picker.group(2).strip()
    return Palette(name, offset, modulus, base, slots)


def picker_registry(model: SemanticModel, picker: str) -> dict[str, int]:
    """``"Table.Measure"`` -> sort order, in source order (first wins)."""
    if model.table_named(picker) is None:
        raise PaletteError(f"the picker table {picker!r} is not in the model")
    registry: dict[str, int] = {}
    for position, ref in enumerate(r for r in model.nameof_refs(picker) if r.in_tuple):
        if ref.qualifier:
            if not model.has_measure(ref.qualifier, ref.name):
                continue  # a column row
            key = f"{ref.qualifier}.{ref.name}"
        else:
            home = model.home_table(ref.name)
            if home is None:
                raise PaletteError(
                    f"{picker!r} row [{ref.name}] names no measure of the model"
                )
            key = f"{home}.{ref.name}"
        order = int(ref.ordinal) if ref.ordinal is not None else position + 1
        registry.setdefault(key, order)
    if not registry:
        raise PaletteError(f"the picker {picker!r} registers no measure")
    return registry


# -- report side ------------------------------------------------------------------------
def _measure_keys(items: Any) -> list[str]:
    keys = []
    for item in items or []:
        measure = dig(item, "field", "Measure") or dig(item, "Measure")
        entity = dig(measure, "Expression", "SourceRef", "Entity")
        prop = dig(measure, "Property")
        if isinstance(entity, str) and isinstance(prop, str):
            keys.append(f"{entity}.{prop}")
    return keys


_literal_colour = qx.hex_colour
_theme_colour = qx.theme_colour


def _true() -> dict:
    return qx.prop_literal("true")


def _owned_colour(prop: Any) -> str | None:
    value = dig(prop, "solid", "color", "expr", "Literal", "Value")
    return value.strip("'").lower() if isinstance(value, str) else None


def _metadata(entry: Any) -> str | None:
    key = dig(entry, "selector", "metadata")
    return key if isinstance(key, str) else None


@dataclass
class _Target:
    path: Path
    data: dict
    vtype: str
    needed: set[str] = field(default_factory=set)


@dataclass
class ColorReport:
    changes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    written: list[Path] = field(default_factory=list)


@dataclass
class ColorOptions:
    measure: str = "c-Measure Color"
    host_table: str = "w-Colors"
    default_color_id: int = 9
    visual_types: tuple[str, ...] = BAR_TYPES + TABLE_TYPES
    min_series: int = 2
    all_visuals: bool = False


def _visuals(report: Path) -> Iterable[tuple[Path, dict]]:
    for path in sorted((report / "definition" / "pages").glob("*/visuals/*/visual.json")):
        data = read_json(path)
        if isinstance(data, dict):
            yield path, data


def _uses_picker(data: dict, picker: str) -> bool:
    state = dig(data, "visual", "query", "queryState") or {}
    for block in state.values() if isinstance(state, dict) else []:
        for param in dig(block, "fieldParameters") or []:
            if dig(param, "parameterExpr", "Column", "Expression", "SourceRef", "Entity") == picker:
                return True
        for projection in dig(block, "projections") or []:
            if dig(projection, "field", "Column", "Expression", "SourceRef", "Entity") == picker:
                return True
    return False


def _bookmark_needs(
    bookmarks: list[Bookmark], registry: dict[str, int], palette: Palette,
    opts: ColorOptions, report: ColorReport,
) -> dict[str, set[str]]:
    """visual id -> keys a multi-series bookmark shows on it."""
    needs: dict[str, set[str]] = {}
    for bookmark in bookmarks:
        for section in bookmark.sections.values():
            for cid, container in bookmark.containers(section).items():
                single = dig(container, "singleVisual")
                if dig(single, "visualType") not in BAR_TYPES:
                    continue
                series = _measure_keys(dig(single, "projections", "Y"))
                if len(series) < opts.min_series:
                    continue
                known = [k for k in series if k in registry]
                for key in series:
                    if key not in registry:
                        report.notes.append(
                            f"bookmark {bookmark.display_name!r}: {key} is not a row of "
                            f"{palette.picker!r}, so it has no palette colour")
                colours: dict[str, str] = {}
                for key in known:
                    colour = palette.colour(registry[key])
                    if colour in colours:
                        report.notes.append(
                            f"bookmark {bookmark.display_name!r}: {colours[colour]} and "
                            f"{key} share colour {colour} on {cid}")
                    colours.setdefault(colour, key)
                needs.setdefault(cid, set()).update(known)
    return needs


def _targets(report_dir: Path, registry: dict[str, int], palette: Palette,
             opts: ColorOptions, report: ColorReport) -> list[_Target]:
    needs = _bookmark_needs(load_bookmarks(report_dir), registry, palette, opts, report)
    targets = []
    for path, data in _visuals(report_dir):
        vtype = dig(data, "visual", "visualType")
        vid = data.get("name") if isinstance(data.get("name"), str) else path.parent.name
        uses = _uses_picker(data, palette.picker)
        supported = vtype in opts.visual_types and (vtype in BAR_TYPES or vtype in TABLE_TYPES)
        if uses and not supported:
            report.notes.append(f"{vid}: {vtype} uses {palette.picker!r} but is not supported")
            continue
        if not supported:
            continue
        in_scope = (
            opts.all_visuals
            or vid in needs
            or (vtype in TABLE_TYPES and uses)
        )
        if not in_scope:
            continue
        target = _Target(path, data, vtype)
        state = dig(data, "visual", "query", "queryState") or {}
        if vtype in BAR_TYPES:
            line = set(_measure_keys(dig(state, "Y2", "projections")))
            base = _measure_keys(dig(state, "Y", "projections"))
            target.needed = {k for k in base if k in registry} | needs.get(vid, set())
            target.needed -= line
        else:
            projected = set(_measure_keys(dig(state, "Values", "projections")))
            if any(dig(p, "field", "Column", "Expression", "SourceRef", "Entity") == palette.picker
                   for p in dig(state, "Values", "projections") or []):
                projected |= set(registry)
            target.needed = ({k for k in projected if k in registry} or needs.get(vid, set()))
        targets.append(target)
    return targets


def _sync_bar(entries: list, needed: set[str], colour_of) -> list:
    out = copy.deepcopy(entries)
    seen = set()
    for entry in out:
        key = _metadata(entry)
        if key in needed:
            entry.setdefault("properties", {})["fill"] = _literal_colour(colour_of(key))
            seen.add(key)
    for key in sorted(needed - seen):
        out.append({"properties": {"fill": _literal_colour(colour_of(key))},
                    "selector": {"metadata": key}})
    return out


def _table_props(colour: str, existing: dict | None = None) -> dict:
    props = dict(existing or {})
    props["fontColor"] = _literal_colour(colour)
    for flag in ("styleValues", "styleHeader", "styleTotal"):
        props[flag] = _true()
    return props


def _sync_table(entries: list, needed: set[str], registry: dict[str, int], colour_of) -> list:
    out = copy.deepcopy(entries)
    seen = set()
    for entry in out:
        key = _metadata(entry)
        if key in registry:
            colour = colour_of(key) if key in needed else BLACK
            entry["properties"] = _table_props(colour, entry.get("properties"))
            seen.add(key)
    for key in sorted(needed - seen):
        out.append({"properties": _table_props(colour_of(key)), "selector": {"metadata": key}})
    return out


def sync(report_dir: Path, model_dir: Path, opts: ColorOptions, apply: bool) -> ColorReport:
    model = SemanticModel.load(model_dir)
    palette = parse_palette(model, opts.measure, opts.host_table)
    registry = picker_registry(model, palette.picker)
    report = ColorReport()

    def colour_of(key: str) -> str:
        return palette.colour(registry[key])

    dirty: dict[Path, dict] = {}
    targets = _targets(report_dir, registry, palette, opts, report)
    for target in targets:
        objects = target.data.setdefault("visual", {}).setdefault("objects", {})
        card = "dataPoint" if target.vtype in BAR_TYPES else "columnFormatting"
        before = objects.get(card) or []
        if target.vtype in BAR_TYPES:
            after = _sync_bar(before, target.needed, colour_of)
        else:
            after = _sync_table(before, target.needed, registry, colour_of)
        if after != before:
            objects[card] = after
            dirty[target.path] = target.data
            report.changes.append(
                f"{target.path.parent.name}: {card} for {', '.join(sorted(target.needed))}")
    by_id = {t.data.get("name"): t for t in targets}
    for bookmark in load_bookmarks(report_dir):
        touched = False
        for section in bookmark.sections.values():
            for cid, container in bookmark.containers(section).items():
                target = by_id.get(cid)
                merge = dig(container, "singleVisual", "objects", "merge")
                if target is None or not isinstance(merge, dict):
                    continue
                card = "dataPoint" if target.vtype in BAR_TYPES else "columnFormatting"
                if not isinstance(merge.get(card), list):
                    continue
                for entry in merge[card]:
                    key = _metadata(entry)
                    if key not in target.needed:
                        continue
                    props = entry.setdefault("properties", {})
                    new = (_literal_colour(colour_of(key)) if card == "dataPoint" else None)
                    if card == "dataPoint" and props.get("fill") != new:
                        props["fill"] = new
                        touched = True
                    elif card == "columnFormatting":
                        updated = _table_props(colour_of(key), props)
                        if updated != props:
                            entry["properties"] = updated
                            touched = True
        if touched:
            dirty[bookmark.path] = bookmark.data
            report.changes.append(f"bookmark {bookmark.display_name!r}: overrides")
    _write(dirty, apply, report)
    return report


def reset(report_dir: Path, model_dir: Path, opts: ColorOptions, apply: bool) -> ColorReport:
    model = SemanticModel.load(model_dir)
    palette = parse_palette(model, opts.measure, opts.host_table)
    owned = palette.colours | {BLACK}
    report = ColorReport()
    dirty: dict[Path, dict] = {}
    for path, data in _visuals(report_dir):
        vtype = dig(data, "visual", "visualType")
        objects = dig(data, "visual", "objects")
        if not isinstance(objects, dict):
            continue
        changed = False
        if vtype in BAR_TYPES and isinstance(objects.get("dataPoint"), list):
            for entry in objects["dataPoint"]:
                fill = dig(entry, "properties", "fill")
                if _metadata(entry) and _owned_colour(fill) in owned:
                    entry["properties"]["fill"] = _theme_colour(opts.default_color_id)
                    changed = True
        if vtype in TABLE_TYPES and isinstance(objects.get("columnFormatting"), list):
            kept = []
            for entry in objects["columnFormatting"]:
                props = dig(entry, "properties")
                if _metadata(entry) and isinstance(props, dict) \
                        and _owned_colour(props.get("fontColor")) in owned:
                    props = {k: v for k, v in props.items() if k not in _TABLE_OWNED}
                    changed = True
                    if not props:
                        continue
                    entry = {**entry, "properties": props}
                kept.append(entry)
            if changed:
                if kept:
                    objects["columnFormatting"] = kept
                else:
                    objects.pop("columnFormatting")
        if changed:
            dirty[path] = data
            report.changes.append(f"{path.parent.name}: palette colours reverted")
    _write(dirty, apply, report)
    return report


def _write(dirty: dict[Path, dict], apply: bool, report: ColorReport) -> None:
    if not apply:
        return
    for path, data in dirty.items():
        if rewrite_json(path, data):
            report.written.append(path)
