"""Read-only integrity checks for PBIP reports (the ``check`` command).

Every check has a stable id and a severity. Ids never change meaning, so a
committed baseline file keeps working across releases:

======  ========  ==========================================================
Id      Severity  Finding
======  ========  ==========================================================
JSN001  error     A report file is not valid JSON.
MDL001  error     The paired semantic model exists but cannot be loaded.
BND001  error     A field reference (``SourceRef`` entity plus property, or
                  a ``From`` entity) does not resolve in the paired model.
BND002  error     A ``queryRef`` or ``selector.metadata`` string does not
                  resolve in the paired model.
BMK001  error     A bookmark ``options`` key is outside the allowed set.
                  Fixable.
BMK002  error     A bookmark ``howCreated``, ``ComparisonKind`` or
                  ``Version`` is a string, not a JSON integer. Fixable when
                  the string is numeric.
BMK003  error     A bookmark's ``activeSection`` or ``sections`` key names a
                  page that does not exist.
BMK004  error     A bookmark captures a visual that does not exist on that
                  page.
BMK005  error     ``bookmarks.json`` lists a bookmark that has no file.
FPM001  error     Two field parameters of one role claim the same slot.
FPM002  error     A field parameter's slot range runs past the role's
                  projections.
THM001  warning   A ``themeCollection`` entry does not resolve to a file
                  under ``StaticResources``.
======  ========  ==========================================================

Those are the ``integrity`` rule, which ``check`` runs by default. The
convention rules (``--rule SLUG``) add their own ids; they are registered in
:mod:`pbi_plot_styler.rules` and listed in ``CHECKS`` below.

Fixes are surgical text edits: the file is never re-serialized. Each edit
is proven by parsing the text before and after and requiring that the only
difference is the intended one; otherwise the fix is refused and the file is
left untouched.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

from .tmdl import SemanticModel
from .textio import load_json

#: id -> (severity, short title)
CHECKS: dict[str, tuple[str, str]] = {
    "JSN001": ("error", "invalid JSON"),
    "MDL001": ("error", "the paired semantic model cannot be loaded"),
    "BND001": ("error", "unresolved field reference"),
    "BND002": ("error", "unresolved queryRef / metadata string"),
    "BMK001": ("error", "unknown bookmark options key"),
    "BMK002": ("error", "bookmark integer stored as string"),
    "BMK003": ("error", "bookmark names a missing page"),
    "BMK004": ("error", "bookmark captures a missing visual"),
    "BMK005": ("error", "bookmarks.json lists a missing bookmark"),
    "FPM001": ("error", "overlapping field-parameter slots"),
    "FPM002": ("error", "field-parameter slots exceed projections"),
    "THM001": ("warning", "theme file not found"),
    # -- convention rules (``check --rule SLUG``) --
    "ABK000": ("error", "no answer bookmark matches the configured prefixes"),
    "ABK001": ("error", "answer bookmark is scoped to some visuals"),
    "ABK003": ("error", "answer bookmark does not show the matrix"),
    "ABK004": ("error", "matrix capture holds another bookmark's fields"),
    "ABK005": ("error", "matrix capture has a stale shape"),
    "ABK006": ("error", "answer bookmark picker selects nothing"),
    "ABK007": ("error", "answer bookmark does not pin the analysis category"),
    "ABK008": ("error", "answer bookmark is not under a submenu"),
    "ABK009": ("error", "matrix slot map does not match the picks"),
    "ABK010": ("error", "row dimension has no dropdown filter"),
    "PGW001": ("error", "raw measure in a field-parameter well"),
    "PGW002": ("error", "bookmark navigator names a missing bookmark"),
    "BML001": ("error", "picker literal registered only in another selector"),
    "BML002": ("error", "picker literal not registered in any selector"),
    "CAT001": ("error", "bookmark does not set the analysis category"),
    "GAT001": ("error", "selector slicer has no active gate"),
    "GAT002": ("error", "bookmark drops a selector slicer's gate"),
    "GAT003": ("error", "slicer gate missing or passive for its mode"),
    "GAT004": ("error", "slicer gate bound to the wrong table"),
    "GAT005": ("error", "stale gate table reference"),
    "THM002": ("error", "no theme collection"),
    "THM003": ("warning", "no custom theme"),
    "THM004": ("error", "hex colour literal in report.json"),
    "THM005": ("error", "neither a base nor a custom theme"),
    "THM006": ("error", "base or custom theme missing"),
    "POS001": ("error", "visual has no x or y position"),
    "YCG001": ("error", "y-combo group badly named"),
    "YCG002": ("error", "y-combo member outside its group"),
    "PNL001": ("error", "filter-panel master group missing"),
    "PNL002": ("warning", "filter-panel master is not a group"),
    "FMT001": ("error", "format-selector filter missing or incomplete"),
    "PLH001": ("error", "stale blank-dimension placeholder"),
}

#: The closed set of keys Power BI accepts in a bookmark's ``options``. An
#: unknown key is valid JSON, so it passes every local lint, but the service
#: rejects the whole report on import.
ALLOWED_BOOKMARK_OPTIONS = frozenset(
    {
        "targetVisualNames",
        "applyOnlyToTargetVisuals",
        "suppressData",
        "suppressActiveSection",
        "suppressDisplay",
    }
)

#: Bookmark keys whose values must be JSON integers.
INTEGER_KEYS = ("howCreated", "ComparisonKind", "Version")

_NUMERIC = re.compile(r"^-?\d+$")


@dataclass(frozen=True)
class Finding:
    """One problem found by a check."""

    check_id: str
    file: str
    subject: str
    message: str
    fixable: bool = False
    #: tells apart findings that share a subject (an FPM001 slot); part of
    #: the key and location, never of the subject a person reads.
    distinct: str = ""

    @property
    def severity(self) -> str:
        return CHECKS[self.check_id][0]

    @property
    def location(self) -> str:
        """Stable location: the file plus the offending name, never an index."""
        tail = f"#{self.distinct}" if self.distinct else ""
        return f"{self.file}::{self.subject}{tail}"

    @property
    def key(self) -> tuple[str, str]:
        return (self.check_id, self.location)

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out.pop("distinct")
        out["id"] = out.pop("check_id")
        out["severity"] = self.severity
        out["location"] = self.location
        return out


class FixRefused(RuntimeError):
    """A repair could not be proven safe; the file is left untouched."""


# -- generic JSON helpers -----------------------------------------------------
def _load(path: Path) -> tuple[str, Any]:
    text = path.read_bytes().decode("utf-8-sig")
    return text, json.loads(text)


def _entity(expr: Any, aliases: dict[str, str]) -> tuple[str | None, bool]:
    """``(entity, known)`` for a ``SourceRef`` expression.

    ``known`` is ``False`` when the reference cannot be judged (an unknown
    ``From`` alias, a subquery, a non-``SourceRef`` source).
    """
    if not isinstance(expr, dict):
        return None, False
    ref = expr.get("SourceRef")
    if not isinstance(ref, dict) or "Schema" in ref:
        # A "Schema": "extension" source is a report-level measure, defined
        # in reportExtensions.json rather than the model.
        return None, False
    if isinstance(ref.get("Entity"), str):
        return ref["Entity"], True
    source = ref.get("Source")
    if isinstance(source, str) and source in aliases:
        return aliases[source], True
    return None, False


def _iter_binding_problems(
    node: Any,
    model: SemanticModel,
    aliases: dict[str, str] | None = None,
    extensions: frozenset[str] = frozenset(),
) -> Iterator[tuple[str, str, str]]:
    """Yield ``(check_id, subject, message)`` for every unresolved binding.

    ``extensions`` holds lower-cased ``"table.measure"`` keys of report-level
    measures, which resolve without being in the model.
    """
    aliases = aliases or {}
    if isinstance(node, list):
        for item in node:
            yield from _iter_binding_problems(item, model, aliases, extensions)
        return

    def resolves(ref: str) -> bool:
        return ref.lower() in extensions or model.resolves_ref_string(ref)

    if not isinstance(node, dict):
        return

    if isinstance(node.get("From"), list):
        aliases = dict(aliases)
        for source in node["From"]:
            if not isinstance(source, dict):
                continue
            name, entity = source.get("Name"), source.get("Entity")
            if isinstance(entity, str):
                if isinstance(name, str):
                    aliases[name] = entity
                if model.table_named(entity) is None:
                    yield (
                        "BND001",
                        entity,
                        f"From entity {entity!r} is not a table in the model",
                    )

    for kind in ("Measure", "Column"):
        ref = node.get(kind)
        if isinstance(ref, dict) and isinstance(ref.get("Property"), str):
            entity, known = _entity(ref.get("Expression"), aliases)
            if known:
                yield from _check_field(model, kind, entity, ref["Property"])

    level = node.get("HierarchyLevel")
    if isinstance(level, dict):
        hierarchy = (level.get("Expression") or {}).get("Hierarchy") or {}
        expr = hierarchy.get("Expression") or {}
        entity, known = _entity(expr, aliases)
        name = hierarchy.get("Hierarchy")
        if known and isinstance(name, str):
            levels = model.hierarchy_levels(entity, name)
            subject = f"{entity}.{name}.{level.get('Level')}"
            if model.table_named(entity) is None:
                yield ("BND001", subject, f"table {entity!r} is not in the model")
            elif levels is None:
                yield (
                    "BND001",
                    subject,
                    f"hierarchy {name!r} is not declared on table {entity!r}",
                )
            elif isinstance(level.get("Level"), str) and level["Level"].lower() not in {
                lvl.lower() for lvl in levels
            }:
                yield (
                    "BND001",
                    subject,
                    f"level {level['Level']!r} is not in hierarchy {name!r}",
                )

    has_field = isinstance(node.get("field"), dict) and any(
        k in node["field"]
        for k in ("Measure", "Column", "Aggregation", "HierarchyLevel")
    )
    query_ref = node.get("queryRef")
    if has_field and isinstance(query_ref, str) and not resolves(query_ref):
        yield ("BND002", query_ref, f"queryRef {query_ref!r} does not resolve")
    selector = node.get("selector")
    if isinstance(selector, dict) and isinstance(selector.get("metadata"), str):
        metadata = selector["metadata"]
        if not resolves(metadata):
            yield (
                "BND002",
                metadata,
                f"selector.metadata {metadata!r} does not resolve",
            )

    for value in node.values():
        yield from _iter_binding_problems(value, model, aliases, extensions)


def _check_field(
    model: SemanticModel, kind: str, entity: str | None, prop: str
) -> Iterator[tuple[str, str, str]]:
    subject = f"{entity}[{prop}]"
    if entity is None or model.table_named(entity) is None:
        yield ("BND001", subject, f"table {entity!r} is not in the model")
        return
    found = model.field_kind(entity, prop)
    expected = "measure" if kind == "Measure" else "column"
    if found is None:
        yield (
            "BND001",
            subject,
            f"{expected} {prop!r} is not declared on table {entity!r}",
        )
    elif found != expected:
        yield (
            "BND001",
            subject,
            f"{prop!r} on {entity!r} is bound as a {expected} but the model "
            f"declares a {found}",
        )


# -- bookmark text edits -------------------------------------------------------
def _remove_member(text: str, key: str, expected: Any) -> str:
    """Remove the one ``"key": value`` member whose removal yields
    ``expected``; refuse unless exactly one candidate does."""
    decoder = json.JSONDecoder()
    winners: list[str] = []
    for match in re.finditer(rf'"{re.escape(key)}"\s*:\s*', text):
        try:
            _, value_end = decoder.raw_decode(text, match.end())
        except json.JSONDecodeError:
            continue
        start = match.start()
        # Prefer swallowing the trailing comma (first/middle member); fall
        # back to the leading comma (last member); else the sole member.
        trailing = re.compile(r"\s*,\s*").match(text, value_end)
        leading = re.search(r",\s*$", text[:start])
        attempts = []
        if trailing:
            attempts.append(text[:start] + text[trailing.end() :])
        if leading:
            attempts.append(text[: leading.start()] + text[value_end:])
        attempts.append(text[:start] + text[value_end:])
        for candidate in attempts:
            try:
                if json.loads(candidate) == expected:
                    winners.append(candidate)
                    break
            except json.JSONDecodeError:
                continue
    if len(winners) != 1:
        raise FixRefused(
            f"could not isolate exactly one options.{key} member to remove "
            f"({len(winners)} candidates)"
        )
    return winners[0]


def _convert_integers(node: Any) -> int:
    """Convert numeric-string INTEGER_KEYS in place; return how many."""
    count = 0
    if isinstance(node, dict):
        for key, value in node.items():
            if key in INTEGER_KEYS and isinstance(value, str) and _NUMERIC.match(value):
                node[key] = int(value)
                count += 1
            else:
                count += _convert_integers(value)
    elif isinstance(node, list):
        for item in node:
            count += _convert_integers(item)
    return count


def _iter_string_integers(node: Any, path: str = "") -> Iterator[tuple[str, str, str]]:
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}" if path else key
            if key in INTEGER_KEYS and isinstance(value, str):
                yield key, value, here
            else:
                yield from _iter_string_integers(value, here)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_string_integers(item, path)


def fix_bookmark_text(text: str) -> tuple[str, list[str]]:
    """Repair BMK001 and BMK002 in one bookmark file's text.

    Returns ``(new_text, descriptions)``. Raises ``FixRefused`` when an edit
    cannot be proven to change only what it should.
    """
    data = json.loads(text)
    done: list[str] = []
    options = data.get("options")
    if isinstance(options, dict):
        for key in sorted(set(options) - ALLOWED_BOOKMARK_OPTIONS):
            expected = json.loads(text)
            expected["options"].pop(key)
            text = _remove_member(text, key, expected)
            done.append(f"removed options.{key}")

    expected = json.loads(text)
    converted = _convert_integers(expected)
    if converted:
        pattern = re.compile(
            r'("(?:' + "|".join(INTEGER_KEYS) + r')"\s*:\s*)"(-?\d+)"'
        )
        new_text, replaced = pattern.subn(r"\1\2", text)
        try:
            ok = replaced == converted and json.loads(new_text) == expected
        except json.JSONDecodeError:
            ok = False
        if not ok:
            raise FixRefused(
                "could not convert the string integers without touching "
                "anything else"
            )
        text = new_text
        done.append(f"converted {converted} string integer(s)")
    return text, done


# -- per-report checks -----------------------------------------------------------
@dataclass
class ReportContext:
    report_dir: Path
    root: Path
    model: SemanticModel | None
    findings: list[Finding] = field(default_factory=list)
    extensions: frozenset[str] = frozenset()

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def add(self, check_id: str, path: Path, subject: str, message: str,
            fixable: bool = False, distinct: str = "") -> None:
        finding = Finding(check_id, self.rel(path), subject, message, fixable, distinct)
        if finding.key not in {f.key for f in self.findings}:
            self.findings.append(finding)


def _read(ctx: ReportContext, path: Path) -> tuple[str, Any] | None:
    try:
        return _load(path)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        ctx.add("JSN001", path, path.name, f"not valid JSON: {exc}")
        return None


def _page_inventory(ctx: ReportContext) -> dict[str, set[str]]:
    """page name -> visual names, read from page.json / visual.json."""
    pages: dict[str, set[str]] = {}
    pages_dir = ctx.report_dir / "definition" / "pages"
    for page_json in sorted(pages_dir.glob("*/page.json")):
        loaded = _read(ctx, page_json)
        name = page_json.parent.name
        if loaded and isinstance(loaded[1], dict):
            name = loaded[1].get("name") or name
        visuals: set[str] = set()
        for visual_json in sorted(page_json.parent.glob("visuals/*/visual.json")):
            try:
                _, data = _load(visual_json)
                visuals.add((data or {}).get("name") or visual_json.parent.name)
            except (json.JSONDecodeError, UnicodeDecodeError):
                visuals.add(visual_json.parent.name)
        pages[name] = visuals
    return pages


def _check_bindings(ctx: ReportContext, path: Path, data: Any) -> None:
    if ctx.model is None:
        return
    for check_id, subject, message in _iter_binding_problems(
        data, ctx.model, extensions=ctx.extensions
    ):
        ctx.add(check_id, path, subject, message)


def _check_field_parameter_slots(ctx: ReportContext, path: Path, data: Any) -> None:
    query_state = (
        (((data or {}).get("visual") or {}).get("query") or {}).get("queryState")
        or {}
    )
    for role, block in query_state.items():
        if not isinstance(block, dict):
            continue
        params = block.get("fieldParameters") or []
        projections = block.get("projections") or []
        claimant: dict[int, str] = {}
        for param in params:
            if not isinstance(param, dict):
                continue
            column = (param.get("parameterExpr") or {}).get("Column") or {}
            name = (
                ((column.get("Expression") or {}).get("SourceRef") or {}).get("Entity")
                or "?"
            )
            start, length = param.get("index", 0), param.get("length", 0)
            if not isinstance(start, int) or not isinstance(length, int):
                continue
            for slot in range(start, start + length):
                earlier = claimant.get(slot)
                if earlier is not None:
                    ctx.add(
                        "FPM001", path, f"{role}:{earlier}|{name}",
                        f"{path.parent.name}/{role}: parameters {earlier} and {name} both "
                        f"claim slot {slot} — the later one wins, so {earlier}'s picks "
                        f"render in NO bookmark",
                        distinct=f"slot{slot}",
                    )
                # The latest claimant owns the slot, so a third claim is
                # paired with the second.
                claimant[slot] = name
            if length and start + length > len(projections):
                ctx.add(
                    "FPM002", path, f"{role}:{name}",
                    f"{path.parent.name}/{role}: parameter {name} claims slots "
                    f"{start}..{start + length - 1} but the well carries only "
                    f"{len(projections)} projections",
                )


def _check_bookmark(
    ctx: ReportContext, path: Path, text: str, data: Any, pages: dict[str, set[str]]
) -> None:
    if not isinstance(data, dict):
        return
    options = data.get("options")
    if isinstance(options, dict):
        for key in sorted(set(options) - ALLOWED_BOOKMARK_OPTIONS):
            ctx.add(
                "BMK001", path, f"options.{key}",
                f"options.{key} is not an allowed bookmark option; the "
                f"service rejects the whole report on import",
                fixable=True,
            )
    for key, value, where in _iter_string_integers(data):
        numeric = bool(_NUMERIC.match(value))
        ctx.add(
            "BMK002", path, where,
            f"{key} is the string {value!r}; it must be a JSON integer"
            + ("" if numeric else " (not numeric, so it needs a manual fix)"),
            fixable=numeric,
        )
    state = data.get("explorationState") or {}
    active = state.get("activeSection")
    if isinstance(active, str) and active not in pages:
        ctx.add(
            "BMK003", path, f"activeSection:{active}",
            f"activeSection {active!r} is not a page of this report",
        )
    for page, section in (state.get("sections") or {}).items():
        if page not in pages:
            ctx.add(
                "BMK003", path, f"sections:{page}",
                f"sections names page {page!r}, which does not exist",
            )
            continue
        if not isinstance(section, dict):
            continue
        for group in ("visualContainers", "visualContainerGroups"):
            for visual in section.get(group) or {}:
                if visual not in pages[page]:
                    ctx.add(
                        "BMK004", path, f"{page}/{visual}",
                        f"{group} captures visual {visual!r}, which is not "
                        f"on page {page!r}",
                    )


def _check_bookmark_index(
    ctx: ReportContext, index_path: Path, data: Any, names: set[str]
) -> None:
    def walk(items: Any) -> Iterator[str]:
        for item in items or []:
            if isinstance(item, str):
                yield item
            elif isinstance(item, dict):
                if "children" in item:
                    yield from walk(item["children"])
                elif isinstance(item.get("name"), str):
                    yield item["name"]

    for name in walk((data or {}).get("items")):
        if name not in names:
            ctx.add(
                "BMK005", index_path, name,
                f"bookmarks.json lists {name!r}, but there is no "
                f"{name}.bookmark.json",
            )


def _check_theme(ctx: ReportContext, report_json: Path, data: Any) -> None:
    if not isinstance(data, dict):
        return
    packages = {
        p.get("name"): p for p in data.get("resourcePackages") or [] if isinstance(p, dict)
    }
    static = ctx.report_dir / "StaticResources"
    for slot, theme in (data.get("themeCollection") or {}).items():
        if not isinstance(theme, dict) or not theme.get("name"):
            continue
        name, kind = theme["name"], theme.get("type")
        package = packages.get(kind) or {}
        items = [
            i for i in package.get("items") or []
            if isinstance(i, dict) and i.get("name") == name
        ]
        if not items:
            ctx.add(
                "THM001", report_json, f"{slot}:{name}",
                f"themeCollection.{slot} {name!r} has no item in the "
                f"{kind!r} resource package",
            )
            continue
        target = static / str(package.get("name")) / str(items[0].get("path", ""))
        if not target.is_file():
            ctx.add(
                "THM001", report_json, f"{slot}:{name}",
                f"themeCollection.{slot} {name!r} points at "
                f"{ctx.rel(target)}, which does not exist",
            )


def _extension_measures(ctx: ReportContext, path: Path) -> frozenset[str]:
    """Lower-cased ``"table.measure"`` keys of report-level measures."""
    if not path.is_file():
        return frozenset()
    loaded = _read(ctx, path)
    keys = set()
    for entity in ((loaded or ("", {}))[1] or {}).get("entities") or []:
        if not isinstance(entity, dict):
            continue
        for measure in entity.get("measures") or []:
            if isinstance(measure, dict) and measure.get("name"):
                keys.add(f"{entity.get('name')}.{measure['name']}".lower())
    return frozenset(keys)


def check_report(
    report_dir: Path, root: Path, model: SemanticModel | None
) -> list[Finding]:
    """Run every integrity check against one report folder."""
    ctx = ReportContext(report_dir, root, model)
    run_integrity(ctx)
    return sorted(ctx.findings, key=lambda f: (f.file, f.check_id, f.subject))


def run_integrity(ctx: ReportContext) -> None:
    """The default ``integrity`` rule: bindings, bookmarks, slots, themes."""
    report_dir = ctx.report_dir
    definition = report_dir / "definition"
    ctx.extensions = _extension_measures(ctx, definition / "reportExtensions.json")
    pages = _page_inventory(ctx)

    report_json = definition / "report.json"
    if report_json.is_file():
        loaded = _read(ctx, report_json)
        if loaded:
            _check_bindings(ctx, report_json, loaded[1])
            _check_theme(ctx, report_json, loaded[1])

    for page_json in sorted((definition / "pages").glob("*/page.json")):
        loaded = _read(ctx, page_json)
        if loaded:
            _check_bindings(ctx, page_json, loaded[1])
    for visual_json in sorted((definition / "pages").rglob("visual.json")):
        loaded = _read(ctx, visual_json)
        if loaded:
            _check_bindings(ctx, visual_json, loaded[1])
            _check_field_parameter_slots(ctx, visual_json, loaded[1])

    bookmarks_dir = definition / "bookmarks"
    names: set[str] = set()
    for bookmark in sorted(bookmarks_dir.glob("*.bookmark.json")):
        names.add(bookmark.name[: -len(".bookmark.json")])
        loaded = _read(ctx, bookmark)
        if not loaded:
            continue
        text, data = loaded
        if isinstance(data, dict) and isinstance(data.get("name"), str):
            names.add(data["name"])
        _check_bookmark(ctx, bookmark, text, data, pages)
        _check_bindings(ctx, bookmark, data)
    index = bookmarks_dir / "bookmarks.json"
    if index.is_file():
        loaded = _read(ctx, index)
        if loaded:
            _check_bookmark_index(ctx, index, loaded[1], names)


def fix_report(report_dir: Path) -> tuple[list[tuple[Path, str]], list[tuple[Path, str]]]:
    """Apply every safe fix (BMK001, BMK002) under one report.

    Returns ``(fixed, refused)`` as ``(path, description)`` pairs. A refused
    file is left byte-for-byte untouched.
    """
    fixed: list[tuple[Path, str]] = []
    refused: list[tuple[Path, str]] = []
    for bookmark in sorted(
        (report_dir / "definition" / "bookmarks").glob("*.bookmark.json")
    ):
        raw = bookmark.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        try:
            text = raw.decode("utf-8-sig")
            json.loads(text)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        try:
            new_text, done = fix_bookmark_text(text)
        except FixRefused as exc:
            refused.append((bookmark, str(exc)))
            continue
        if new_text != text:
            bookmark.write_bytes(
                (b"\xef\xbb\xbf" if bom else b"") + new_text.encode("utf-8")
            )
            fixed.extend((bookmark, d) for d in done)
    return fixed, refused


# -- baseline ----------------------------------------------------------------------
BASELINE_VERSION = 1


def load_baseline(path: Path) -> set[tuple[str, str]]:
    data = load_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("findings"), list):
        raise ValueError(
            f"{path} is not a pbi-plot-styler baseline (expected an object "
            f"with a 'findings' list). Recreate it with --update-baseline."
        )
    return {
        (str(f["id"]), str(f["location"]))
        for f in data["findings"]
        if isinstance(f, dict) and "id" in f and "location" in f
    }


def write_baseline(path: Path, findings: list[Finding],
                   keep: Iterable[tuple[str, str]] = ()) -> None:
    """Write ``findings`` plus the ``keep`` entries (id, location) of other scopes."""
    by_key = {key: {"id": key[0], "location": key[1]} for key in keep}
    by_key.update({f.key: {"id": f.check_id, "location": f.location} for f in findings})
    entries = sorted(
        by_key.values(),
        key=lambda e: (e["id"], e["location"]),
    )
    path.write_text(
        json.dumps({"version": BASELINE_VERSION, "findings": entries}, indent=2)
        + "\n",
        encoding="utf-8",
    )

