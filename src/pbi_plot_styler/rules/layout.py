"""Theme, visual position and y-combo naming rules."""
from __future__ import annotations

import re

from ..canvas import dig, read_json
from . import RuleContext, rule_result_block

#: A quoted hex colour literal in raw report.json text: a JSON string
#: ``"#00FF00"``, or a DAX literal ``"'#FF0000'"`` (how a hard-coded colour
#: is saved in an ``expr.Literal.Value``).
_HEX_LITERAL = re.compile(r'"(?:#[0-9A-Fa-f]{3,8}|\'#[0-9A-Fa-f]{3,8}\')"')
_MAX_SAMPLES = 8


def check_theme(ctx: RuleContext) -> None:
    """THM002-THM006: the report declares its themes and no hex literals."""
    report_json = ctx.report_dir / "definition" / "report.json"
    data = read_json(report_json)
    themes = dig(data, "themeCollection")
    if not isinstance(themes, dict):
        themes = {}
    ctx.checked["theme"] = 1
    ctx.details["theme"] = {"components": 1}

    def declared(slot: str) -> bool:
        return bool(themes.get(slot))

    if not themes:
        ctx.add("THM002", report_json, "themeCollection",
                "Report missing themeCollection configuration (Expected: "
                "themeCollection with baseTheme and customTheme, Got: null or missing)")
    if not declared("customTheme"):
        ctx.add("THM003", report_json, "customTheme",
                "No custom theme defined - may use hardcoded colors (Expected: "
                "customTheme configuration, Got: null or missing)")
    if not declared("baseTheme") and not declared("customTheme"):
        ctx.add("THM005", report_json, "themeCollection",
                "Report has no theme configuration. Without a base or custom theme, "
                "ThemeDataColor references cannot resolve and visuals fall back to "
                "Power BI defaults.")
    missing = [slot for slot in ("baseTheme", "customTheme") if not declared(slot)]
    if missing:
        ctx.add("THM006", report_json, "+".join(missing),
                f"Theme collection is incomplete - missing: {', '.join(missing)}. "
                f"Reports must declare both baseTheme and customTheme.")

    try:
        text = report_json.read_bytes().decode("utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return
    hits = _HEX_LITERAL.findall(text)
    if hits:
        samples = sorted({h for h in hits})[:_MAX_SAMPLES]
        ctx.add("THM004", report_json, "hex-literals",
                f"{len(hits)} hard-coded hex color literal(s) in report.json "
                f"(sample: {', '.join(samples)}) (Expected: ThemeDataColor "
                f"references only, Got: {len(hits)} '#RGBHEX' literals)")


def check_positions(ctx: RuleContext) -> None:
    """POS001: every visual container sets ``position.x`` and ``position.y``."""
    visuals = list(ctx.index.visuals())
    ctx.checked["visual-position"] = len(visuals)
    if not visuals:
        ctx.skip("visual-position: No visual containers discovered")
        return
    missing: list[str] = []
    for visual in visuals:
        position = visual.data.get("position")
        position = position if isinstance(position, dict) else {}
        axes = [axis for axis in ("x", "y") if position.get(axis) is None]
        if axes:
            missing.append(visual.semantic_name)
            ctx.add("POS001", visual.path, visual.semantic_name,
                    f"1 visual container(s) missing x or y position: "
                    f"{visual.semantic_name}")
    ctx.details["visual-position"] = {"missing": len(missing), "names": missing}


def render_positions(findings, counts, framing, values) -> list[str]:
    """The findings and the aggregate line of a visual-position check."""
    lines = [framing(f) for f in findings]
    names = counts.get("names") or []
    if names:
        shown = ", ".join(names[:10])
        lines.append(f"{len(names)} visual container(s) missing x or y position: "
                     f"{shown}{'...' if len(names) > 10 else ''}")
    return lines


_GROUP_NAME = re.compile(r"y\d+_combo_group")
#: a member needs at least one character after ``y<N>_``
_MEMBER_NAME = re.compile(r"y\d+_(.+)", re.DOTALL)


def check_y_combo(ctx: RuleContext) -> None:
    """YCG001 / YCG002: y<N>_combo_group naming and membership."""
    visuals = list(ctx.index.visuals())
    if not visuals:
        ctx.skip("y-combo naming: No visuals discovered")
        return
    candidates = [
        v for v in visuals
        if "combo_group" in v.semantic_name.lower() and v.semantic_name.lower().startswith("y")
    ]
    if not candidates:
        ctx.skip("y-combo naming: No y-combo groups discovered in this report - skip "
                 "rather than fail (reports without y-combos are valid).")
    misnamed: list[str] = []
    for visual in candidates:
        if not _GROUP_NAME.fullmatch(visual.semantic_name):
            misnamed.append(visual.semantic_name)
            ctx.add("YCG001", visual.path, visual.semantic_name,
                    f"1 y-combo group(s) violate the y{{N}}_combo_group naming "
                    f"pattern: {visual.semantic_name}")
    groups = {v.semantic_name for v in visuals if _GROUP_NAME.fullmatch(v.semantic_name)}
    if not groups:
        ctx.skip("y-combo hierarchy: No y_combo_group containers in this report")
        ctx.details["y-combo"] = {
            "misnamed": len(misnamed),
            "group names": misnamed,
            "orphans": 0,
            "orphan rows": [],
        }
        return
    names = ctx.index.semantic_names()
    orphans: list[tuple[str, str]] = []
    for visual in visuals:
        member = _MEMBER_NAME.fullmatch(visual.semantic_name)
        if not member or member.group(1) == "combo_group":
            continue
        parent = names.get(visual.parent, visual.parent) if visual.parent else None
        if parent not in groups:
            shown = parent if parent else "<no parentGroupName>"
            orphans.append((visual.semantic_name, shown))
            ctx.add("YCG002", visual.path, visual.semantic_name,
                    f"1 y-combo child visual(s) orphaned (missing or invalid "
                    f"parentGroupName): {visual.semantic_name} → parent: {shown}")
    ctx.details["y-combo"] = {
        "misnamed": len(misnamed),
        "group names": misnamed,
        "orphans": len(orphans),
        "orphan rows": orphans,
    }


def render_y_combo(findings, counts, framing, values) -> list[str]:
    """The findings and the aggregate sentences of a y-combo check."""
    lines = [framing(f) for f in findings]
    names = counts.get("group names") or []
    if names:
        lines.append(f"{len(names)} y-combo group(s) violate the y{{N}}_combo_group "
                     f"naming pattern: {', '.join(names[:10])}"
                     f"{'...' if len(names) > 10 else ''}")
    rows = counts.get("orphan rows") or []
    if rows:
        lines.append(f"{len(rows)} y-combo child visual(s) orphaned (missing or "
                     f"invalid parentGroupName):")
        for child, parent in rows[:10]:
            lines.append(f"  - {child} → parent: {parent}")
    return lines


def render_theme(findings, counts, framing, values) -> list[str]:
    """The result block and the failure block of the theme rule."""
    return rule_result_block(6, findings, counts, framing, values)
