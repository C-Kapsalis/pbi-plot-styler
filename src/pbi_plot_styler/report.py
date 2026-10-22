"""Restyle combo-chart formatting inside a PBIP report from a measure list.

For every targeted visual the styler owns a narrow slice of two arrays under
``visual.objects`` in ``visual.json``, and nothing else:

``dataPoint[]``
    The ``selector.metadata = "<Table>.<Measure>"`` entry of every measure it
    styles: the series ``fill`` (line and columns alike).

``labels[]``
    The same per-measure entries: ``backgroundColor`` (and
    ``backgroundTransparency`` when absent or explicitly configured). Plus a
    no-selector default entry that carries ``enableBackground: true``,
    without which Power BI ignores every per-measure background. It is
    seeded only when the visual has none.

Everything else in those arrays is preserved verbatim and in order: the
no-selector defaults (the column render baseline, often hand-tuned),
``selector.data`` entries (per legend value, for example ``showSeries:
false``), and the metadata entries of measures excluded from styling (the
measures drawn as columns). Inside an owned entry, only the owned
properties change; hand-tuned siblings survive. The rebuilt layout is::

    [defaults] + [excluded metadata] + [styled metadata] + [data-scoped]

Metadata entries for measures that are neither styled nor excluded (renamed
or retired measures) are dropped, so stale formatting heals. Styled entries
are sorted by key, so the operation is deterministic and idempotent:
re-running on an already-styled report is a byte-for-byte no-op.
"""
from __future__ import annotations

import copy
import difflib
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Mapping

from .config import Color, StylerConfig, ThemeColor
from .tmdl import SemanticModel
from .textio import BOM, decode, load_json

JSON_INDENT = 2

#: Properties the styler owns inside a no-selector ``labels[]`` entry.
_LABEL_DEFAULT_OWNED = ("show", "color", "enableBackground")


class RestyleInvariantError(RuntimeError):
    """A rebuilt visual altered an entry the styler must preserve.

    Raised instead of writing anything, so a regression in the merge logic
    can never silently destroy hand-made formatting.
    """


# -- JSON building blocks ----------------------------------------------------
def _literal(value: str) -> dict:
    return {"expr": {"Literal": {"Value": value}}}


def _solid_color(color: Color) -> dict:
    if isinstance(color, ThemeColor):
        percent = color.percent
        if isinstance(percent, float) and percent.is_integer():
            percent = int(percent)
        return {
            "solid": {
                "color": {
                    "expr": {
                        "ThemeDataColor": {
                            "ColorId": color.color_id,
                            "Percent": percent,
                        }
                    }
                }
            }
        }
    # Power BI encodes literal colors as a quoted string literal expression.
    return {"solid": {"color": _literal(f"'{color}'")}}


def datapoint_entry(
    measure_key: str, color: Color, existing: dict | None = None
) -> dict:
    """A ``dataPoint[]`` entry: series fill for one measure.

    Merges into ``existing`` (the visual's current entry for the same
    measure), so sibling properties set by hand, such as a
    ``fillTransparency``, survive.
    """
    props = dict((existing or {}).get("properties") or {})
    props["fill"] = _solid_color(color)
    return {"properties": props, "selector": {"metadata": measure_key}}


def labels_default_entry(config: StylerConfig) -> dict:
    """The no-selector ``labels[]`` entry seeded when a visual has none.

    ``label_default_properties`` replaces the built-in property set.
    """
    if config.label_default_properties:
        return {
            "properties": {
                name: _literal(value) for name, value in config.label_default_properties
            }
        }
    return {
        "properties": {
            "show": _literal("true" if config.show_labels else "false"),
            "color": _solid_color(config.label_color),
            "enableBackground": _literal("true"),
        }
    }


def labels_entry(
    measure_key: str,
    background: Color,
    transparency: int,
    existing: dict | None = None,
    *,
    enforce_transparency: bool = True,
) -> dict:
    """A per-measure ``labels[]`` entry: label background color and opacity.

    Merges into ``existing``: ``backgroundColor`` is always set, every other
    property (a custom label ``color``, for example) is kept, and
    ``backgroundTransparency`` is only seeded when absent unless
    ``enforce_transparency`` is set.
    """
    props = dict((existing or {}).get("properties") or {})
    props["backgroundColor"] = _solid_color(background)
    if enforce_transparency or "backgroundTransparency" not in props:
        props["backgroundTransparency"] = _literal(f"{transparency}L")
    return {"properties": props, "selector": {"metadata": measure_key}}


# -- entry classification ----------------------------------------------------
def _metadata_of(entry: dict) -> str | None:
    """The ``selector.metadata`` key of a pure metadata entry, else ``None``."""
    selector = entry.get("selector")
    if not isinstance(selector, dict) or set(selector) != {"metadata"}:
        return None
    key = selector["metadata"]
    return key if isinstance(key, str) else None


def _is_default(entry: dict) -> bool:
    return not entry.get("selector")


def _split(entries: Iterable[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """``(defaults, metadata_entries, other)`` in their original order.

    ``other`` holds every entry that is neither a no-selector default nor a
    pure ``selector.metadata`` entry: ``selector.data`` (per legend value)
    entries and any selector shape this tool does not know. They are never
    rewritten.
    """
    defaults, metadata, other = [], [], []
    for entry in entries:
        if not isinstance(entry, dict):
            other.append(entry)
        elif _is_default(entry):
            defaults.append(entry)
        elif _metadata_of(entry) is not None:
            metadata.append(entry)
        else:
            other.append(entry)
    return defaults, metadata, other


def _rebuild_card(
    existing: list | None,
    styled: list[str],
    excluded: set[str],
    build_entry,
) -> tuple[list, list, list, list]:
    """Split one ``objects`` array for rebuilding. Returns ``(defaults,
    excluded_entries, owned_entries, other)``: everything except
    ``owned_entries`` exactly as found in the input."""
    defaults, metadata, other = _split(existing or [])
    excluded_entries = [e for e in metadata if _metadata_of(e) in excluded]
    # duplicates of one key collapse into one entry, merged from the last
    previous: dict[str, dict] = {}
    for entry in metadata:
        previous[_metadata_of(entry)] = entry
    owned = [build_entry(key, previous.get(key)) for key in styled]
    return defaults, excluded_entries, owned, other


def _strip_owned(entry: dict, owned: Iterable[str]) -> dict:
    props = {
        k: v
        for k, v in (entry.get("properties") or {}).items()
        if k not in owned
    }
    return {**entry, "properties": props}


def restyle_visual(
    visual_data: dict,
    measure_keys: list[str],
    config: StylerConfig,
    *,
    excluded: Iterable[str] = (),
    slots: Mapping[str, int] | None = None,
) -> dict:
    """Return a deep copy of ``visual_data`` with its owned formatting rebuilt.

    ``measure_keys`` are the field-parameter measures; those in ``excluded``
    (measures this visual draws as columns) are not styled, and their
    existing metadata entries are preserved verbatim. ``slots`` maps each key
    to its stable palette slot; when omitted, the sorted index is used.
    """
    excluded_set = set(excluded)
    styled = sorted(k for k in set(measure_keys) if k not in excluded_set)
    if slots is None:
        slots = {k: i for i, k in enumerate(sorted(set(measure_keys)))}

    def slot(key: str) -> int:
        return slots.get(key, 0)

    data = copy.deepcopy(visual_data)
    objects = data.setdefault("visual", {}).setdefault("objects", {})
    original = (visual_data.get("visual") or {}).get("objects") or {}

    # dataPoint: never invent a default; a visual without one keeps its
    # columns exactly as they are.
    dp_defaults, dp_excluded, dp_owned, dp_other = _rebuild_card(
        original.get("dataPoint"),
        styled,
        excluded_set,
        lambda key, prev: datapoint_entry(key, config.series_color(key, slot(key)), prev),
    )
    objects["dataPoint"] = dp_defaults + dp_excluded + dp_owned + dp_other

    enforce_transparency = "label_transparency" in config.explicit
    transparency = (config.label_transparency if enforce_transparency
                    or config.label_transparency_seed is None
                    else config.label_transparency_seed)
    lb_defaults, lb_excluded, lb_owned, lb_other = _rebuild_card(
        original.get("labels"),
        styled,
        excluded_set,
        lambda key, prev: labels_entry(
            key,
            config.label_background_for(key, slot(key)),
            transparency,
            prev,
            enforce_transparency=enforce_transparency,
        ),
    )
    if lb_defaults and not config.touch_existing_label_default:
        new_defaults = copy.deepcopy(lb_defaults)
    elif lb_defaults:
        new_defaults = []
        for entry in lb_defaults:
            entry = copy.deepcopy(entry)
            props = entry.setdefault("properties", {})
            props["enableBackground"] = _literal("true")
            if "show_labels" in config.explicit:
                props["show"] = _literal("true" if config.show_labels else "false")
            if "label_color" in config.explicit:
                props["color"] = _solid_color(config.label_color)
            new_defaults.append(entry)
    else:
        new_defaults = [labels_default_entry(config)]
    objects["labels"] = new_defaults + lb_excluded + lb_owned + lb_other

    _assert_preserved(original, objects, excluded_set)
    return data


def _assert_preserved(original: dict, rebuilt: dict, excluded: set[str]) -> None:
    """Every entry the styler does not own must survive verbatim, in order."""
    for card in ("dataPoint", "labels"):
        before_defaults, before_meta, before_other = _split(original.get(card) or [])
        after_defaults, after_meta, after_other = _split(rebuilt.get(card) or [])
        if after_other != before_other:
            raise RestyleInvariantError(
                f"{card}: selector.data (or other non-metadata) entries were "
                f"altered or dropped ({len(before_other)} -> {len(after_other)})"
            )
        if card == "dataPoint":
            defaults_ok = after_defaults == before_defaults
        else:
            defaults_ok = not before_defaults or [
                _strip_owned(e, _LABEL_DEFAULT_OWNED) for e in after_defaults
            ] == [_strip_owned(e, _LABEL_DEFAULT_OWNED) for e in before_defaults]
        if not defaults_ok:
            raise RestyleInvariantError(
                f"{card}: a no-selector default entry was altered or dropped"
            )
        kept = [e for e in after_meta if _metadata_of(e) in excluded]
        if kept != [e for e in before_meta if _metadata_of(e) in excluded]:
            raise RestyleInvariantError(
                f"{card}: metadata entries of excluded measures were altered "
                f"or dropped"
            )


# -- query-state reading -----------------------------------------------------
def _query_state(visual_data: dict) -> dict:
    return (
        ((visual_data.get("visual") or {}).get("query") or {}).get("queryState")
        or {}
    )


def _source_entity(node: dict) -> str | None:
    return ((node.get("Expression") or {}).get("SourceRef") or {}).get("Entity")


def current_role_measure_key(visual_data: dict, role: str) -> str | None:
    """The ``"<Entity>.<Property>"`` key presently bound to a query role.

    Power BI's combo-chart roles are named ``Y`` (columns) and ``Y2``
    (line) internally. Returns the first measure projection of the role, or
    ``None`` if the visual has no query state, the role isn't present, or
    it projects no measure.
    """
    for projection in (_query_state(visual_data).get(role) or {}).get(
        "projections", []
    ):
        measure = (projection.get("field") or {}).get("Measure")
        if not measure:
            continue
        entity = _source_entity(measure)
        prop = measure.get("Property")
        if entity and prop:
            return f"{entity}.{prop}"
    return None


def _measure_keys_of(visual_data: dict, role: str) -> list[str]:
    """The measure keys a query role projects directly."""
    keys: list[str] = []
    for projection in (_query_state(visual_data).get(role) or {}).get(
        "projections", []
    ):
        measure = (projection.get("field") or {}).get("Measure")
        if not measure:
            continue
        entity, prop = _source_entity(measure), measure.get("Property")
        if entity and prop:
            keys.append(f"{entity}.{prop}")
    return keys


def role_measure_keys(
    visual_data: dict,
    role: str,
    catalogs: Mapping[str, list[str]] | None = None,
) -> set[str]:
    """Every measure a query role can draw on this visual.

    A direct ``Measure`` projection contributes its own key. A ``Column``
    projection on a field-parameter table (a role bound through a field
    parameter) contributes that table's whole measure catalog, looked up in
    ``catalogs`` (table name -> keys, matched case-insensitively), because
    any of those measures may be the one currently picked.
    """
    lowered = {t.lower(): keys for t, keys in (catalogs or {}).items()}
    keys: set[str] = set()
    for projection in (_query_state(visual_data).get(role) or {}).get(
        "projections", []
    ):
        fld = projection.get("field") or {}
        measure = fld.get("Measure")
        if measure:
            entity, prop = _source_entity(measure), measure.get("Property")
            if entity and prop:
                keys.add(f"{entity}.{prop}")
            continue
        column = fld.get("Column")
        if column:
            entity = _source_entity(column)
            if entity and entity.lower() in lowered:
                keys.update(lowered[entity.lower()])
    return keys


# -- stale line rebind ---------------------------------------------------------
_LEADING_JUNK = re.compile(r"^[^A-Za-z0-9]+")


@dataclass(frozen=True)
class Rebind:
    """One stale line projection pointed at the model's current measure."""

    entity: str
    old: str
    new: str


def _rebind_target(model: SemanticModel, entity: str, prop: str) -> str | None:
    table = model.table_named(entity)
    if table is None:
        return None  # not a model table: stale, but there is nothing to bind to
    measures = model.measures_by_table.get(table, set())
    if prop in measures:
        return None  # current
    stem = _LEADING_JUNK.sub("", prop).strip()
    if not stem:
        return None
    if stem in measures:
        return stem
    candidates = sorted(m for m in measures if stem.casefold() in m.casefold())
    return candidates[0] if len(candidates) == 1 else None


def rebind_stale_line(
    visual_data: dict, model: SemanticModel, line_role: str = "Y2"
) -> list[Rebind]:
    """Point stale ``Measure`` projections of the line role at current names.

    A projection is stale when its table does not declare a measure with
    exactly that name. The name is stripped of leading non-alphanumeric
    characters; an exact match wins, else a single case-insensitive
    substring match among the same table's measures. Edits ``visual_data``
    in place (``Property`` and ``queryRef`` only) and returns the rebinds.
    """
    done: list[Rebind] = []
    block = _query_state(visual_data).get(line_role) or {}
    for projection in block.get("projections") or []:
        measure = (projection.get("field") or {}).get("Measure") if isinstance(projection, dict) else None
        if not isinstance(measure, dict):
            continue
        entity, prop = _source_entity(measure), measure.get("Property")
        if not isinstance(entity, str) or not isinstance(prop, str):
            continue
        target = _rebind_target(model, entity, prop)
        if target is None:
            continue
        measure["Property"] = target
        query_ref = projection.get("queryRef")
        if isinstance(query_ref, str):
            projection["queryRef"] = query_ref.replace(f".{prop}", f".{target}")
        done.append(Rebind(entity, prop, target))
    return done


# -- report discovery ---------------------------------------------------------
def is_report_dir(path: Path) -> bool:
    return (path / "definition.pbir").is_file() or (
        path / "definition" / "pages"
    ).is_dir()


@dataclass(frozen=True)
class Discovery:
    """The report folders found under a path, plus the ones skipped."""

    reports: list[Path]
    skipped: list[tuple[Path, str]] = field(default_factory=list)
    #: True when the path itself was a report folder.
    single: bool = False


def discover_reports(path: Path) -> Discovery:
    """Resolve ``path`` to one or more PBIP report folders.

    ``path`` is either a ``*.Report`` folder itself, or any directory that
    contains one or more ``*.Report`` folders at any depth (a project
    folder, a monorepo subtree). Nested discovery uses a recursive search,
    so report trees kept in subfolders are never silently missed. A
    discovered folder without ``definition/pages`` (a legacy, non-PBIR
    report) is skipped and reported.
    """
    if is_report_dir(path):
        return Discovery(reports=[path], single=True)
    reports: list[Path] = []
    skipped: list[tuple[Path, str]] = []
    for candidate in sorted(path.rglob("*.Report")):
        if not candidate.is_dir():
            continue
        if any(parent in reports for parent in candidate.parents):
            continue
        if (candidate / "definition" / "pages").is_dir():
            reports.append(candidate)
        else:
            skipped.append(
                (candidate, "no definition/pages (not saved in PBIR format)")
            )
    return Discovery(reports=reports, skipped=skipped)


def resolve_model_dir(report_dir: Path) -> Path:
    """Locate the semantic model paired with a report via ``definition.pbir``."""
    pbir = report_dir / "definition.pbir"
    if not pbir.is_file():
        raise FileNotFoundError(
            f"{report_dir} has no definition.pbir, so the paired semantic "
            f"model cannot be resolved. Pass the model folder explicitly "
            f"with --model."
        )
    meta = load_json(pbir)
    rel = ((meta.get("datasetReference") or {}).get("byPath") or {}).get("path")
    if not rel:
        raise FileNotFoundError(
            f"{pbir} has no datasetReference.byPath.path, so the paired "
            f"semantic model cannot be resolved (the report may reference a "
            f"published dataset instead of a local folder). Pass the model "
            f"folder explicitly with --model."
        )
    return (report_dir / rel).resolve()


def report_model_name(report_dir: Path) -> str | None:
    """The ``<name>`` of the ``<name>.SemanticModel`` a report points at by
    path, or ``None`` (no pbir, malformed JSON, or a non-byPath reference)."""
    from .canvas import dig, read_json

    target = dig(read_json(report_dir / "definition.pbir"), "datasetReference", "byPath", "path")
    if not isinstance(target, str):
        return None
    folder = Path(target.replace("\\", "/").rstrip("/")).name
    stem, dot, kind = folder.rpartition(".")
    return stem if dot and kind == "SemanticModel" else None


def iter_visual_files(report_dir: Path) -> Iterator[Path]:
    """Every ``visual.json`` under the report's pages, in sorted order."""
    pages_dir = report_dir / "definition" / "pages"
    if not pages_dir.is_dir():
        raise FileNotFoundError(
            f"{report_dir} has no definition/pages directory, so it is not "
            f"a PBIP report folder. Pass the *.Report folder of a project "
            f"saved in PBIP format."
        )
    yield from sorted(pages_dir.rglob("visual.json"))


def enclosing_report(path: Path) -> Path | None:
    """The ``*.Report`` folder a page folder or visual file belongs to."""
    for parent in [path, *path.parents]:
        if parent.is_dir() and is_report_dir(parent) and parent != path:
            return parent
    return None


@dataclass(frozen=True)
class VisualChange:
    """One visual.json rewrite the styler plans to make."""

    path: Path
    old_text: str
    new_text: str
    rebinds: tuple[Rebind, ...] = ()
    bom: bool = False
    #: column-side measures left out of styling on this visual.
    excluded: tuple[str, ...] = ()
    #: per card: (entries before, entries after).
    counts: tuple[tuple[str, int, int], ...] = ()
    #: the measures this visual styles (the line set).
    styled: tuple[str, ...] = ()
    #: the column-side measures, including the ones the model declares but
    #: the field parameters do not offer.
    column_side: tuple[str, ...] = ()
    #: the no-selector and data-scoped entries the rebuild kept.
    bar_side: int = 0

    @property
    def changed(self) -> bool:
        return self.old_text != self.new_text

    def unified_diff(self, root: Path) -> str:
        rel = self.path.relative_to(root).as_posix()
        return "".join(
            difflib.unified_diff(
                self.old_text.splitlines(keepends=True),
                self.new_text.splitlines(keepends=True),
                fromfile=rel,
                tofile=f"{rel} (styled)",
            )
        )


def dump_visual(
    data: dict, *, trailing_newline: bool = True, newline: str = "\n"
) -> str:
    """Serialize a visual back the way PBIP tooling writes it.

    Power BI Desktop saves ``visual.json`` without a trailing newline and
    with LF line endings; hand-maintained files may differ. The caller
    passes whichever conventions the source file used so untouched bytes
    stay untouched.
    """
    text = json.dumps(data, indent=JSON_INDENT, ensure_ascii=False)
    if trailing_newline:
        text += "\n"
    return text.replace("\n", newline) if newline != "\n" else text


def _is_bar_side(entry: Any) -> bool:
    """A no-selector (the bar render baseline) or data-scoped (per legend
    value) entry: one the rebuild keeps rather than rewrites."""
    if not isinstance(entry, dict):
        return False
    selector = entry.get("selector")
    if not isinstance(selector, dict) or not selector:
        return True
    return "metadata" not in selector


def _bar_side_count(before: list, after: list, *, seed_default: bool) -> int:
    """The no-selector and data-scoped entries the rebuild kept.

    A no-selector default the base already had is not one of them; only a
    default the rebuild seeded counts (``seed_default``).
    """
    if seed_default:
        kept = sum(1 for entry in after
                   if isinstance(entry, dict) and entry.get("selector")
                   and "metadata" not in entry["selector"])
        if not any(isinstance(e, dict) and not e.get("selector") for e in before):
            kept += 1
        return kept
    return sum(1 for entry in after if _is_bar_side(entry))


def plan_changes(
    report_dir: Path,
    measure_keys: list[str],
    config: StylerConfig,
    *,
    catalogs: Mapping[str, list[str]] | None = None,
    slots: Mapping[str, int] | None = None,
    model: SemanticModel | None = None,
    within: Path | None = None,
    errors: list[tuple[Path, str]] | None = None,
) -> list[VisualChange]:
    """Compute the rewrite for every targeted visual (changed or not).

    ``catalogs`` (field-parameter table -> measure keys) lets an excluded
    role bound through a field parameter exclude that parameter's whole
    catalog; ``slots`` fixes each measure's palette slot. With
    ``config.rebind_stale_line`` (which needs ``model``), stale line
    projections are rebound first and the column role counts as column
    side unless excluded roles are configured. A visual file that does not
    parse is reported through ``errors`` and left alone.
    """
    roles = config.exclude_current_roles
    if config.rebind_stale_line and not roles:
        roles = (config.column_role,)
    changes: list[VisualChange] = []
    for visual_file in iter_visual_files(report_dir):
        if within is not None and visual_file != within and within not in visual_file.parents:
            continue
        # Read raw bytes so change detection is byte-accurate (no newline
        # translation on Windows).
        raw = visual_file.read_bytes()
        old_text = decode(raw)
        try:
            data = json.loads(old_text)
        except json.JSONDecodeError as exc:
            if errors is not None:
                errors.append((visual_file, str(exc)))
            continue
        if (data.get("visual") or {}).get("visualType") not in config.visual_types:
            continue
        source = data
        rebinds: list[Rebind] = []
        if config.rebind_stale_line and model is not None:
            source = copy.deepcopy(data)
            rebinds = rebind_stale_line(source, model, config.line_role)
        excluded: set[str] = set()
        for role in roles:
            excluded |= role_measure_keys(source, role, catalogs)
        new_data = restyle_visual(
            source, measure_keys, config, excluded=excluded, slots=slots
        )
        if new_data == data:
            new_text = old_text  # already in style: leave every byte alone
        else:
            new_text = dump_visual(
                new_data,
                trailing_newline=old_text.endswith("\n"),
                newline="\r\n" if "\r\n" in old_text else "\n",
            )
        before_objects = (data.get("visual") or {}).get("objects") or {}
        after_objects = (new_data.get("visual") or {}).get("objects") or {}
        counts = tuple((card, len(before_objects.get(card) or []),
                        len(after_objects.get(card) or [])) for card in ("dataPoint", "labels"))
        styled = sorted(set(measure_keys) - excluded)
        column_side = sorted(set(_measure_keys_of(source, config.column_role)) | excluded)
        bar_side = _bar_side_count(before_objects.get("dataPoint") or [],
                                   after_objects.get("dataPoint") or [],
                                   seed_default=False) + _bar_side_count(
            before_objects.get("labels") or [], after_objects.get("labels") or [],
            seed_default=True)
        changes.append(
            VisualChange(path=visual_file, old_text=old_text, new_text=new_text,
                         rebinds=tuple(rebinds), bom=raw.startswith(BOM),
                         excluded=tuple(sorted(excluded & set(measure_keys))),
                         counts=counts, styled=tuple(styled),
                         column_side=tuple(column_side), bar_side=bar_side)
        )
    return changes


def apply_changes(changes: list[VisualChange]) -> int:
    """Write every changed visual in place. Returns the number written."""
    written = 0
    for change in changes:
        if change.changed:
            # write_bytes, not write_text: text mode would rewrite every
            # line ending to os.linesep (CRLF on Windows), churning bytes
            # far outside the owned entries.
            change.path.write_bytes(
                (BOM if change.bom else b"") + change.new_text.encode("utf-8"))
            written += 1
    return written


def write_zip(
    report_dirs: Path | list[Path],
    changes: list[VisualChange],
    out_path: Path,
    *,
    base: Path | None = None,
) -> None:
    """Emit the styled report folder(s) as a zip archive.

    The archive always contains the *styled* content, even under
    ``--dry-run``: unchanged files are copied from disk, styled visuals are
    taken from the computed rewrites. Entries are named relative to
    ``base`` (default: the parent of the first report, so a single report
    is rooted at its own folder name).
    """
    if isinstance(report_dirs, Path):
        report_dirs = [report_dirs]
    if base is None:
        base = report_dirs[0].parent
    styled = {change.path: change.new_text for change in changes}
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for report_dir in report_dirs:
            for file in sorted(p for p in report_dir.rglob("*") if p.is_file()):
                arcname = file.relative_to(base).as_posix()
                if file in styled:
                    archive.writestr(arcname, styled[file].encode("utf-8"))
                else:
                    archive.write(file, arcname)
