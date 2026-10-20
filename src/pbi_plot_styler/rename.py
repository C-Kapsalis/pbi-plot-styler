"""Report-side measure rename: count and rewrite every reference to a measure.

When a measure is renamed in the model, the report must follow everywhere.
Some references break loudly (a field binding shows an error); others fail
silently (a bookmark that remembers a field-parameter pick by name restores
nothing). This module finds both kinds in ``visual.json`` and
``*.bookmark.json`` files.

Always rewritten (names compared case-insensitively):

* a ``Measure`` object whose ``Property`` is the old name (``Column`` objects
  are never touched, even when a column has the same name);
* a ``queryRef`` or ``metadata`` string ending in ``.<old>``;
* a ``nativeQueryRef`` equal to the old name;
* each ``[<old>]`` inside the ``Value`` string of a ``Literal`` object (a
  saved slicer selection).

Labels are rewritten only while they still read as the old label and some
sibling provably binds the measure, so a label someone customised stays:

* a cached display item (``id`` + ``displayName``) whose ``id`` holds a
  selection literal for the measure;
* a projection label (``displayName``) whose own ``nativeQueryRef`` or
  ``queryRef`` names the measure;
* a value map (``decomposedIdentities.values`` paired with ``valueMap`` by
  position).

Every decision is taken against the document as it was before the command
changed anything, and counting runs exactly the same decisions without
writing, so a dry-run count always equals the number of rewrites.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

from .textio import Layout, decode, dump_json

Edit = Callable[[], None]


class _Matcher:
    """Name tests for one rename, precomputed."""

    def __init__(self, old: str, old_label: str | None) -> None:
        self.old = old
        self.old_folded = old.casefold()
        self.label_folded = (old_label if old_label is not None else old).casefold()
        self.bracketed = re.compile(
            r"\[" + re.escape(literal_name(old)) + r"\]", re.IGNORECASE)

    def is_old(self, value: Any) -> bool:
        return isinstance(value, str) and value.casefold() == self.old_folded

    def is_old_label(self, value: Any) -> bool:
        return isinstance(value, str) and value.casefold() == self.label_folded

    def ends_with_old(self, value: Any) -> bool:
        if not isinstance(value, str) or "." not in value:
            return False
        head, _, tail = value.rpartition(".")
        if tail.casefold() == self.old_folded:
            return True
        # Measure names may themselves contain dots.
        suffix = "." + self.old_folded
        return value.casefold().endswith(suffix) and len(value) > len(suffix)

    def holds_selection(self, node: Any) -> bool:
        """Whether a ``Literal`` below ``node`` selects ``[<old>]``."""
        stack = [node]
        while stack:
            current = stack.pop()
            if isinstance(current, dict):
                text = _literal_text(current)
                if text is not None and self.bracketed.search(text):
                    return True
                stack.extend(current.values())
            elif isinstance(current, list):
                stack.extend(current)
        return False


def literal_name(name: str) -> str:
    """``name`` as it is spelled between brackets inside a selection literal.

    A closing bracket is doubled (DAX bracket escaping) and an apostrophe is
    written four times: once doubled for the quoted DAX reference, and that
    pair doubled again for the quoted literal string that carries it.
    """
    return name.replace("]", "]]").replace("'", "'" * 4)


def _literal_text(node: dict) -> str | None:
    """The ``Value`` text of ``node["Literal"]``, if ``node`` holds one."""
    holder = node.get("Literal")
    text = holder.get("Value") if isinstance(holder, dict) else None
    return text if isinstance(text, str) else None


def _replace_suffix(value: str, old_len: int, new: str) -> str:
    return value[: len(value) - old_len] + new


def _plan(node: Any, m: _Matcher, new: str, new_label: str) -> list[Edit]:
    """Collect every edit for ``node``'s tree without changing anything."""
    edits: list[Edit] = []
    stack: list[Any] = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, list):
            stack.extend(current)
            continue
        if not isinstance(current, dict):
            continue
        edits.extend(_plan_object(current, m, new, new_label))
        stack.extend(current.values())
    return edits


def _setter(target: dict, key: str, value: Any) -> Edit:
    def apply() -> None:
        target[key] = value
    return apply


def _binds_something_else(obj: dict) -> bool:
    """Whether ``obj`` is a projection whose ``field`` is not a measure.

    A column (or hierarchy level, or aggregated column) can share the
    measure's name; its references and label then belong to the column.
    """
    field = obj.get("field")
    return isinstance(field, dict) and bool(field) and "Measure" not in field


def _plan_object(obj: dict, m: _Matcher, new: str, new_label: str) -> list[Edit]:
    edits: list[Edit] = []

    measure = obj.get("Measure")
    if isinstance(measure, dict) and m.is_old(measure.get("Property")):
        edits.append(_setter(measure, "Property", new))

    if _binds_something_else(obj):
        return edits

    for key in ("queryRef", "metadata"):
        value = obj.get(key)
        if m.ends_with_old(value):
            edits.append(_setter(obj, key, _replace_suffix(value, len(m.old), new)))

    if m.is_old(obj.get("nativeQueryRef")):
        edits.append(_setter(obj, "nativeQueryRef", new))

    text = _literal_text(obj)
    hits = len(m.bracketed.findall(text)) if text is not None else 0
    if hits:
        spelled = literal_name(new)
        rewritten = m.bracketed.sub(lambda _: f"[{spelled}]", text)
        edits.append(_setter(obj["Literal"], "Value", rewritten))
        # One edit per occurrence, so the count matches the rewrite.
        edits.extend(lambda: None for _ in range(hits - 1))

    label = obj.get("displayName")
    if isinstance(label, str) and m.is_old_label(label):
        cached_item = "id" in obj and m.holds_selection(obj["id"])
        projection = m.is_old(obj.get("nativeQueryRef")) or m.ends_with_old(obj.get("queryRef"))
        if cached_item or projection:
            edits.append(_setter(obj, "displayName", new_label))

    values = (obj.get("decomposedIdentities") or {}).get("values") if isinstance(
        obj.get("decomposedIdentities"), dict) else None
    value_map = obj.get("valueMap")
    if isinstance(values, list) and isinstance(value_map, list) and len(values) == len(value_map):
        for identity, entry in zip(values, value_map):
            if (
                isinstance(entry, dict)
                and m.is_old_label(entry.get("0"))
                and m.holds_selection(identity)
            ):
                edits.append(_setter(entry, "0", new_label))
    return edits


def rewrite_tree(
    node: Any,
    old: str,
    new: str,
    old_label: str | None = None,
    new_label: str | None = None,
) -> int:
    """Rename measure ``old`` to ``new`` everywhere in ``node`` (in place).

    Returns the number of references rewritten. ``old_label`` / ``new_label``
    default to the measure names.
    """
    matcher = _Matcher(old, old_label)
    edits = _plan(node, matcher, new, new_label if new_label is not None else new)
    for edit in edits:
        edit()
    return len(edits)


def count_tree(node: Any, old: str, old_label: str | None = None) -> int:
    """How many references :func:`rewrite_tree` would rewrite; changes nothing."""
    return len(_plan(node, _Matcher(old, old_label), old, old))


# -- report files ---------------------------------------------------------------
def report_roots(model_dir: Path) -> list[Path]:
    """Every ``*.Report`` folder at any depth under the model's parent folder."""
    base = Path(model_dir).parent
    return sorted(p for p in base.rglob("*.Report") if p.is_dir())


def report_files(root: Path) -> list[Path]:
    """The JSON files of one report root that can reference a measure."""
    definition = Path(root) / "definition"
    visuals = sorted(definition.glob("pages/*/visuals/*/visual.json"))
    bookmarks = sorted(definition.glob("bookmarks/*.bookmark.json"))
    return visuals + bookmarks


def _scan(
    roots: Iterable[Path], plan: Callable[[Any], int]
) -> Iterator[tuple[Path, bytes, Any, int]]:
    """Visit every report file once, yielding ``(path, raw, document, hits)``.

    ``plan`` runs on the parsed document and returns its hit count (it may
    change the document in place). Files without hits are not yielded;
    unreadable files are passed over.
    """
    for root in roots:
        for path in report_files(root):
            try:
                raw = path.read_bytes()
                data = json.loads(decode(raw))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            hits = plan(data)
            if hits:
                yield path, raw, data, hits


def count_measure_refs(
    roots: Iterable[Path], old: str, old_label: str | None = None
) -> int:
    """Total references to ``old`` across the report roots (read-only)."""
    found = _scan(roots, lambda doc: count_tree(doc, old, old_label))
    return sum(hits for *_, hits in found)


def rename_measure(
    roots: Iterable[Path],
    old: str,
    new: str,
    old_label: str | None = None,
    new_label: str | None = None,
    *,
    backup: Callable[[Path], None] | None = None,
    on_file: Callable[[Path, int], None] | None = None,
) -> int:
    """Rewrite every reference to ``old`` across the report roots.

    Changed files are written back as 2-space JSON that keeps the file's
    byte-order mark and line endings; ``backup`` (if given) is called with
    each path before it is rewritten. Returns the number of references
    rewritten.
    """
    def rename(doc: Any) -> int:
        return rewrite_tree(doc, old, new, old_label, new_label)

    total = 0
    for path, raw, data, hits in _scan(roots, rename):
        if backup is not None:
            backup(path)
        path.write_bytes(Layout.of(raw).encode(dump_json(data)))
        total += hits
        if on_file is not None:
            on_file(path, hits)
    return total
