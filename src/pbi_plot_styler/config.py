"""Configuration model and loading for pbi-plot-styler.

Precedence (highest wins): CLI flags > config file > built-in defaults.
"""
from __future__ import annotations

import dataclasses
import re
import sys
from pathlib import Path
from typing import Any, Union

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on Python 3.10
    import tomli as tomllib

DEFAULT_FIELD_PARAMETER_TABLES: tuple[str, ...] = (
    "x-Plot Specific 1",
    "x-Plot Specific 2",
    "y-Plot Specific",
)
DEFAULT_VISUAL_TYPES: tuple[str, ...] = (
    "lineClusteredColumnComboChart",
    "lineStackedColumnComboChart",
)
DEFAULT_LINE_COLOR = "#118DFF"
DEFAULT_LABEL_COLOR = "#252423"
DEFAULT_LABEL_TRANSPARENCY = 20
DEFAULT_CONFIG_FILENAME = "plotstyler.toml"

_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


class ConfigError(ValueError):
    """Raised for malformed configuration values."""


@dataclasses.dataclass(frozen=True)
class ThemeColor:
    """A theme-relative color: slot ``color_id`` of the report theme's
    ``dataColors``, lightened (positive) or darkened (negative) by
    ``percent``. Serialized as Power BI's ``ThemeDataColor`` expression, so
    the chart follows a theme change instead of pinning a hex value."""

    color_id: int
    percent: float = 0


#: A series color: a ``#RRGGBB`` literal or a theme-relative color.
Color = Union[str, ThemeColor]


def _require_hex(value: str, key: str) -> str:
    if not isinstance(value, str) or not _HEX_RE.match(value):
        raise ConfigError(
            f"{key} is set to {value!r}, which is not a valid color. "
            f"Use a 6-digit hex color of the form '#RRGGBB', "
            f"such as '#118DFF'."
        )
    return value.upper() if value.islower() else value


@dataclasses.dataclass(frozen=True)
class StylerConfig:
    """Every knob the styler exposes, with its default."""

    #: Field-parameter tables whose NAMEOF measure references drive the styling.
    field_parameter_tables: tuple[str, ...] = DEFAULT_FIELD_PARAMETER_TABLES
    #: visualType values that get restyled.
    visual_types: tuple[str, ...] = DEFAULT_VISUAL_TYPES
    #: Query roles (for example "Y", Power BI's internal name for a combo
    #: chart's column well) whose *currently bound* measure is excluded
    #: from styling, per visual. Empty by default (no exclusion). This is
    #: how a measure that is a member of the line's field-parameter table
    #: but is presently plotted on the columns via a different selector
    #: avoids getting the line's styling bled onto it.
    exclude_current_roles: tuple[str, ...] = ()
    #: Hex color for the combo chart's line/column series fill.
    line_color: str = DEFAULT_LINE_COLOR
    #: Optional palette; when non-empty it is cycled per measure and
    #: overrides ``line_color``.
    palette: tuple[str, ...] = ()
    #: Hex color for the data-label text.
    label_color: str = DEFAULT_LABEL_COLOR
    #: Hex color for the data-label background. ``None`` means "match the
    #: measure's line color".
    label_background: str | None = None
    #: Data-label background transparency, 0-100.
    label_transparency: int = DEFAULT_LABEL_TRANSPARENCY
    #: Whether data labels are switched on.
    show_labels: bool = True
    #: Theme ``dataColors`` slot used instead of ``line_color`` when set.
    theme_color_id: int | None = None
    #: Lighten (>0) or darken (<0) the theme color, -1.0 to 1.0.
    theme_color_percent: float = 0
    #: Per-measure pins, ``"Table.Measure"`` -> ``#RRGGBB``. A pin beats the
    #: palette, the theme color and ``line_color`` for that one measure.
    colors: tuple[tuple[str, str], ...] = ()
    #: Names of the fields above that a config file or CLI flag set
    #: explicitly. Label settings a visual already carries are kept unless
    #: the user explicitly configured them (see ``report.restyle_visual``).
    explicit: frozenset[str] = frozenset()

    def validate(self) -> None:
        if not self.field_parameter_tables:
            raise ConfigError(
                "field_parameter_tables is empty, so no measures can be "
                "resolved. List at least one table under [tables] "
                "field_parameters, or pass --table."
            )
        if not self.visual_types:
            raise ConfigError(
                "visual_types is empty, so no visuals can be targeted. "
                "List at least one type under [targets] visual_types, or "
                "pass --visual-type."
            )
        _require_hex(self.line_color, "line_color")
        for color in self.palette:
            _require_hex(color, "palette entry")
        _require_hex(self.label_color, "label_color")
        if self.label_background is not None:
            _require_hex(self.label_background, "label_background")
        for key, color in self.colors:
            if not isinstance(key, str) or "." not in key:
                raise ConfigError(
                    f"color pin {key!r} is not a \"Table.Measure\" key, for "
                    f"example \"Sales Measures.Revenue\"."
                )
            _require_hex(color, f"color pin for {key!r}")
        if self.theme_color_id is not None and (
            isinstance(self.theme_color_id, bool)
            or not isinstance(self.theme_color_id, int)
            or self.theme_color_id < 0
        ):
            raise ConfigError(
                f"theme_color_id is set to {self.theme_color_id!r}. Use a "
                f"non-negative integer: the index into the theme's dataColors."
            )
        if isinstance(self.theme_color_percent, bool) or not isinstance(
            self.theme_color_percent, (int, float)
        ) or not -1 <= self.theme_color_percent <= 1:
            raise ConfigError(
                f"theme_color_percent is set to {self.theme_color_percent!r}, "
                f"which is out of range. Use a number between -1 (darkest) "
                f"and 1 (lightest); 0 is the theme color itself."
            )
        if not isinstance(self.label_transparency, int) or not (
            0 <= self.label_transparency <= 100
        ):
            raise ConfigError(
                f"label_transparency is set to {self.label_transparency!r}, "
                f"which is out of range. Use an integer between 0 "
                f"(opaque) and 100 (fully transparent)."
            )

    # -- per-measure color resolution -------------------------------------
    def _pin_for(self, measure_key: str) -> str | None:
        lowered = measure_key.lower()
        for key, color in self.colors:
            if key.lower() == lowered:
                return color.upper() if color.islower() else color
        return None

    def series_color(self, measure_key: str, slot: int) -> Color:
        """The series fill for a measure.

        Precedence: a ``colors`` pin, then the palette (indexed by the
        measure's stable ``slot``), then ``theme_color_id``, then
        ``line_color``.
        """
        pinned = self._pin_for(measure_key)
        if pinned is not None:
            return pinned
        if self.palette:
            return self.palette[slot % len(self.palette)]
        if self.theme_color_id is not None:
            return ThemeColor(self.theme_color_id, self.theme_color_percent)
        return self.line_color

    def label_background_for(self, measure_key: str, slot: int) -> Color:
        """The label background: explicit hex, or match the series color."""
        if self.label_background is not None:
            return self.label_background
        return self.series_color(measure_key, slot)


_KNOWN_SECTIONS = {"tables", "targets", "style"}
_KNOWN_TABLES_KEYS = {"field_parameters", "renames"}
_KNOWN_TARGETS_KEYS = {"visual_types", "exclude_current_roles"}
_KNOWN_STYLE_KEYS = {
    "line_color",
    "palette",
    "label_color",
    "label_background",
    "label_transparency",
    "show_labels",
    "theme_color_id",
    "theme_color_percent",
    "colors",
}


def apply_table_renames(
    tables: tuple[str, ...], renames: dict[str, str]
) -> tuple[str, ...]:
    """Substitute table names in place, preserving order and position.

    Unlike ``--table``, which replaces the whole field-parameter table
    list the moment it's used once, this changes only the named
    table(s), leaving the rest (defaults or an explicit ``--table``
    list) untouched. Each key in ``renames`` must match a table already
    in ``tables`` exactly; an unmatched rename is almost certainly a
    typo; a table name silently kept unrenamed is worse than an error.
    """
    result = list(tables)
    unmatched = []
    for old, new in renames.items():
        try:
            index = result.index(old)
        except ValueError:
            unmatched.append(old)
            continue
        result[index] = new
    if unmatched:
        raise ConfigError(
            f"--rename-table (or [tables] renames) names a table that "
            f"is not in the current field-parameter table list: "
            f"{', '.join(sorted(unmatched))}. Current tables: "
            f"{list(tables)}."
        )
    return tuple(result)


def _reject_unknown_keys(
    path: Path, section: str, present: dict, known: set[str]
) -> None:
    """Fail loudly on a typo'd key instead of silently ignoring it.

    A misspelled key (``line-color`` for ``line_color``, a wrong case on
    a section name) previously just vanished: the value was never read,
    no default was overridden, and the tool reported nothing had
    changed. That reads as "the config had no effect" with zero signal
    of why.
    """
    unknown = set(present) - known
    if unknown:
        raise ConfigError(
            f"{path} has unknown key(s) under [{section}]: "
            f"{', '.join(sorted(unknown))}. Valid keys are: "
            f"{', '.join(sorted(known))}."
        )


def load_config_file(path: Path) -> dict[str, Any]:
    """Read a plotstyler.toml file into a flat override dict."""
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(
            f"{path} is not valid TOML: {exc}. Fix the syntax and rerun."
        ) from exc

    unknown_sections = set(raw) - _KNOWN_SECTIONS
    if unknown_sections:
        raise ConfigError(
            f"{path} has unknown section(s): "
            f"{', '.join(sorted(unknown_sections))}. Valid sections are "
            f"[tables], [targets], and [style]."
        )

    overrides: dict[str, Any] = {}
    tables = raw.get("tables", {})
    _reject_unknown_keys(path, "tables", tables, _KNOWN_TABLES_KEYS)
    if "field_parameters" in tables:
        overrides["field_parameter_tables"] = tuple(tables["field_parameters"])
    if "renames" in tables:
        overrides["table_renames"] = dict(tables["renames"])

    targets = raw.get("targets", {})
    _reject_unknown_keys(path, "targets", targets, _KNOWN_TARGETS_KEYS)
    if "visual_types" in targets:
        overrides["visual_types"] = tuple(targets["visual_types"])
    if "exclude_current_roles" in targets:
        overrides["exclude_current_roles"] = tuple(
            targets["exclude_current_roles"]
        )

    style = raw.get("style", {})
    _reject_unknown_keys(path, "style", style, _KNOWN_STYLE_KEYS)
    for key in (
        "line_color",
        "label_color",
        "label_background",
        "label_transparency",
        "show_labels",
        "theme_color_id",
        "theme_color_percent",
    ):
        if key in style:
            overrides[key] = style[key]
    if "palette" in style:
        overrides["palette"] = tuple(style["palette"])
    if "colors" in style:
        if not isinstance(style["colors"], dict):
            raise ConfigError(
                f"{path} [style] colors must be a table of "
                f"\"Table.Measure\" = \"#RRGGBB\" pairs, for example a "
                f"[style.colors] section."
            )
        overrides["color_pins"] = dict(style["colors"])
    return overrides


def build_config(
    config_path: Path | None = None,
    table_renames: dict[str, str] | None = None,
    color_pins: dict[str, str] | None = None,
    **cli_overrides: Any,
) -> StylerConfig:
    """Merge defaults, an optional config file, and CLI overrides.

    ``cli_overrides`` entries with value ``None`` are ignored, so unset CLI
    flags never mask config-file values. ``table_renames`` (from
    ``--rename-table``) is applied last, on top of whatever
    ``field_parameter_tables`` resolved to from the config file, an
    explicit ``--table`` override, or the built-in default, so renaming
    one table never requires respecifying the other two. ``color_pins``
    (from ``--color``) merge over the file's ``[style.colors]`` per key.
    """
    values: dict[str, Any] = {}
    file_renames: dict[str, str] = {}
    file_pins: dict[str, str] = {}
    if config_path is not None:
        if not config_path.is_file():
            raise ConfigError(
                f"config file {config_path} does not exist. Check the "
                f"--config path."
            )
        file_overrides = load_config_file(config_path)
        file_renames = file_overrides.pop("table_renames", {})
        file_pins = file_overrides.pop("color_pins", {})
        values.update(file_overrides)
    values.update({k: v for k, v in cli_overrides.items() if v is not None})

    renames = {**file_renames, **(table_renames or {})}
    if renames:
        base_tables = values.get(
            "field_parameter_tables", DEFAULT_FIELD_PARAMETER_TABLES
        )
        values["field_parameter_tables"] = apply_table_renames(
            base_tables, renames
        )

    pins = {**file_pins, **(color_pins or {})}
    if pins:
        values["colors"] = tuple(sorted(pins.items()))

    values["explicit"] = frozenset(values)
    config = StylerConfig(**values)
    config.validate()
    return config
