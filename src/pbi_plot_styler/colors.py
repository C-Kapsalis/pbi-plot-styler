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

Exit codes (set by the CLI): 0 written or nothing to do, 1 a dry run found
changes, 2 when the palette or the picker cannot be read (nothing is
written).
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

from . import qx
from .canvas import Bookmark, dig, load_bookmarks, read_json
from .rules import rewrite_json
from .tmdl import SemanticModel, strip_dax_comments

BAR_TYPES = (
    "barChart", "columnChart", "clusteredColumnChart", "stackedColumnChart", "hundredPercentStackedColumnChart",
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
#: ``MOD ( <first argument>, <modulus> ) + <base>``; the first argument is
#: then read by :data:`_ORDER_TERM`.
_MOD = re.compile(r"MOD\s*\(\s*([^,()]+?)\s*,\s*(\d+)\s*\)\s*\+\s*(-?\d+)", re.IGNORECASE)
#: ``<variable>``, ``<variable> + n`` or ``<variable> - n``.
_ORDER_TERM = re.compile(r"[A-Za-z_][\w.]*(?:\s*([+-])\s*(\d+))?")
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
    term = _ORDER_TERM.fullmatch(mod.group(1).strip())
    if not term:
        raise PaletteError(
            f"[{measure}]: cannot read the slot offset from MOD({mod.group(1).strip()}, ...); "
            f"write the first argument as <order>, <order> + n or <order> - n")
    sign, amount = term.groups()
    offset = int(amount or 0) * (-1 if sign == "-" else 1)
    modulus, base = int(mod.group(2)), int(mod.group(3))
    # colours keep the palette's spelling; only reset compares case-insensitively
    slots = {int(n): colour for n, colour in _SLOT.findall(body)}
    if modulus <= 0 or len(slots) != modulus:
        raise PaletteError(
            f"[{measure}]: MOD cycles through {modulus} slot(s) but the SWITCH "
            f"lists {len(slots)} colour(s); give exactly one colour per slot"
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
#: query roles whose field parameter makes a visual "use" the picker:
#: the columns, the line and the matrix values.
VALUE_ROLES = ("Y", "Y2", "Values")


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


def _is_true(prop: Any) -> bool:
    return dig(prop, "expr", "Literal", "Value") == "true"


def _owned_colour(prop: Any) -> str | None:
    value = dig(prop, "solid", "color", "expr", "Literal", "Value")
    return value.strip("'").lower() if isinstance(value, str) else None


def _metadata(entry: Any) -> str | None:
    key = dig(entry, "selector", "metadata")
    return key if isinstance(key, str) else None


def _card(vtype: str | None) -> str | None:
    """The array a visual type's colours live in."""
    if vtype in BAR_TYPES:
        return "dataPoint"
    if vtype in TABLE_TYPES:
        return "columnFormatting"
    return None


@dataclass
class _Target:
    path: Path
    data: dict
    vtype: str
    page: str
    vid: str
    #: measures whose colour the visual itself carries.
    needed: set[str] = field(default_factory=set)
    #: measures a bookmark override of this visual carries.
    override_needed: set[str] = field(default_factory=set)


@dataclass
class ColorReport:
    changes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)
    written: list[Path] = field(default_factory=list)
    rewritten: int = 0
    added: int = 0


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


def _identity(path: Path, data: dict) -> tuple[str, str]:
    """``(page section, visual id)`` of a visual file."""
    vid = data.get("name") if isinstance(data.get("name"), str) else path.parent.name
    return path.parent.parent.parent.name, vid


def _uses_picker(visual: dict, picker: str) -> bool:
    """A value role (columns, line or values) carries the picker as a field parameter."""
    roles = dig(visual, "visual", "query", "queryState")
    if not isinstance(roles, dict):
        return False
    for role in VALUE_ROLES:
        for param in dig(roles, role, "fieldParameters") or []:
            if dig(param, "parameterExpr", "Column", "Expression", "SourceRef", "Entity") == picker:
                return True
    return False


def _multi_series(bookmarks: list[Bookmark], opts: ColorOptions):
    """``(bookmark, section id, container id, single)`` of each multi-series capture."""
    for bookmark in bookmarks:
        for section_id, section in bookmark.sections.items():
            for cid, container in bookmark.containers(section).items():
                single = dig(container, "singleVisual")
                if dig(single, "visualType") not in BAR_TYPES:
                    continue
                if len(_measure_keys(dig(single, "projections", "Y"))) < opts.min_series:
                    continue
                yield bookmark, section_id, cid, single


def _bookmark_needs(
    bookmarks: list[Bookmark], registry: dict[str, int], palette: Palette,
    opts: ColorOptions, report: ColorReport,
) -> dict[tuple[str, str], set[str]]:
    """(page section, visual id) -> keys a multi-series bookmark shows on it.

    Every series of such a capture (columns, line and values) is listed with
    its role, sort order and colour; unregistered series and series sharing
    a colour are reported.
    """
    needs: dict[tuple[str, str], set[str]] = {}
    collided = False
    for bookmark, section_id, cid, single in _multi_series(bookmarks, opts):
        report.info.append(f"bookmark {bookmark.display_name!r} on {cid}:")
        colours: dict[str, str] = {}
        for role in VALUE_ROLES:
            for key in _measure_keys(dig(single, "projections", role)):
                if key not in registry:
                    report.info.append(f"  {role:<6} {key}: not registered, no palette colour")
                    report.notes.append(
                        f"bookmark {bookmark.display_name!r}: {key} is not a row of "
                        f"{palette.picker!r}, so it has no palette colour")
                    continue
                colour = palette.colour(registry[key])
                report.info.append(f"  {role:<6} {key}: order {registry[key]}, colour {colour}")
                if colour.lower() in colours and colours[colour.lower()] != key:
                    collided = True
                    report.notes.append(
                        f"bookmark {bookmark.display_name!r}: {colours[colour.lower()]} and "
                        f"{key} share colour {colour} on {cid}")
                colours.setdefault(colour.lower(), key)
        known = [k for k in _measure_keys(dig(single, "projections", "Y")) if k in registry]
        needs.setdefault((section_id, cid), set()).update(known)
    if collided:
        report.notes.append(
            f"hint: re-space the sort order of {palette.picker!r} (or add palette slots) so "
            f"measures shown together land on different slots")
    return needs


def _targets(report_dir: Path, registry: dict[str, int], palette: Palette,
             opts: ColorOptions, report: ColorReport) -> list[_Target]:
    needs = _bookmark_needs(load_bookmarks(report_dir), registry, palette, opts, report)
    targets = []
    for path, data in _visuals(report_dir):
        vtype = dig(data, "visual", "visualType")
        if vtype not in opts.visual_types:
            continue  # the visual-type filter comes first, silently
        page, vid = _identity(path, data)
        uses = _uses_picker(data, palette.picker)
        bookmarked = (page, vid) in needs
        in_scope = opts.all_visuals or bookmarked or (vtype in TABLE_TYPES and uses)
        if _card(vtype) is None:
            if in_scope or uses:
                report.notes.append(f"{vid}: {vtype} uses {palette.picker!r} but is not supported")
            continue
        if not in_scope:
            continue
        target = _Target(path, data, vtype, page, vid)
        state = dig(data, "visual", "query", "queryState") or {}
        extra = needs.get((page, vid), set())
        if vtype in BAR_TYPES:
            line = set(_measure_keys(dig(state, "Y2", "projections")))
            base = {k for k in _measure_keys(dig(state, "Y", "projections")) if k in registry}
            target.override_needed = base | extra
            target.needed = target.override_needed - line
        else:
            if uses:
                projected = _measure_keys(dig(state, "Values", "projections"))
                target.needed = {k for k in projected if k in registry}
            else:
                target.needed = set(extra)
            target.override_needed = set(target.needed)
        targets.append(target)
    return targets


def _sync_bar(entries: list, needed: set[str], colour_of, counts: list[int]) -> list:
    out = copy.deepcopy(entries)
    seen = set()
    for entry in out:
        key = _metadata(entry)
        if key in needed:
            props = entry.setdefault("properties", {})
            fill = _literal_colour(colour_of(key))
            if props.get("fill") != fill:
                props["fill"] = fill
                counts[0] += 1
            seen.add(key)
    for key in sorted(needed - seen):
        out.append({"properties": {"fill": _literal_colour(colour_of(key))},
                    "selector": {"metadata": key}})
        counts[1] += 1
    return out


def _table_props(colour: str, existing: dict | None = None) -> dict:
    props = dict(existing or {})
    props["fontColor"] = _literal_colour(colour)
    for flag in ("styleValues", "styleHeader", "styleTotal"):
        props[flag] = _true()
    return props


def _sync_table(entries: list, needed: set[str], registry: dict[str, int], colour_of,
                counts: list[int]) -> list:
    out = copy.deepcopy(entries)
    seen = set()
    for entry in out:
        key = _metadata(entry)
        if key in registry:
            colour = colour_of(key) if key in needed else BLACK
            props = _table_props(colour, entry.get("properties"))
            if props != entry.get("properties"):
                entry["properties"] = props
                counts[0] += 1
            seen.add(key)
    for key in sorted(needed - seen):
        out.append({"properties": _table_props(colour_of(key)), "selector": {"metadata": key}})
        counts[1] += 1
    return out


def _override_holder(single: Any) -> dict | None:
    """The node a bookmark capture keeps its formatting overrides in.

    Normally ``objects.merge``; without that wrapper, ``objects`` itself.
    """
    objects = dig(single, "objects")
    if not isinstance(objects, dict):
        return None
    merge = objects.get("merge")
    return merge if isinstance(merge, dict) else objects


def sync(report_dir: Path, model_dir: Path, opts: ColorOptions, apply: bool) -> ColorReport:
    model = SemanticModel.load(model_dir)
    palette = parse_palette(model, opts.measure, opts.host_table)
    registry = picker_registry(model, palette.picker)
    report = ColorReport()
    report.info.append(
        f"palette: picker {palette.picker!r}, offset {palette.offset}, modulus "
        f"{palette.modulus}, {len(palette.slots)} slot(s); {len(registry)} registered "
        f"measure(s)")

    def colour_of(key: str) -> str:
        return palette.colour(registry[key])

    dirty: dict[Path, dict] = {}
    counts = [0, 0]
    targets = _targets(report_dir, registry, palette, opts, report)
    for target in targets:
        objects = target.data.setdefault("visual", {}).setdefault("objects", {})
        card = _card(target.vtype)
        before = objects.get(card) or []
        if card == "dataPoint":
            after = _sync_bar(before, target.needed, colour_of, counts)
        else:
            after = _sync_table(before, target.needed, registry, colour_of, counts)
        if after != before:
            objects[card] = after
            dirty[target.path] = target.data
            report.changes.append(
                f"{target.vid}: {card} for {', '.join(sorted(target.needed)) or '(none needed)'}")
    by_id = {(t.page, t.vid): t for t in targets}
    for bookmark in load_bookmarks(report_dir):
        touched = False
        for section_id, section in bookmark.sections.items():
            for cid, container in bookmark.containers(section).items():
                target = by_id.get((section_id, cid))
                single = dig(container, "singleVisual")
                holder = _override_holder(single)
                if target is None or holder is None:
                    continue
                card = _card(dig(single, "visualType")) or _card(target.vtype)
                entries = holder.get(card)
                if not isinstance(entries, list):
                    continue  # an override array is never created
                if card == "dataPoint":
                    after = _sync_bar(entries, target.override_needed, colour_of, counts)
                else:
                    after = _sync_table(entries, target.override_needed, registry, colour_of,
                                        counts)
                if after != entries:
                    holder[card] = after
                    touched = True
        if touched:
            dirty[bookmark.path] = bookmark.data
            report.changes.append(f"bookmark {bookmark.display_name!r}: overrides")
    report.rewritten, report.added = counts
    _write(dirty, apply, report)
    return report


def _revert_entries(entries: list, card: str, registry: dict[str, int], owned: set[str],
                    opts: ColorOptions) -> tuple[list | None, bool]:
    """Revert the palette colours of registered measures in one array.

    Returns the new array (``None`` when it ends up empty) and whether
    anything changed.
    """
    changed = False
    kept = []
    for entry in copy.deepcopy(entries):
        key = _metadata(entry)
        props = dig(entry, "properties")
        if key not in registry or not isinstance(props, dict):
            kept.append(entry)
            continue
        if card == "dataPoint":
            if _owned_colour(props.get("fill")) in owned:
                props["fill"] = _theme_colour(opts.default_color_id)
                changed = True
            kept.append(entry)
            continue
        if _owned_colour(props.get("fontColor")) not in owned:
            kept.append(entry)
            continue
        props = {k: v for k, v in props.items()
                 if k != "fontColor" and not (k in _TABLE_OWNED and _is_true(v))}
        changed = True
        if props:
            entry["properties"] = props
            kept.append(entry)
    return (kept or None), changed


def reset(report_dir: Path, model_dir: Path, opts: ColorOptions, apply: bool) -> ColorReport:
    model = SemanticModel.load(model_dir)
    palette = parse_palette(model, opts.measure, opts.host_table)
    registry = picker_registry(model, palette.picker)
    owned = palette.colours | {BLACK}
    report = ColorReport()
    dirty: dict[Path, dict] = {}
    types: dict[tuple[str, str], str] = {}
    for path, data in _visuals(report_dir):
        vtype = dig(data, "visual", "visualType")
        types[_identity(path, data)] = vtype
        if vtype not in opts.visual_types:
            continue
        objects = dig(data, "visual", "objects")
        card = _card(vtype)
        if card is None or not isinstance(objects, dict) or not isinstance(objects.get(card), list):
            continue
        after, changed = _revert_entries(objects[card], card, registry, owned, opts)
        if changed:
            if after is None:
                objects.pop(card)
            else:
                objects[card] = after
            dirty[path] = data
            report.changes.append(f"{_identity(path, data)[1]}: palette colours reverted")
    for bookmark in load_bookmarks(report_dir):
        touched = False
        for section_id, section in bookmark.sections.items():
            for cid, container in bookmark.containers(section).items():
                single = dig(container, "singleVisual")
                vtype = dig(single, "visualType") or types.get((section_id, cid))
                if vtype not in opts.visual_types:
                    continue
                card = _card(vtype)
                holder = _override_holder(single)
                if card is None or holder is None or not isinstance(holder.get(card), list):
                    continue
                after, changed = _revert_entries(holder[card], card, registry, owned, opts)
                if changed:
                    if after is None:
                        holder.pop(card)
                    else:
                        holder[card] = after
                    touched = True
        if touched:
            dirty[bookmark.path] = bookmark.data
            report.changes.append(f"bookmark {bookmark.display_name!r}: overrides reverted")
    _write(dirty, apply, report)
    return report


def _write(dirty: dict[Path, dict], apply: bool, report: ColorReport) -> None:
    if not apply:
        return
    for path, data in dirty.items():
        if rewrite_json(path, data):
            report.written.append(path)
