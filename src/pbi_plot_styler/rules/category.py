"""CAT001: answer bookmarks set the analysis-category filter."""
from __future__ import annotations

import re
from typing import Any

from ..canvas import Bookmark, CategorySection, dig, read_json
from . import RuleContext, rule_result_block

_DEPTH_CAP = 64
_NAVIGATION_EMOJI = ((0x1F300, 0x1FAFF), (0x2600, 0x27BF), (0x1F000, 0x1F02F))
_WIDE_SYMBOLS = ((0x2000, 0xFFFF), (0x10000, 0x1FFFF))


def _label(bookmark: Bookmark) -> str:
    raw = bookmark.data.get("displayName")
    text = raw if isinstance(raw, str) and raw.strip() else bookmark.name
    return text.strip()


def _component(bookmark: Bookmark) -> str:
    """The name a finding carries: the display name as stored, or the name."""
    raw = bookmark.data.get("displayName")
    return raw if isinstance(raw, str) and raw else bookmark.name


def _in_ranges(text: str, ranges) -> bool:
    return any(lo <= ord(ch) <= hi for ch in text for lo, hi in ranges)


def _wordy_chrome(label: str, cfg: CategorySection) -> bool:
    if label.startswith(tuple(cfg.chrome_prefixes)):
        return True
    return any(
        re.search(rf"\b{re.escape(word)}\b", label, re.IGNORECASE)
        for word in cfg.chrome_words
    )


def is_menu_chrome(label: str, cfg: CategorySection) -> bool:
    """Menu furniture (headings, date presets, decorated labels)."""
    return bool(label) and (_wordy_chrome(label, cfg) or _in_ranges(label, _WIDE_SYMBOLS))


def is_navigation(label: str, cfg: CategorySection) -> bool:
    return bool(label) and (_wordy_chrome(label, cfg) or _in_ranges(label, _NAVIGATION_EMOJI))


def bookmarks_in_scope(ctx: RuleContext) -> list[Bookmark]:
    """Bookmarks registered in bookmarks.json groups, minus menu chrome.

    Falls back to the page-level, non-navigation bookmarks when that list
    is empty.
    """
    cfg = ctx.settings.category
    by_name = {b.name: b for b in ctx.bookmarks}
    index = read_json(ctx.report_dir / "definition" / "bookmarks" / "bookmarks.json")
    scoped: list[Bookmark] = []
    for item in dig(index, "items") or []:
        if not isinstance(item, dict):
            continue
        for child in item.get("children") or []:
            bookmark = by_name.get(child) if isinstance(child, str) else None
            if bookmark is not None and not is_menu_chrome(_label(bookmark), cfg):
                scoped.append(bookmark)
    if scoped:
        return scoped
    return [
        bookmark for bookmark in ctx.bookmarks
        if not dig(bookmark.data, "options", "targetVisualNames")
        and not is_navigation(_label(bookmark), cfg)
    ]


def _sets_category(node: Any, cfg: CategorySection, depth: int = 0) -> bool:
    if depth > _DEPTH_CAP:
        return False
    if isinstance(node, list):
        return any(_sets_category(item, cfg, depth + 1) for item in node)
    if not isinstance(node, dict):
        return False
    bodies = []
    if isinstance(node.get("filter"), dict):
        bodies.append(node["filter"])
    if "From" in node and "Where" in node:
        bodies.append(node)
    for body in bodies:
        if _body_filters_category(body, cfg):
            return True
    return any(_sets_category(value, cfg, depth + 1) for value in node.values())


def _body_filters_category(body: dict, cfg: CategorySection) -> bool:
    sources = body.get("From") if isinstance(body.get("From"), list) else []
    if not any(isinstance(s, dict) and s.get("Entity") == cfg.table for s in sources):
        return False
    wheres = body.get("Where") if isinstance(body.get("Where"), list) else []
    for where in wheres:
        for expr in dig(where, "Condition", "In", "Expressions") or []:
            if dig(expr, "Column", "Property") == cfg.column:
                return True
    return False


def check_category_filter(ctx: RuleContext) -> None:
    cfg = ctx.settings.category
    scoped = bookmarks_in_scope(ctx)
    ctx.checked["category-filter"] = len(scoped)
    ctx.details["category-filter"] = {"components": len(scoped)}
    for bookmark in scoped:
        state = bookmark.data.get("explorationState")
        if state is None or not _sets_category(state, cfg):
            label = _component(bookmark)
            ctx.add("CAT001", bookmark.path, label,
                    f"Page-level bookmark has no {cfg.column} filter (Expected: a "
                    f"filter in byName or byExpr targeting {cfg.table}[{cfg.column}], "
                    f"Got: no such filter found)")


def render_category_filter(findings, counts, framing, values) -> list[str]:
    """The result block and the failure block of the category-filter rule."""
    return rule_result_block(3, findings, counts, framing, values)
