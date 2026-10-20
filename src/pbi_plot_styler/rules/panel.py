"""PNL001 / PNL002: the canvas filter slicers live in one named master group."""
from __future__ import annotations

import re
from pathlib import Path

from ..canvas import Visual, dig
from . import RuleContext, RuleError, rewrite_json


def check_filter_panel(ctx: RuleContext) -> None:
    target = ctx.settings.panel.group_name
    visuals = list(ctx.index.visuals())
    if not any(v.vtype in ("group", "unknown") for v in visuals):
        ctx.checked["filter-panel"] = 0
        ctx.skip("filter-panel: the report has no group containers")
        return
    ctx.checked["filter-panel"] = 1
    master = next((v for v in visuals if v.semantic_name == target), None)
    definition = ctx.report_dir / "definition"
    if master is None:
        ctx.add("PNL001", definition / "pages", target,
                f"no visual is named {target!r}; panel bookmarks and tooling "
                f"cannot find the filter region", fixable=True)
    elif master.vtype not in ("group", "unknown"):
        ctx.add("PNL002", master.path, target,
                f"{target!r} is a {master.vtype}, not a group container")


def _filter_tables_in(path: Path, tables: tuple[str, ...]) -> set[str]:
    text = path.read_bytes().decode("utf-8-sig")
    return {
        table for table in tables
        if re.search(r'"Entity"\s*:\s*' + re.escape(f'"{table}"'), text)
    }


def _master_candidate(visuals: dict[str, Visual], tables: tuple[str, ...]) -> Visual | None:
    tables_under: dict[str, set[str]] = {}

    def chain(start: Visual) -> list[str]:
        seen: list[str] = []
        parent = start.parent
        while parent and parent in visuals and parent not in seen:
            seen.append(parent)
            parent = visuals[parent].parent
        return seen

    for visual in visuals.values():
        if visual.is_group:
            continue
        found = _filter_tables_in(visual.path, tables)
        if not found:
            continue
        for ancestor in chain(visual):
            tables_under.setdefault(ancestor, set()).update(found)

    def eligible(name: str) -> bool:
        group = visuals[name]
        display = dig(group.data, "visualGroup", "displayName")
        return (
            group.is_group  # never turn a non-group visual into the master
            and len(tables_under[name]) >= 2
            and group.data.get("isHidden") is not True
            and not (isinstance(display, str) and display.startswith("_"))
        )

    def rank(name: str) -> tuple[int, int, str]:
        # most filter tables first, then the most deeply nested group; the
        # name breaks ties, smallest first (hence the negated string order)
        return len(tables_under[name]), len(chain(visuals[name])), _reverse_order(name)

    candidates = [name for name in tables_under if name in visuals and eligible(name)]
    best = max(candidates, key=rank, default=None)
    return visuals[best] if best is not None else None


def _covered(visuals: dict[str, Visual], master: Visual, tables: tuple[str, ...]) -> list[str]:
    """The filter tables of the visuals nested under ``master``."""
    found: set[str] = set()
    for visual in visuals.values():
        if visual.is_group:
            continue
        parent, seen = visual.parent, set()
        while parent and parent in visuals and parent not in seen:
            if parent == master.name:
                found |= _filter_tables_in(visual.path, tables)
                break
            seen.add(parent)
            parent = visuals[parent].parent
    return sorted(found)


def _reverse_order(name: str) -> tuple[int, ...]:
    """A key under which ``max`` prefers the alphabetically smallest name."""
    return tuple(-ord(ch) for ch in name) + (1,)


def fix_filter_panel(ctx: RuleContext) -> list[tuple[Path, str]]:
    """Rename the detected master group on the main page, with its cascade.

    Acts only when the check reports ``PNL001`` for the report: a report that
    already has a visual named like the master (or no group at all) is left
    as it is.
    """
    target = ctx.settings.panel.group_name
    every = list(ctx.index.visuals())
    if not any(v.vtype in ("group", "unknown") for v in every):
        return []
    if any(v.semantic_name == target for v in every):
        ctx.skip(f"filter-panel fix: {target!r} is already present; nothing to rename")
        return []
    page = ctx.index.main_page(ctx.settings)
    if page is None:
        ctx.skip("filter-panel fix: no main page (slicers + combo chart + matrix)")
        return []
    visuals = {v.folder: v for v in page.visuals if v.name == v.folder}
    master = _master_candidate(visuals, ctx.settings.panel.filter_tables)
    if master is None:
        ctx.skip("filter-panel fix: no group covers two or more filter tables")
        return []
    old = master.name
    display = dig(master.data, "visualGroup", "displayName")
    if old == target and display == target:
        ctx.skip(f"filter-panel fix: {target!r} is already named; nothing to rename")
        return []
    covered = _covered(visuals, master, ctx.settings.panel.filter_tables)
    if old != target and (page.path / "visuals" / target).exists():
        raise RuleError(
            f"cannot rename {old!r} to {target!r}: page {page.page_id} already "
            f"has a visual folder named {target!r}"
        )

    changes: list[tuple[Path, str]] = []
    master.data["name"] = target
    master.data.setdefault("visualGroup", {})["displayName"] = target
    # this fixer writes visual files with non-ASCII text escaped
    rewrite_json(master.path, master.data, ascii_only=True)
    changes.append((master.path, f"renamed group {old!r} (display name {display!r}, "
                                 f"covering {', '.join(covered)}) to {target!r}"))
    if old != target:
        for visual in page.visuals:
            if visual.parent == old and visual is not master:
                visual.data["parentGroupName"] = target
                if rewrite_json(visual.path, visual.data, ascii_only=True):
                    changes.append((visual.path, f"parentGroupName {old!r} -> {target!r}"))
        bookmarks = ctx.report_dir / "definition" / "bookmarks"
        quoted_old, quoted_new = f'"{old}"', f'"{target}"'
        for path in sorted(bookmarks.glob("*.json")):
            raw = path.read_bytes()
            text = raw.decode("utf-8")
            if quoted_old in text:
                path.write_bytes(text.replace(quoted_old, quoted_new).encode("utf-8"))
                changes.append((path, f"{quoted_old} -> {quoted_new}"))
        master.path.parent.rename(master.path.parent.with_name(target))
    return changes
