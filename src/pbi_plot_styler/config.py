"""Configuration model and loading for pbi-plot-styler.

Precedence (highest wins): CLI flags > config file > built-in defaults.
"""
from __future__ import annotations

import dataclasses
import re
import sys
from pathlib import Path
from typing import Any

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
        if not isinstance(self.label_transparency, int) or not (
            0 <= self.label_transparency <= 100
        ):
            raise ConfigError(
                f"label_transparency is set to {self.label_transparency!r}, "
                f"which is out of range. Use an integer between 0 "
                f"(opaque) and 100 (fully transparent)."
            )

    # -- per-measure color resolution -------------------------------------
    def line_color_for(self, measure_index: int) -> str:
        """The series color for the measure at ``measure_index`` (sorted order)."""
        if self.palette:
            return self.palette[measure_index % len(self.palette)]
        return self.line_color

    def label_background_for(self, measure_index: int) -> str:
        """The label background for a measure: explicit hex, or match the line."""
        if self.label_background is not None:
            return self.label_background
        return self.line_color_for(measure_index)


def load_config_file(path: Path) -> dict[str, Any]:
    """Read a plotstyler.toml file into a flat override dict."""
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(
            f"{path} is not valid TOML: {exc}. Fix the syntax and rerun."
        ) from exc

    overrides: dict[str, Any] = {}
    tables = raw.get("tables", {})
    if "field_parameters" in tables:
        overrides["field_parameter_tables"] = tuple(tables["field_parameters"])

    targets = raw.get("targets", {})
    if "visual_types" in targets:
        overrides["visual_types"] = tuple(targets["visual_types"])

    style = raw.get("style", {})
    for key in (
        "line_color",
        "label_color",
        "label_background",
        "label_transparency",
        "show_labels",
    ):
        if key in style:
            overrides[key] = style[key]
    if "palette" in style:
        overrides["palette"] = tuple(style["palette"])
    return overrides


def build_config(
    config_path: Path | None = None, **cli_overrides: Any
) -> StylerConfig:
    """Merge defaults, an optional config file, and CLI overrides.

    ``cli_overrides`` entries with value ``None`` are ignored, so unset CLI
    flags never mask config-file values.
    """
    values: dict[str, Any] = {}
    if config_path is not None:
        if not config_path.is_file():
            raise ConfigError(
                f"config file {config_path} does not exist. Check the "
                f"--config path."
            )
        values.update(load_config_file(config_path))
    values.update({k: v for k, v in cli_overrides.items() if v is not None})
    config = StylerConfig(**values)
    config.validate()
    return config
