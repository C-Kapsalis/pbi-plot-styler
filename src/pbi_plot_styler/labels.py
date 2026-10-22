"""``rename-label``: rename a field-parameter row's display text everywhere.

The first value of a field-parameter row is both what the slicer shows and
what a bookmark or filter stores when it remembers the pick. Renaming it in
the model alone leaves every remembered selection pointing at text that no
longer exists. This command replaces the label, always searched together
with its double quotes (``"OLD"``) so a longer label that merely contains it
is left alone, in the measure-selector tables of every model directly under
the client folder and in the pages, visuals and bookmarks of every report
below it.
"""
from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from .textio import read_text


class LabelRenameError(RuntimeError):
    """A replacement would corrupt a file; nothing was written."""


@dataclass
class LabelRenameResult:
    counts: list[tuple[str, str, int]] = field(default_factory=list)
    touched: list[Path] = field(default_factory=list)


_TABLE_DECL = re.compile(r"^table\s+(?:'((?:[^'\n]|'')+)'|\"([^\"\n]+)\"|(\S[^\n]*?))\s*$", re.MULTILINE)


def _table_name(path: Path, text: str) -> str:
    match = _TABLE_DECL.search(text)
    if not match:
        return path.stem
    single, double, bare = match.groups()
    return single.replace("''", "'") if single is not None else (double or bare or path.stem)


def label_files(client_dir: Path, patterns: tuple[str, ...] = ("x-*",)) -> list[Path]:
    """The TMDL and JSON files a row label can appear in."""
    files: list[Path] = []
    for model in sorted(client_dir.glob("*.SemanticModel")):
        for tmdl in sorted((model / "definition" / "tables").glob("*.tmdl")):
            name = _table_name(tmdl, read_text(tmdl))
            if any(fnmatch.fnmatchcase(name, p) for p in patterns):
                files.append(tmdl)
    for report in sorted(p for p in client_dir.rglob("*.Report") if p.is_dir()):
        definition = report / "definition"
        files += sorted(definition.glob("pages/*/visuals/*/visual.json"))
        files += sorted(definition.glob("bookmarks/*.bookmark.json"))
        files += sorted(definition.glob("pages/*/page.json"))
    return files


def rename_labels(
    client_dir: Path,
    pairs: list[tuple[str, str]],
    *,
    apply: bool,
    patterns: tuple[str, ...] = ("x-*",),
) -> LabelRenameResult:
    """Replace each quoted ``OLD`` with ``NEW``; the longest old label first."""
    ordered = sorted(pairs, key=lambda pair: len(pair[0]), reverse=True)
    result = LabelRenameResult()
    pending: dict[Path, tuple[bytes, str]] = {}
    totals = {old: 0 for old, _ in ordered}
    for path in label_files(client_dir, patterns):
        raw = path.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        text = raw.decode("utf-8-sig")
        original = text
        for old, new in ordered:
            # A quoted label that happens to sit in a JSON key position
            # (``"OLD":``) is a field name, not a value: rewrite the values
            # only, so a rename of a label such as "version" does not
            # corrupt object keys.
            pattern = re.compile(re.escape(f'"{old}"') + r"(?!\s*:)")
            hits = len(pattern.findall(text))
            if hits:
                totals[old] += hits
                text = pattern.sub(f'"{new}"', text)
        if text == original:
            continue
        if path.suffix == ".json":
            try:
                json.loads(text)
            except json.JSONDecodeError as exc:
                raise LabelRenameError(
                    f"replacing the label in {path.relative_to(client_dir).as_posix()} "
                    f"would leave invalid JSON ({exc}); nothing was written"
                ) from exc
        pending[path] = ((b"\xef\xbb\xbf" if bom else b""), text)
    result.counts = [(old, new, totals[old]) for old, new in ordered]
    result.touched = list(pending)  # visiting order: model tables first
    if apply:
        for path, (bom, text) in pending.items():
            path.write_bytes(bom + text.encode("utf-8"))
    return result
