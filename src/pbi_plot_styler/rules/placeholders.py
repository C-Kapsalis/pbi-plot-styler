"""PLH001: saved state names the blank-dimension placeholder its axis offers.

Each dimension selector (``y-*``) offers one "no dimension" row: a column of
the placeholder table (``#Report Measures[z]``, ``[z_space]``, ...). Visuals
and bookmarks store the picked column, so retargeting an axis can leave a
binding to a placeholder the axis no longer offers. A role bound to several
axes that offer different placeholders is ambiguous: it is reported as
skipped and never changed.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

from ..canvas import dig
from ..textio import load_json
from . import RuleContext, rewrite_json


@dataclass
class _Hit:
    path: Path
    where: str
    column: dict
    holder: dict
    old: str
    wanted: str


@dataclass
class _Skip:
    path: Path
    role: str
    axes: list[str]
    placeholders: list[str]
    ambiguous: bool


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


def _skip(judge: _Judge, path: Path, role: str, axes: list[str], note: str) -> None:
    """Record the placeholder a role cannot be repointed to."""
    judge.ctx.skip(f"stale-placeholders: {judge.ctx.rel(path)}: {role}: {note}")
    if note.startswith("ambiguous: axes"):
        placeholders = ast.literal_eval(note.split("offer ", 1)[-1])
        judge.ctx.options.setdefault("placeholder_skips", []).append(
            _Skip(path, role, axes, list(placeholders), True))
        return
    judge.ctx.options.setdefault("placeholder_skips", []).append(
        _Skip(path, role, axes, [], False))

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
                _skip(judge, path, role, axes, note)
            elif column.get("Property") != wanted:
                yield _Hit(path, role, column, projection,
                           column.get("Property"), wanted)


def _hits_in_bookmark(judge: _Judge, path: Path, data: Any) -> Iterator[_Hit]:
    sections = dig(data, "explorationState", "sections")
    for page_id, section in (sections or {}).items() if isinstance(sections, dict) else []:
        containers = dig(section, "visualContainers")
        for container_id, container in (containers or {}).items() if isinstance(containers, dict) else []:
            state = dig(container, "singleVisual")
            if not isinstance(state, dict):
                continue
            params = state.get("parameters") if isinstance(state.get("parameters"), dict) else {}
            projections = state.get("projections") if isinstance(state.get("projections"), dict) else {}
            for group in ("projections", "activeProjections"):
                roles = state.get(group)
                for role, bound in (roles or {}).items() if isinstance(roles, dict) else []:
                    axes = judge.axes_of(params.get(role))
                    if not axes:
                        continue
                    for expr in bound or []:
                        column = dig(expr, "Column")
                        if not judge.is_placeholder(column):
                            continue
                        wanted, note = judge.wanted(axes)
                        where = f"{group}.{role}"
                        if note:
                            _skip(judge, path, role, axes, note)
                        elif column.get("Property") != wanted:
                            yield _Hit(path, where, column, expr, column.get("Property"), wanted)
            all_axes = [a for role in projections for a in judge.axes_of(params.get(role))]
            wanted = judge.wanted(all_axes)[0] if all_axes else None
            if wanted is None:
                continue
            extras = [(f.get("expression"), "filter") for f in dig(container, "filters", "byExpr") or []
                      if isinstance(f, dict)]
            extras += [(o.get("Expression"), "orderBy") for o in state.get("orderBy") or []
                       if isinstance(o, dict)]
            for node, origin in extras:
                column = dig(node, "Column")
                if judge.is_placeholder(column) and column.get("Property") != wanted:
                    yield _Hit(path, origin, column, node,
                               column.get("Property"), wanted)


def _collect(ctx: RuleContext) -> tuple[list[_Hit], dict[Path, Any], list[tuple[Path, str]]]:
    if ctx.model is None:
        ctx.missing_model("stale-placeholders")
        return [], {}, []
    judge = _Judge(ctx)
    ctx.options["placeholder_skips"] = []
    hits: list[_Hit] = []
    docs: dict[Path, Any] = {}
    errors: list[tuple[Path, str]] = []
    for visual in ctx.index.visuals():
        docs[visual.path] = visual.data
        hits.extend(_hits_in_visual(judge, visual.path, visual.data))
    # every JSON file of the bookmarks folder that holds exploration state
    folder = ctx.report_dir / "definition" / "bookmarks"
    for path in sorted(folder.glob("*.json")):
        if path.name == "bookmarks.json":
            continue
        try:
            data = load_json(path)
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            errors.append((path, str(exc)))
            continue
        if isinstance(data, dict) and isinstance(data.get("explorationState"), dict):
            docs[path] = data
            hits.extend(_hits_in_bookmark(judge, path, data))
    return hits, docs, errors


def check_placeholders(ctx: RuleContext) -> None:
    hits, _docs, errors = _collect(ctx)
    for path, message in errors:
        ctx.options.setdefault("read_errors", []).append(
            (path, f"  ERROR {path.resolve()}: {message}"))
    for hit in hits:
        ctx.add("PLH001", hit.path, f"{hit.where}:{hit.old}",
                f"{hit.old}->{hit.wanted} ({hit.where})", fixable=True)
    fixed = ctx.options.get("placeholder_fix")
    if fixed:
        ctx.details["stale-placeholders"] = fixed
        return
    ctx.details["stale-placeholders"] = {
        "stale": len(hits),
        "skips": _skip_lines(ctx),
        "lines": _file_lines(ctx, hits, "would repoint"),
    }


def fix_placeholders(ctx: RuleContext) -> list[tuple[Path, str]]:
    hits, docs, errors = _collect(ctx)
    for path, message in errors:
        ctx.options.setdefault("read_errors", []).append(
            (path, f"  ERROR {path.resolve()}: {message}"))
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
    ctx.options["placeholder_fix"] = {
        "stale": len(hits),
        "skips": _skip_lines(ctx),
        "lines": _file_lines(ctx, hits, "repointed"),
    }
    return changes


def _skip_lines(ctx: RuleContext) -> list[str]:
    """The SKIPPED lines of a run, in the order they were found."""
    lines = []
    for skip in ctx.options.get("placeholder_skips") or []:
        axes = ", ".join(repr(a) for a in skip.axes)
        if skip.ambiguous:
            lines.append(f"  SKIPPED {ctx.rel(skip.path)}: {skip.role}: [{axes}] offer "
                         f"{sorted(skip.placeholders)} — ambiguous")
        else:
            table = ctx.settings.placeholders.blank_dimension_table
            lines.append(f"  SKIPPED {ctx.rel(skip.path)}: {skip.role}: [{axes}] offer no "
                         f"{table} placeholder")
    return lines


def _file_lines(ctx: RuleContext, hits: list[_Hit], verb: str) -> list[str]:
    """The per-file lines of a run: the repoint ones, with their SKIPPED ones."""
    lines: list[str] = []
    by_file: dict[Path, list[_Hit]] = {}
    for hit in hits:
        by_file.setdefault(hit.path, []).append(hit)
    skips = ctx.options.get("placeholder_skips") or []
    for path, group in by_file.items():
        for skip in [s for s in skips if s.path == path]:
            lines.append(_skip_line(ctx, skip))
        shown = ", ".join(f"{h.old}->{h.wanted} ({h.where})" for h in group[:3])
        kind = "bookmark" if path.name.endswith(".bookmark.json") else "visual"
        lines.append(f"  {verb} {len(group):3d} in {kind} {ctx.rel(path)}: {shown}")
    return lines


def _skip_line(ctx: RuleContext, skip: "_Skip") -> str:
    axes = ", ".join(repr(a) for a in skip.axes)
    if skip.ambiguous:
        return (f"  SKIPPED {ctx.rel(skip.path)}: {skip.role}: [{axes}] offer "
                f"{sorted(skip.placeholders)} — ambiguous")
    table = ctx.settings.placeholders.blank_dimension_table
    return (f"  SKIPPED {ctx.rel(skip.path)}: {skip.role}: [{axes}] offer no "
            f"{table} placeholder")


def render_placeholders(findings, counts, framing, values) -> list[str]:
    """The per-file lines, the findings and the totals of a placeholder run."""
    lines = list(counts.get("lines") or [])
    for line in counts.get("skips") or []:
        if line not in lines:
            lines.append(line)
    lines += [framing(f) for f in findings]
    total = counts.get("stale", 0)
    skipped = len(counts.get("skips") or [])
    verb = "repointed" if values.get("fixing") else "stale"
    lines.append("")
    lines.append(f"{verb}: {total}" + (f"; skipped {skipped}" if skipped else ""))
    if not total and not skipped:
        return [f"No stale placeholder bindings under {values['check_folder']}."]
    return lines
