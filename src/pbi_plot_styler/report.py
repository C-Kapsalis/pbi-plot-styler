"""Rebuild combo-chart formatting inside a PBIP report from a measure list.

For every targeted visual the styler wipes and regenerates two arrays under
``visual.objects`` in ``visual.json``:

``dataPoint[]``
    One entry per field-parameter measure, binding the series ``fill``
    (line and columns alike) to a literal hex color, selected via
    ``selector.metadata = "<Table>.<Measure>"``.

``labels[]``
    A leading no-selector entry that turns data labels on/off, sets the
    label text ``color``, and sets ``enableBackground: true`` (without which
    Power BI ignores every per-measure background), followed by one entry
    per measure binding ``backgroundColor`` and ``backgroundTransparency``.

Because both arrays are rebuilt from scratch off a sorted measure list, the
operation is deterministic and idempotent: renamed or removed measures heal
on the next run, and re-running on an already-styled report is a no-op.
"""
from __future__ import annotations

import copy
import difflib
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .config import StylerConfig

JSON_INDENT = 2


# -- JSON building blocks ----------------------------------------------------
def _literal(value: str) -> dict:
    return {"expr": {"Literal": {"Value": value}}}


def _solid_color(hex_color: str) -> dict:
    # Power BI encodes literal colors as a quoted string literal expression.
    return {"solid": {"color": _literal(f"'{hex_color}'")}}


def datapoint_entry(measure_key: str, line_hex: str) -> dict:
    """A ``dataPoint[]`` entry: series fill for one measure."""
    return {
        "properties": {"fill": _solid_color(line_hex)},
        "selector": {"metadata": measure_key},
    }


def labels_default_entry(config: StylerConfig) -> dict:
    """The no-selector ``labels[]`` entry that activates everything else."""
    return {
        "properties": {
            "show": _literal("true" if config.show_labels else "false"),
            "color": _solid_color(config.label_color),
            "enableBackground": _literal("true"),
        }
    }


def labels_entry(measure_key: str, background_hex: str, transparency: int) -> dict:
    """A per-measure ``labels[]`` entry: label background color and opacity."""
    return {
        "properties": {
            "backgroundColor": _solid_color(background_hex),
            "backgroundTransparency": _literal(f"{transparency}L"),
        },
        "selector": {"metadata": measure_key},
    }


def restyle_visual(
    visual_data: dict, measure_keys: list[str], config: StylerConfig
) -> dict:
    """Return a deep copy of ``visual_data`` with rebuilt formatting arrays."""
    data = copy.deepcopy(visual_data)
    objects = data.setdefault("visual", {}).setdefault("objects", {})
    objects["dataPoint"] = [
        datapoint_entry(key, config.line_color_for(i))
        for i, key in enumerate(measure_keys)
    ]
    objects["labels"] = [labels_default_entry(config)] + [
        labels_entry(key, config.label_background_for(i), config.label_transparency)
        for i, key in enumerate(measure_keys)
    ]
    return data


# -- report traversal ---------------------------------------------------------
def resolve_model_dir(report_dir: Path) -> Path:
    """Locate the semantic model paired with a report via ``definition.pbir``."""
    pbir = report_dir / "definition.pbir"
    if not pbir.is_file():
        raise FileNotFoundError(
            f"{report_dir} has no definition.pbir, so the paired semantic "
            f"model cannot be resolved. Pass the model folder explicitly "
            f"with --model."
        )
    meta = json.loads(pbir.read_text(encoding="utf-8"))
    rel = ((meta.get("datasetReference") or {}).get("byPath") or {}).get("path")
    if not rel:
        raise FileNotFoundError(
            f"{pbir} has no datasetReference.byPath.path, so the paired "
            f"semantic model cannot be resolved (the report may reference a "
            f"published dataset instead of a local folder). Pass the model "
            f"folder explicitly with --model."
        )
    return (report_dir / rel).resolve()


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


@dataclass(frozen=True)
class VisualChange:
    """One visual.json rewrite the styler plans to make."""

    path: Path
    old_text: str
    new_text: str

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


def dump_visual(data: dict, *, trailing_newline: bool = True) -> str:
    """Serialize a visual back the way PBIP tooling writes it.

    Power BI Desktop saves ``visual.json`` without a trailing newline;
    hand-maintained files often carry one. The caller passes whichever
    convention the source file used so untouched bytes stay untouched.
    """
    text = json.dumps(data, indent=JSON_INDENT, ensure_ascii=False)
    return text + "\n" if trailing_newline else text


def plan_changes(
    report_dir: Path, measure_keys: list[str], config: StylerConfig
) -> list[VisualChange]:
    """Compute the rewrite for every targeted visual (changed or not)."""
    changes: list[VisualChange] = []
    for visual_file in iter_visual_files(report_dir):
        # Read raw bytes so change detection is byte-accurate (no newline
        # translation on Windows).
        old_text = visual_file.read_bytes().decode("utf-8")
        try:
            data = json.loads(old_text)
        except json.JSONDecodeError:
            continue
        if (data.get("visual") or {}).get("visualType") not in config.visual_types:
            continue
        new_data = restyle_visual(data, measure_keys, config)
        changes.append(
            VisualChange(
                path=visual_file,
                old_text=old_text,
                new_text=dump_visual(
                    new_data, trailing_newline=old_text.endswith("\n")
                ),
            )
        )
    return changes


def apply_changes(changes: list[VisualChange]) -> int:
    """Write every changed visual in place. Returns the number written."""
    written = 0
    for change in changes:
        if change.changed:
            # write_bytes, not write_text: text mode would rewrite every
            # line ending to os.linesep (CRLF on Windows), churning bytes
            # far outside the two rebuilt arrays.
            change.path.write_bytes(change.new_text.encode("utf-8"))
            written += 1
    return written


def write_zip(
    report_dir: Path, changes: list[VisualChange], out_path: Path
) -> None:
    """Emit the styled report folder as a zip archive.

    The archive always contains the *styled* content, even under
    ``--dry-run``: unchanged files are copied from disk, styled visuals are
    taken from the computed rewrites.
    """
    styled = {change.path: change.new_text for change in changes}
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(p for p in report_dir.rglob("*") if p.is_file()):
            arcname = (Path(report_dir.name) / file.relative_to(report_dir)).as_posix()
            if file in styled:
                archive.writestr(arcname, styled[file])
            else:
                archive.write(file, arcname)
