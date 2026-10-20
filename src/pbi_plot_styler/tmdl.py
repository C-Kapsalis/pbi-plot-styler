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
from .textio import read_text

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
    r"\s*\[((?:[^\]\n]|\]\])+)\]\s*\)",
    re.IGNORECASE,
)


def _unquote(single: str | None, double: str | None, bare: str | None) -> str:
    if single is not None:
        return single.replace("''", "'").strip()
    return (double if double is not None else bare or "").strip()


def strip_dax_comments(text: str) -> str:
    """Remove ``--`` / ``//`` line comments and ``/* */`` block comments.

    String literals (``"..."``) and quoted names (``'...'``) are respected,
    so ``"a -- b"`` survives. A block comment may span lines; every newline
    inside it is kept, so line numbers of the surrounding text never move.
    Field-parameter partitions routinely keep retired measures around as
    commented-out tuples; those must never seed formatting entries.
    """
    out: list[str] = []
    in_string: str | None = None
    in_block = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        pair = text[i : i + 2]
        if in_block:
            if pair == "*/":
                in_block = False
                i += 2
                continue
            if ch == "\n":
                out.append(ch)
            i += 1
            continue
        if ch == "\n":
            # A quote never spans lines in DAX; a stray one must not swallow
            # the rest of the file.
            in_string = None
            out.append(ch)
            i += 1
            continue
        if in_string:
            if ch == in_string:
                in_string = None
            out.append(ch)
            i += 1
            continue
        if ch in {'"', "'"}:
            in_string = ch
            out.append(ch)
            i += 1
            continue
        if pair in ("--", "//"):
            newline = text.find("\n", i)
            i = n if newline < 0 else newline
            continue
        if pair == "/*":
            in_block = True
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


@dataclass(frozen=True)
class CatalogEntry:
    """One measure row of a field-parameter table."""

    #: ``"Table.Measure"`` key, the form ``selector.metadata`` uses.
    key: str
    #: The tuple's sort ordinal (third tuple member), when it has one.
    ordinal: float | None
    #: Zero-based position of the row in the partition source.
    position: int


@dataclass(frozen=True)
class NameofRef:
    """One ``NAMEOF ( ... )`` argument in a table's DAX."""

    #: The table qualifier as written, or ``None`` for a bare ``[Name]``.
    qualifier: str | None
    #: The bracketed name.
    name: str
    #: Whether the closing parenthesis is followed by a comma (a tuple
    #: member of a field-parameter row, not a trailing reference).
    in_tuple: bool
    #: The row's sort ordinal (the number after the reference), if any.
    ordinal: float | None = None


@dataclass
class SemanticModel:
    """A parsed view of a PBIP semantic model's ``definition/tables``."""

    definition_dir: Path
    #: table name -> set of measure names declared in it.
    measures_by_table: dict[str, set[str]] = field(default_factory=dict)
    #: table name -> set of column names declared in it.
    columns_by_table: dict[str, set[str]] = field(default_factory=dict)
    #: table name -> {hierarchy name: [level names]}.
    hierarchies_by_table: dict[str, dict[str, list[str]]] = field(
        default_factory=dict
    )
    #: table name -> raw TMDL text (used to scan field-parameter partitions).
    raw_by_table: dict[str, str] = field(default_factory=dict)
    _catalog_cache: dict[str, list[CatalogEntry]] = field(
        default_factory=dict, repr=False
    )

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
            content = read_text(tmdl_file)
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
            columns, hierarchies = _parse_columns_and_hierarchies(content)
            model.columns_by_table[table_name] = columns
            model.hierarchies_by_table[table_name] = hierarchies
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

    # -- case-insensitive resolution (used by `check`) -----------------------
    def table_named(self, name: str) -> str | None:
        """The model's spelling of table ``name``, matched case-insensitively."""
        if name in self.raw_by_table:
            return name
        lowered = name.lower()
        for table in self.raw_by_table:
            if table.lower() == lowered:
                return table
        return None

    def field_kind(self, table: str, name: str) -> str | None:
        """``"measure"``, ``"column"`` or ``"hierarchy"`` for a field of
        ``table`` (both matched case-insensitively), or ``None``."""
        real = self.table_named(table)
        if real is None:
            return None
        lowered = name.lower()
        if any(m.lower() == lowered for m in self.measures_by_table.get(real, ())):
            return "measure"
        if any(c.lower() == lowered for c in self.columns_by_table.get(real, ())):
            return "column"
        if any(h.lower() == lowered for h in self.hierarchies_by_table.get(real, {})):
            return "hierarchy"
        return None

    def hierarchy_levels(self, table: str, hierarchy: str) -> list[str] | None:
        real = self.table_named(table)
        if real is None:
            return None
        for name, levels in self.hierarchies_by_table.get(real, {}).items():
            if name.lower() == hierarchy.lower():
                return levels
        return None

    def resolves_ref_string(self, ref: str) -> bool:
        """Whether a ``"Table.Field"`` string (a ``queryRef`` or a
        ``selector.metadata``) names something in the model.

        The string is split at a *known table prefix*, longest first, never
        with a naive ``rsplit(".")``: measure names may contain dots
        (``Sales.Revenue v1.2 (Adj.)``). An aggregation wrapper such as
        ``Sum(Orders.Amount)`` is unwrapped first. After the table, the rest
        may be a measure, a column, a hierarchy, ``Hierarchy.Level``, or a
        date-variation path that starts with a column name.
        """
        wrapped = _AGG_WRAPPER.match(ref)
        if wrapped:
            ref = wrapped.group(1)
        lowered = ref.lower()
        candidates = sorted(
            (t for t in self.raw_by_table if lowered.startswith(t.lower() + ".")),
            key=len,
            reverse=True,
        )
        for table in candidates:
            rest = ref[len(table) + 1 :]
            if self.field_kind(table, rest):
                return True
            rest_lower = rest.lower()
            for hierarchy, levels in self.hierarchies_by_table.get(table, {}).items():
                prefix = hierarchy.lower() + "."
                if rest_lower.startswith(prefix) and any(
                    lvl.lower() == rest_lower[len(prefix) :] for lvl in levels
                ):
                    return True
            for column in self.columns_by_table.get(table, ()):
                if rest_lower.startswith(column.lower() + "."):
                    return True
        return False

    def nameof_refs(self, table: str) -> list[NameofRef]:
        """Every ``NAMEOF`` argument in ``table``'s TMDL, comments ignored."""
        real = self.table_named(table)
        if real is None:
            return []
        source = strip_dax_comments(self.raw_by_table[real])
        refs: list[NameofRef] = []
        for ref in _NAMEOF_REF.finditer(source):
            qualifier = _unquote(ref.group(1), ref.group(2), None) or None
            in_tuple = bool(re.compile(r"\s*,").match(source, ref.end()))
            ordinal = _ORDINAL_AFTER.match(source, ref.end())
            refs.append(NameofRef(
                qualifier, ref.group(3).replace("]]", "]").strip(), in_tuple,
                float(ordinal.group(1)) if ordinal else None,
            ))
        return refs

    def declaring_table(self, measure: str) -> str | None:
        """The first table (file order) that declares ``measure``."""
        return self.home_table(measure)

    # -- field-parameter scan -------------------------------------------------
    def parameter_catalog(self, table: str) -> list[CatalogEntry]:
        """The measure rows of one field-parameter table, in source order.

        A NAMEOF reference counts as a measure when the model actually
        declares a measure by that name: a table-qualified reference is
        checked against that table, a bare reference is resolved to its home
        table. Column references are skipped, and commented-out tuples are
        ignored. Duplicate registrations are kept; callers decide.
        Returns ``[]`` for a table that is unknown or references no measure.
        """
        real = self.table_named(table)
        if real is None:
            return []
        if real in self._catalog_cache:
            return self._catalog_cache[real]
        entries: list[CatalogEntry] = []
        source = strip_dax_comments(self.raw_by_table[real])
        for ref in _NAMEOF_REF.finditer(source):
            ref_table = _unquote(ref.group(1), ref.group(2), None) or None
            ref_name = ref.group(3).strip()
            if ref_table:
                if not self.has_measure(ref_table, ref_name):
                    continue
                key = f"{ref_table}.{ref_name}"
            else:
                home = self.home_table(ref_name)
                if home is None:
                    continue
                key = f"{home}.{ref_name}"
            ordinal_match = _ORDINAL_AFTER.match(source, ref.end())
            ordinal = float(ordinal_match.group(1)) if ordinal_match else None
            entries.append(CatalogEntry(key, ordinal, len(entries)))
        self._catalog_cache[real] = entries
        return entries

    def field_parameter_measures(
        self, field_parameter_tables: tuple[str, ...]
    ) -> list[str]:
        """Every measure a field-parameter table exposes, as sorted
        ``"Table.Measure"`` keys (see ``parameter_catalog``)."""
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
        keys: set[str] = set()
        for table_name in field_parameter_tables:
            if table_name in self.raw_by_table:
                keys.update(e.key for e in self.parameter_catalog(table_name))
        return sorted(keys)

    def palette_slots(self, field_parameter_tables: tuple[str, ...]) -> dict[str, int]:
        """Each measure's stable palette slot: ``"Table.Measure"`` -> index.

        Tables are taken in configured order; within a table, rows are
        ordered by their sort ordinal (source position breaks ties and
        orders rows without one). The first registration of a measure fixes
        its slot, and a later duplicate does not consume one. A measure's
        color therefore follows the order an author chose in the model, not
        the alphabet, so renaming or adding a measure elsewhere in the list
        does not repaint it.
        """
        slots: dict[str, int] = {}
        for table_name in field_parameter_tables:
            rows = sorted(
                self.parameter_catalog(table_name),
                key=lambda e: (
                    e.ordinal is None,
                    e.ordinal if e.ordinal is not None else 0.0,
                    e.position,
                ),
            )
            for entry in rows:
                if entry.key not in slots:
                    slots[entry.key] = len(slots)
        return slots


# -- column / hierarchy inventory ---------------------------------------------
_OBJECT_DECL = re.compile(
    r"^(?P<indent>[ \t]+)(?P<kind>column|hierarchy|level|measure|partition|"
    r"calculationGroup|calculationItem|annotation|extendedProperty)\s+"
    r"(?:'(?P<single>(?:[^'\n]|'')+)'|\"(?P<double>[^\"\n]+)\"|(?P<bare>[^\s=]+))"
)


def _indent_width(indent: str) -> int:
    return len(indent.expandtabs(4))


def _parse_columns_and_hierarchies(
    content: str,
) -> tuple[set[str], dict[str, list[str]]]:
    """Columns and hierarchies (with their levels) declared in a table file."""
    columns: set[str] = set()
    hierarchies: dict[str, list[str]] = {}
    current: str | None = None
    current_indent = 0
    for line in content.splitlines():
        m = _OBJECT_DECL.match(line)
        if not m:
            continue
        kind = m.group("kind")
        name = _unquote(m.group("single"), m.group("double"), m.group("bare"))
        indent = _indent_width(m.group("indent"))
        if kind == "level" and current is not None and indent > current_indent:
            hierarchies[current].append(name)
            continue
        if kind in ("annotation", "extendedProperty") and current is not None:
            continue
        current = None
        if kind == "column":
            columns.add(name)
        elif kind == "hierarchy":
            current, current_indent = name, indent
            hierarchies[name] = []
    return columns, hierarchies


_AGG_WRAPPER = re.compile(r"^[A-Za-z]+\((.*)\)$", re.DOTALL)
_ORDINAL_AFTER = re.compile(r"\s*,\s*(-?\d+(?:\.\d+)?)")
