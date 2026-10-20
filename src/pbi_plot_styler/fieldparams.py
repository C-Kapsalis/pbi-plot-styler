"""Detecting a model's field parameters, and what each one offers.

A field parameter is a calculated table whose column carries
`extendedProperty ParameterMetadata` and whose calculated partition holds
`NAMEOF(...)` tuples. The name pattern is a hint, not the rule: a table
called `Bar Metrics` is a field parameter when the model says so, and a
table called `x-Selector 1` that carries no parameter metadata is not.

Each detected parameter is classified by what its rows point at:

- a **dimension parameter** offers columns (the `NAMEOF` targets are
  columns);
- a **metric parameter** offers measures.

The styler's selector and column-well logic works on the DIMENSION
parameters: those are the ones a slicer binds to.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# `extendedProperty ParameterMetadata` on a column of the table.
_PARAMETER_METADATA = re.compile(
    r"^\s*extendedProperty\s+ParameterMetadata\b", re.MULTILINE)

# A `NAMEOF(...)` reference: the table (optional) and the object.
_NAMEOF = re.compile(
    r"NAMEOF\s*\(\s*"
    r"(?:'((?:[^'\n]|'')+)'|([A-Za-z_][^'\"\[\]\n(),]*?))?"  # optional table
    r"\s*\[((?:[^\]\n]|\]\])+)\]\s*\)",
    re.IGNORECASE)

# The calculated partition's source: the rows live between the braces.
_ROW_TUPLE = re.compile(r"\(\s*(?:\"[^\"]*\"|'[^']*')\s*,\s*NAMEOF", re.IGNORECASE)


@dataclass(frozen=True)
class FieldParameter:
    """One detected field-parameter table."""

    name: str
    #: ``"dimension"``, ``"metric"`` or ``"mixed"``.
    kind: str = "dimension"
    #: the objects the rows point at, in source order.
    targets: tuple[str, ...] = ()

    @property
    def is_dimension(self) -> bool:
        return self.kind == "dimension"

    @property
    def is_metric(self) -> bool:
        return self.kind == "metric"


@dataclass
class FieldParameterSet:
    """Every detected field parameter of a model."""

    parameters: list[FieldParameter] = field(default_factory=list)

    @property
    def dimension(self) -> list[FieldParameter]:
        return [p for p in self.parameters if p.is_dimension]

    @property
    def metric(self) -> list[FieldParameter]:
        return [p for p in self.parameters if p.is_metric]

    @property
    def mixed(self) -> list[FieldParameter]:
        return [p for p in self.parameters if p.kind == "mixed"]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(p.name for p in self.parameters)

    @property
    def dimension_names(self) -> tuple[str, ...]:
        return tuple(p.name for p in self.dimension)

    @property
    def metric_names(self) -> tuple[str, ...]:
        return tuple(p.name for p in self.metric)


def _unquote(single: str | None, double: str | None, bare: str | None) -> str:
    if single is not None:
        return single.replace("''", "'").strip()
    return (double if double is not None else bare or "").strip()


def _strip_comments(text: str) -> str:
    """The text without ``--`` and ``//`` line comments."""
    out = []
    for line in text.split("\n"):
        stripped = line.lstrip()
        if stripped.startswith("--") or stripped.startswith("//"):
            continue
        out.append(line)
    return "\n".join(out)


def _source_of(text: str) -> str:
    """The body of the table's calculated partition."""
    lines = text.split("\n")
    in_calc = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("partition ") and stripped.endswith("= calculated"):
            in_calc = True
            continue
        if in_calc and stripped.startswith("source") and "=" in stripped:
            body = []
            for rest in lines[i + 1:]:
                if rest.strip() and not rest.startswith("\t\t"):
                    break
                body.append(rest)
            return "\n".join(body)
    return ""


def detect_field_parameters(tables: dict[str, str],
                            measures_by_table: dict[str, set[str]] | None = None
                            ) -> FieldParameterSet:
    """Every field parameter of a model, from its TMDL.

    ``tables`` maps a table's name to its file text; ``measures_by_table``
    maps a table's name to the measures it declares (used to tell a metric
    parameter from a dimension one).
    """
    measures_by_table = measures_by_table or {}
    out = FieldParameterSet()
    for name, text in sorted(tables.items()):
        if not _PARAMETER_METADATA.search(text):
            continue
        source = _strip_comments(_source_of(text))
        if not _ROW_TUPLE.search(source):
            continue
        targets = []
        for hit in _NAMEOF.finditer(source):
            targets.append((_unquote(hit.group(1), hit.group(2), None),
                            hit.group(3).strip()))
        out.parameters.append(_classify(name, targets, measures_by_table))
    return out


def _classify(name: str, targets: list[tuple[str | None, str]],
              measures_by_table: dict[str, set[str]]) -> FieldParameter:
    """A parameter is a metric one when its rows point at measures."""
    points_at_measure = False
    points_at_column = False
    for ref_table, ref_name in targets:
        if ref_table:
            names = measures_by_table.get(ref_table) or set()
            if any(n.lower() == ref_name.lower() for n in names):
                points_at_measure = True
            else:
                points_at_column = True
        else:
            points_at_measure = True
    if points_at_measure and points_at_column:
        kind = "mixed"
    elif points_at_measure:
        kind = "metric"
    else:
        kind = "dimension"
    return FieldParameter(name=name, kind=kind,
                          targets=tuple(f"{t or ''}[{n}]" for t, n in targets))


def detect_from_directory(definition: Path) -> FieldParameterSet:
    """Every field parameter of a model folder, from its TMDL files."""
    from .tmdl import SemanticModel
    model = SemanticModel.load(definition)
    return detect_field_parameters(model.raw_by_table, model.measures_by_table)
