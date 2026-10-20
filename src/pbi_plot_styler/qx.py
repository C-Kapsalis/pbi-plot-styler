"""Builders for the Power BI query-expression JSON the fixers write.

Report files describe fields, filters and colours with a small nested
vocabulary (``SourceRef``, ``Literal``, ``Comparison``, ...). Building it
from these helpers keeps every fixer's output shape identical, so two fixers
that write the same gate produce the same bytes.
"""
from __future__ import annotations


def source(entity: str | None = None, *, alias: str | None = None) -> dict:
    """``{"SourceRef": {...}}`` naming an entity, or a ``From`` alias."""
    ref = {"Source": alias} if alias is not None else {"Entity": entity}
    return {"SourceRef": ref}


def field_ref(kind: str, prop: str, entity: str | None = None, *, alias: str | None = None) -> dict:
    """A ``Column`` / ``Measure`` reference: ``{kind: {Expression, Property}}``."""
    return {kind: {"Expression": source(entity, alias=alias), "Property": prop}}


def column(entity: str, prop: str) -> dict:
    return field_ref("Column", prop, entity)


def measure(entity: str, prop: str) -> dict:
    return field_ref("Measure", prop, entity)


def lit(text: str) -> dict:
    """``{"Literal": {"Value": text}}`` (``text`` is DAX literal text)."""
    return {"Literal": {"Value": text}}


def quoted(text: str) -> str:
    """DAX string-literal text: ``'text'``, inner apostrophes doubled."""
    return "'" + text.replace("'", "''") + "'"


def prop_literal(text: str) -> dict:
    """An ``objects`` property value: ``{"expr": {"Literal": ...}}``."""
    return {"expr": lit(text)}


def solid(expr: dict) -> dict:
    """A colour property: ``{"solid": {"color": {"expr": expr}}}``."""
    return {"solid": {"color": {"expr": expr}}}


def hex_colour(colour: str) -> dict:
    return solid(lit(quoted(colour)))


def theme_colour(color_id: int, percent: float | int = 0) -> dict:
    return solid({"ThemeDataColor": {"ColorId": color_id, "Percent": percent}})


def from_entry(alias: str, entity: str) -> dict:
    return {"Name": alias, "Entity": entity, "Type": 0}


def filter_body(alias: str, entity: str, condition: dict) -> dict:
    """A Version 2 filter over one aliased entity with one condition."""
    return {
        "Version": 2,
        "From": [from_entry(alias, entity)],
        "Where": [{"Condition": condition}],
    }


def comparison(kind: int, left: dict, right: dict) -> dict:
    return {"Comparison": {"ComparisonKind": kind, "Left": left, "Right": right}}


def in_values(expression: dict, values: list[str]) -> dict:
    """An ``In`` condition: one expression, one literal per row."""
    return {"In": {"Expressions": [expression], "Values": [[lit(v)] for v in values]}}


def alias_of(entity: str, fallback: str = "t") -> str:
    """A one-letter ``From`` alias for an entity."""
    head = entity[:1].lower()
    return head if head.isalnum() else fallback
