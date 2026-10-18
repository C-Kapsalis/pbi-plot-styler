"""PLH001: saved state names the blank-dimension placeholder its axis offers.

Each dimension selector (``y-*``) offers one "no dimension" row: a column of
the placeholder table (``#Report Measures[z]``, ``[z_space]``, ...). Visuals
and bookmarks store the picked column, so retargeting an axis can leave a
binding to a placeholder the axis no longer offers. A role bound to several
axes that offer different placeholders is ambiguous: it is reported as
skipped and never changed.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

from ..canvas import dig
from . import RuleContext, rewrite_json


@dataclass
class _Hit:
    path: Path
    where: str
    column: dict
    holder: dict
    old: str
    wanted: str


class _Judge:
    def __init__(self, ctx: RuleContext) -> None:
        self.ctx = ctx
        self.table = ctx.settings.placeholders.blank_dimension_table
        self._offers: dict[str, set[str]] = {}

    def offers(self, axis: str) -> set[str]:
        if axis not in self._offers:
            model = self.ctx.model
            self._offers[axis] = {
                ref.name for ref in (model.nameof_refs(axis) if model else [])
                if ref.qualifier == self.table
            }
        return self._offers[axis]

    def wanted(self, axes: Iterable[str]) -> tuple[str | None, str | None]:
        """``(placeholder, note)``: exactly one placeholder, or why not."""
        axes = sorted(set(axes))
        union = set().union(*(self.offers(a) for a in axes)) if axes else set()
        if len(union) == 1:
            return next(iter(union)), None
        if not union:
            return None, f"axes {axes} offer no {self.table} placeholder"
        return None, f"ambiguous: axes {axes} offer {sorted(union)}"

    def axes_of(self, params: Any) -> list[str]:
        found = []
        for param in params or []:
            column = dig(param, "parameterExpr", "Column") or dig(param, "expr", "Column")
            entity = dig(column, "Expression", "SourceRef", "Entity")
            if self.ctx.settings.is_dimension_selector(entity):
                found.append(entity)
        return found

    def is_placeholder(self, column: Any) -> bool:
        return isinstance(column, dict) and \
            dig(column, "Expression", "SourceRef", "Entity") == self.table


def _hits_in_visual(judge: _Judge, path: Path, data: Any) -> Iterator[_Hit]:
    state = dig(data, "visual", "query", "queryState")
    for role, block in (state or {}).items() if isinstance(state, dict) else []:
        if not isinstance(block, dict):
            continue
        axes = judge.axes_of(block.get("fieldParameters"))
        if not axes:
            continue
        for projection in block.get("projections") or []:
            if not isinstance(projection, dict):
                continue
            column = projection.get("Column") or dig(projection, "field", "Column")
            if not judge.is_placeholder(column):
                continue
            wanted, note = judge.wanted(axes)
            if note:
                judge.ctx.skip(f"stale-placeholders: {path.parent.name}/{role}: {note}")
            elif column.get("Property") != wanted:
                yield _Hit(path, f"{path.parent.name}/{role}", column, projection,
                           column.get("Property"), wanted)


def _hits_in_bookmark(judge: _Judge, path: Path, data: Any) -> Iterator[_Hit]:
    sections = dig(data, "explorationState", "sections")
    for page_id, section in (sections or {}).items() if isinstance(sections, dict) else []:
        containers = dig(section, "visualContainers")
        for cid, container in (containers or {}).items() if isinstance(containers, dict) else []:
            single = dig(container, "singleVisual")
            if not isinstance(single, dict):
                continue
            params = single.get("parameters") if isinstance(single.get("parameters"), dict) else {}
            projections = single.get("projections") if isinstance(single.get("projections"), dict) else {}
            for group in ("projections", "activeProjections"):
                roles = single.get(group)
                for role, exprs in (roles or {}).items() if isinstance(roles, dict) else []:
                    axes = judge.axes_of(params.get(role))
                    if not axes:
                        continue
                    for expr in exprs or []:
                        column = dig(expr, "Column")
                        if not judge.is_placeholder(column):
                            continue
                        wanted, note = judge.wanted(axes)
                        where = f"{page_id}/{cid}/{group}.{role}"
                        if note:
                            judge.ctx.skip(f"stale-placeholders: {where}: {note}")
                        elif column.get("Property") != wanted:
                            yield _Hit(path, where, column, expr, column.get("Property"), wanted)
            axes = [a for role in projections for a in judge.axes_of(params.get(role))]
            if not axes:
                continue
            wanted, _note = judge.wanted(axes)
            if wanted is None:
                continue
            extras = [(f.get("expression"), "filters") for f in dig(container, "filters", "byExpr") or []
                      if isinstance(f, dict)]
            extras += [(o.get("Expression"), "orderBy") for o in single.get("orderBy") or []
                       if isinstance(o, dict)]
            for holder, label in extras:
                column = dig(holder, "Column")
                if judge.is_placeholder(column) and column.get("Property") != wanted:
                    yield _Hit(path, f"{page_id}/{cid}/{label}", column, holder,
                               column.get("Property"), wanted)


def _collect(ctx: RuleContext) -> tuple[list[_Hit], dict[Path, Any]]:
    if ctx.model is None:
        ctx.skip("stale-placeholders: no paired semantic model")
        return [], {}
    judge = _Judge(ctx)
    hits: list[_Hit] = []
    docs: dict[Path, Any] = {}
    for visual in ctx.index.visuals():
        docs[visual.path] = visual.data
        hits.extend(_hits_in_visual(judge, visual.path, visual.data))
    for bookmark in ctx.bookmarks:
        docs[bookmark.path] = bookmark.data
        hits.extend(_hits_in_bookmark(judge, bookmark.path, bookmark.data))
    return hits, docs


def check_placeholders(ctx: RuleContext) -> None:
    hits, _ = _collect(ctx)
    for hit in hits:
        ctx.add("PLH001", hit.path, f"{hit.where}:{hit.old}",
                f"{hit.where} binds placeholder [{hit.old}], but its axis offers "
                f"[{hit.wanted}]", fixable=True)


def fix_placeholders(ctx: RuleContext) -> list[tuple[Path, str]]:
    hits, docs = _collect(ctx)
    touched: dict[Path, list[str]] = {}
    for hit in hits:
        hit.column["Property"] = hit.wanted
        for key in ("queryRef", "nativeQueryRef"):
            value = hit.holder.get(key)
            if isinstance(value, str) and value.endswith(f".{hit.old}"):
                hit.holder[key] = value[: len(value) - len(hit.old)] + hit.wanted
        touched.setdefault(hit.path, []).append(f"{hit.where}: [{hit.old}] -> [{hit.wanted}]")
    changes = []
    for path, notes in touched.items():
        if rewrite_json(path, docs[path]):
            changes.extend((path, note) for note in notes)
    return changes
