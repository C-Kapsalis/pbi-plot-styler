"""Theme, visual position and y-combo naming rules."""
from __future__ import annotations

import re

from ..canvas import dig, read_json
from . import RuleContext

#: A quoted hex colour literal in raw report.json text.
_HEX_LITERAL = re.compile(r'"#[0-9A-Fa-f]{3,8}"')
_MAX_SAMPLES = 8


def check_theme(ctx: RuleContext) -> None:
    """THM002-THM006: the report declares its themes and no hex literals."""
    report_json = ctx.report_dir / "definition" / "report.json"
    data = read_json(report_json)
    themes = dig(data, "themeCollection")
    if not isinstance(themes, dict):
        themes = {}
    ctx.checked["theme"] = 1

    def declared(slot: str) -> bool:
        return bool(themes.get(slot))

    if not themes:
        ctx.add("THM002", report_json, "themeCollection",
                "report.json declares no themeCollection, so every visual falls "
                "back to Power BI's default colours")
    if not declared("customTheme"):
        ctx.add("THM003", report_json, "customTheme",
                "report.json declares no customTheme; the report cannot be "
                "rebranded by swapping one theme file")
    if not declared("baseTheme") and not declared("customTheme"):
        ctx.add("THM005", report_json, "themeCollection",
                "themeCollection declares neither a baseTheme nor a customTheme")
    missing = [slot for slot in ("baseTheme", "customTheme") if not declared(slot)]
    if missing:
        ctx.add("THM006", report_json, "+".join(missing),
                f"themeCollection lacks {' and '.join(missing)}")

    try:
        text = report_json.read_bytes().decode("utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return
    hits = _HEX_LITERAL.findall(text)
    if hits:
        samples = sorted({h.strip('"') for h in hits})[:_MAX_SAMPLES]
        ctx.add("THM004", report_json, "hex-literals",
                f"report.json holds {len(hits)} quoted hex colour literal(s) "
                f"that bypass the theme: {', '.join(samples)}")


def check_positions(ctx: RuleContext) -> None:
    """POS001: every visual container sets ``position.x`` and ``position.y``."""
    visuals = list(ctx.index.visuals())
    ctx.checked["visual-position"] = len(visuals)
    if not visuals:
        ctx.skip("visual-position: the report has no visuals")
        return
    for visual in visuals:
        position = visual.data.get("position")
        position = position if isinstance(position, dict) else {}
        missing = [axis for axis in ("x", "y") if position.get(axis) is None]
        if missing:
            ctx.add("POS001", visual.path, visual.semantic_name,
                    f"visual {visual.semantic_name!r} has no position "
                    f"{' or '.join(missing)}, so Power BI places it arbitrarily")


_GROUP_NAME = re.compile(r"y\d+_combo_group")
#: a member needs at least one character after ``y<N>_``
_MEMBER_NAME = re.compile(r"y\d+_(.+)", re.DOTALL)


def check_y_combo(ctx: RuleContext) -> None:
    """YCG001 / YCG002: y<N>_combo_group naming and membership."""
    visuals = list(ctx.index.visuals())
    candidates = [
        v for v in visuals
        if "combo_group" in v.semantic_name.lower() and v.semantic_name.lower().startswith("y")
    ]
    if not candidates:
        ctx.skip("y-combo naming: no y-combo group in this report")
    for visual in candidates:
        if not _GROUP_NAME.fullmatch(visual.semantic_name):
            ctx.add("YCG001", visual.path, visual.semantic_name,
                    f"group {visual.semantic_name!r} does not match y<N>_combo_group")

    groups = {v.semantic_name for v in visuals if _GROUP_NAME.fullmatch(v.semantic_name)}
    if not groups:
        ctx.skip("y-combo hierarchy: no group named y<N>_combo_group")
        return
    names = ctx.index.semantic_names()
    for visual in visuals:
        member = _MEMBER_NAME.fullmatch(visual.semantic_name)
        if not member or member.group(1) == "combo_group":
            continue
        parent = names.get(visual.parent, visual.parent) if visual.parent else None
        if parent not in groups:
            shown = parent if parent else "<no parent>"
            ctx.add("YCG002", visual.path, visual.semantic_name,
                    f"{visual.semantic_name!r} sits under {shown}, not under a "
                    f"y<N>_combo_group, so it cannot be hidden with its stack")
