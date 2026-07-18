"""Minimal TMDL parsing: measure inventory and field-parameter references.

The semantic model is the single source of truth for which measures a combo
chart can display: the field-parameter tables list them as
``NAMEOF ( [Measure] )`` (or ``NAMEOF ( 'Table'[Measure] )``) tuples in their
calculated-partition DAX. We parse just enough TMDL to answer two questions:

1. Which measures does each table of the model declare?
2. Which of the NAMEOF references inside the field-parameter tables point at
   a measure (as opposed to a column)?

That is deliberately not a full TMDL parser - table and measure declarations
plus NAMEOF calls are the only grammar this tool depends on.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# `table <name>` at the top of a .tmdl file. Single-quoted names may embed
# doubled quotes; bare names run to end of line.
_TABLE_DECL = re.compile(
    r"^table\s+(?:'((?:[^'\n]|'')+)'|\"([^\"\n]+)\"|(\S[^\n]*?))\s*$",
    re.MULTILINE,
)

# `<indent>measure <name> =` inside a table body.
_MEASURE_DECL = re.compile(
    r"^[ \t]+measure\s+(?:'((?:[^'\n]|'')+)'|\"([^\"\n]+)\"|([^\s=]+))\s*=",
    re.MULTILINE,
)

# NAMEOF ( [X] ) and NAMEOF ( 'Table'[X] ) / NAMEOF ( Table[X] ).
_NAMEOF_REF = re.compile(
    r"NAMEOF\s*\(\s*"
    r"(?:'((?:[^'\n]|'')+)'|([A-Za-z_][^'\"\[\]\n(),]*?))?"  # optional table
    r"\s*\[([^\]\n]+)\]\s*\)",
    re.IGNORECASE,
)


def _unquote(single: str | None, double: str | None, bare: str | None) -> str:
    if single is not None:
        return single.replace("''", "'").strip()
    return (double if double is not None else bare or "").strip()


def strip_dax_comments(text: str) -> str:
    """Remove ``--`` and ``//`` line comments, respecting string literals.

    Field-parameter partitions routinely keep retired measures around as
    commented-out tuples; those must never seed formatting entries.
    """
    out_lines: list[str] = []
    for line in text.splitlines():
        in_string: str | None = None
        cut = len(line)
        i = 0
        while i < len(line):
            ch = line[i]
            if in_string:
                if ch == in_string:
                    in_string = None
            elif ch in {'"', "'"}:
                in_string = ch
            elif line[i : i + 2] in ("--", "//"):
                cut = i
                break
            i += 1
        out_lines.append(line[:cut])
    return "\n".join(out_lines)


@dataclass
class SemanticModel:
    """A parsed view of a PBIP semantic model's ``definition/tables``."""

    definition_dir: Path
    #: table name -> set of measure names declared in it.
    measures_by_table: dict[str, set[str]] = field(default_factory=dict)
    #: table name -> raw TMDL text (used to scan field-parameter partitions).
    raw_by_table: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, model_dir: Path) -> "SemanticModel":
        """Parse every ``definition/tables/*.tmdl`` under ``model_dir``.

        ``model_dir`` may be the ``*.SemanticModel`` folder or its
        ``definition`` subfolder.
        """
        definition = Path(model_dir)
        if (definition / "definition" / "tables").is_dir():
            definition = definition / "definition"
        tables_dir = definition / "tables"
        if not tables_dir.is_dir():
            raise FileNotFoundError(
                f"{model_dir} has no TMDL tables directory (expected "
                f"definition/tables/*.tmdl). Pass the *.SemanticModel folder "
                f"of a model saved in TMDL format."
            )

        model = cls(definition_dir=definition)
        for tmdl_file in sorted(tables_dir.glob("*.tmdl")):
            content = tmdl_file.read_text(encoding="utf-8")
            match = _TABLE_DECL.search(content)
            table_name = (
                _unquote(match.group(1), match.group(2), match.group(3))
                if match
                else tmdl_file.stem
            )
            model.raw_by_table[table_name] = content
            bucket = model.measures_by_table.setdefault(table_name, set())
            for m in _MEASURE_DECL.finditer(content):
                bucket.add(_unquote(m.group(1), m.group(2), m.group(3)))
        return model

    # -- measure lookups ----------------------------------------------------
    def has_measure(self, table: str, name: str) -> bool:
        return name in self.measures_by_table.get(table, set())

    def home_table(self, measure_name: str) -> str | None:
        """First table (sorted file order) declaring ``measure_name``."""
        for table, names in self.measures_by_table.items():
            if measure_name in names:
                return table
        return None

    # -- field-parameter scan -------------------------------------------------
    def field_parameter_measures(
        self, field_parameter_tables: tuple[str, ...]
    ) -> list[str]:
        """Every measure a field-parameter table exposes, as sorted
        ``"Table.Measure"`` keys.

        A NAMEOF reference counts as a measure when the model actually
        declares a measure by that name - table-qualified references are
        checked against that table, bare references are resolved to their
        home table. Column references (dimensions) are skipped, and
        commented-out tuples are ignored.
        """
        keys: set[str] = set()
        missing = [
            t for t in field_parameter_tables if t not in self.raw_by_table
        ]
        if len(missing) == len(field_parameter_tables):
            raise LookupError(
                f"none of the field-parameter tables "
                f"{list(field_parameter_tables)} exist in "
                f"{self.definition_dir / 'tables'}. Check the table names, "
                f"or configure the right ones with --table or the "
                f"[tables] field_parameters config key."
            )
        for table_name in field_parameter_tables:
            content = self.raw_by_table.get(table_name)
            if content is None:
                continue
            for ref in _NAMEOF_REF.finditer(strip_dax_comments(content)):
                ref_table = _unquote(ref.group(1), ref.group(2), None) or None
                ref_name = ref.group(3).strip()
                if ref_table:
                    if self.has_measure(ref_table, ref_name):
                        keys.add(f"{ref_table}.{ref_name}")
                else:
                    home = self.home_table(ref_name)
                    if home is not None:
                        keys.add(f"{home}.{ref_name}")
        return sorted(keys)
