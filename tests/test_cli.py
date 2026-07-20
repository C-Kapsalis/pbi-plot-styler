"""End-to-end CLI behavior: apply, dry-run, config file, overrides, zip."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

from click.testing import CliRunner

from pbi_plot_styler.cli import main

from conftest import EXPECTED_KEYS


def _run(*args: str):
    return CliRunner().invoke(main, [str(a) for a in args])


def _visual(report_dir: Path, page: str, visual: str) -> dict:
    path = (
        report_dir / "definition" / "pages" / page / "visuals" / visual / "visual.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def _snapshot(report_dir: Path) -> dict[str, str]:
    return {
        str(p.relative_to(report_dir)): p.read_text(encoding="utf-8")
        for p in sorted(report_dir.rglob("*"))
        if p.is_file()
    }


# -- apply (default mode) ------------------------------------------------------
def test_apply_styles_every_combo_chart(report_dir):
    result = _run(report_dir)
    assert result.exit_code == 0, result.output
    assert "Restyled 2/2 visual(s)" in result.output

    for page, visual in (
        ("monthlyperformance", "combo01"),
        ("seasonaltrends", "combo02"),
    ):
        data = _visual(report_dir, page, visual)
        objects = data["visual"]["objects"]
        assert [d["selector"]["metadata"] for d in objects["dataPoint"]] == EXPECTED_KEYS
        assert len(objects["labels"]) == len(EXPECTED_KEYS) + 1


def test_apply_is_idempotent(report_dir):
    first = _run(report_dir)
    assert first.exit_code == 0

    before = _snapshot(report_dir)
    second = _run(report_dir)
    assert second.exit_code == 0
    assert "Restyled 0/2 visual(s); 2 already styled" in second.output
    assert _snapshot(report_dir) == before


def test_non_target_visuals_untouched(report_dir):
    slicer_before = _visual(report_dir, "monthlyperformance", "slicer01")
    assert _run(report_dir).exit_code == 0
    assert _visual(report_dir, "monthlyperformance", "slicer01") == slicer_before


# -- dry run -------------------------------------------------------------------
def test_dry_run_leaves_files_untouched_and_exits_1(report_dir):
    before = _snapshot(report_dir)
    result = _run(report_dir, "--dry-run")
    assert result.exit_code == 1
    assert _snapshot(report_dir) == before
    # A unified diff of the pending rewrite is shown.
    assert "--- definition/pages/monthlyperformance/visuals/combo01/visual.json" in result.output
    assert "+++ definition/pages/monthlyperformance/visuals/combo01/visual.json (styled)" in result.output
    assert "2/2 visual(s) would change." in result.output


def test_dry_run_after_apply_exits_0(report_dir):
    assert _run(report_dir).exit_code == 0
    result = _run(report_dir, "--dry-run")
    assert result.exit_code == 0
    assert "All 2 visual(s) already styled." in result.output


# -- CLI flag overrides ----------------------------------------------------------
def test_cli_color_flags(report_dir):
    result = _run(
        report_dir,
        "--line-color", "#00AA55",
        "--label-color", "#FFFFFF",
        "--label-background", "#003322",
        "--label-transparency", "0",
        "--hide-labels",
    )
    assert result.exit_code == 0, result.output

    objects = _visual(report_dir, "monthlyperformance", "combo01")["visual"]["objects"]
    fill = objects["dataPoint"][0]["properties"]["fill"]["solid"]["color"]
    assert fill["expr"]["Literal"]["Value"] == "'#00AA55'"

    default = objects["labels"][0]["properties"]
    assert default["show"]["expr"]["Literal"]["Value"] == "false"
    assert default["color"]["solid"]["color"]["expr"]["Literal"]["Value"] == "'#FFFFFF'"

    per_measure = objects["labels"][1]["properties"]
    assert (
        per_measure["backgroundColor"]["solid"]["color"]["expr"]["Literal"]["Value"]
        == "'#003322'"
    )
    assert per_measure["backgroundTransparency"]["expr"]["Literal"]["Value"] == "0L"


def test_invalid_hex_exits_2(report_dir):
    result = _run(report_dir, "--line-color", "teal")
    assert result.exit_code == 2  # error, distinct from dry-run drift (1)
    assert "hex color" in result.output


def test_missing_field_parameter_tables_exit_2(report_dir):
    result = _run(report_dir, "--table", "No Such Table")
    assert result.exit_code == 2
    assert "No Such Table" in result.output


# -- config file -----------------------------------------------------------------
def test_config_file_overrides(project, report_dir, tmp_path):
    # Rename the field-parameter tables, as a fork of the template might.
    tables_dir = project / "Roastery.SemanticModel" / "definition" / "tables"
    renames = {
        "x-Plot Specific 1": "Axis Fields",
        "x-Plot Specific 2": "Legend Fields",
        "y-Plot Specific": "Metric Fields",
    }
    for old, new in renames.items():
        f = tables_dir / f"{old}.tmdl"
        content = f.read_text(encoding="utf-8").replace(old, new)
        f.unlink()
        (tables_dir / f"{new}.tmdl").write_text(content, encoding="utf-8")

    config_file = tmp_path / "plotstyler.toml"
    config_file.write_text(
        "\n".join(
            [
                "[tables]",
                'field_parameters = ["Axis Fields", "Legend Fields", "Metric Fields"]',
                "",
                "[style]",
                'palette = ["#7A4419", "#C58F5D"]',
                'label_color = "#FFF8F0"',
                "label_transparency = 45",
                "",
                "[targets]",
                'visual_types = ["lineClusteredColumnComboChart", "lineStackedColumnComboChart"]',
            ]
        ),
        encoding="utf-8",
    )

    result = _run(report_dir, "--config", config_file)
    assert result.exit_code == 0, result.output

    objects = _visual(report_dir, "monthlyperformance", "combo01")["visual"]["objects"]
    fills = [
        d["properties"]["fill"]["solid"]["color"]["expr"]["Literal"]["Value"]
        for d in objects["dataPoint"]
    ]
    assert fills[:2] == ["'#7A4419'", "'#C58F5D'"]
    assert (
        objects["labels"][1]["properties"]["backgroundTransparency"]["expr"]["Literal"]["Value"]
        == "45L"
    )


def test_typo_d_config_key_fails_loudly(report_dir, tmp_path):
    # A hyphen instead of an underscore (matching the --line-color flag's
    # own spelling) used to be silently ignored: the file parsed, the key
    # was skipped, and the run reported nothing had changed.
    config_file = tmp_path / "plotstyler.toml"
    config_file.write_text('[style]\nline-color = "#FF0000"\n', encoding="utf-8")

    result = _run(report_dir, "--config", config_file)
    assert result.exit_code == 2
    assert "line-color" in result.output


def test_typo_d_config_section_fails_loudly(report_dir, tmp_path):
    config_file = tmp_path / "plotstyler.toml"
    config_file.write_text('[Style]\nline_color = "#FF0000"\n', encoding="utf-8")

    result = _run(report_dir, "--config", config_file)
    assert result.exit_code == 2
    assert "Style" in result.output


def test_cli_flags_beat_config_file(report_dir, tmp_path):
    config_file = tmp_path / "plotstyler.toml"
    config_file.write_text('[style]\nline_color = "#123456"\n', encoding="utf-8")

    result = _run(report_dir, "--config", config_file, "--line-color", "#654321")
    assert result.exit_code == 0, result.output

    objects = _visual(report_dir, "monthlyperformance", "combo01")["visual"]["objects"]
    fill = objects["dataPoint"][0]["properties"]["fill"]["solid"]["color"]
    assert fill["expr"]["Literal"]["Value"] == "'#654321'"


# -- zip -------------------------------------------------------------------------
def test_zip_contains_styled_report(report_dir, tmp_path):
    out = tmp_path / "styled.zip"
    result = _run(report_dir, "--zip", out)
    assert result.exit_code == 0, result.output
    assert out.is_file()

    with zipfile.ZipFile(out) as archive:
        names = archive.namelist()
        assert "Roastery.Report/definition.pbir" in names
        combo = json.loads(
            archive.read(
                "Roastery.Report/definition/pages/monthlyperformance/"
                "visuals/combo01/visual.json"
            ).decode("utf-8")
        )
    datapoints = combo["visual"]["objects"]["dataPoint"]
    assert [d["selector"]["metadata"] for d in datapoints] == EXPECTED_KEYS


def test_dry_run_zip_writes_archive_but_not_files(report_dir, tmp_path):
    before = _snapshot(report_dir)
    out = tmp_path / "styled.zip"
    result = _run(report_dir, "--dry-run", "--zip", out)
    assert result.exit_code == 1  # drift is still reported
    assert _snapshot(report_dir) == before
    assert out.is_file()

    with zipfile.ZipFile(out) as archive:
        combo = json.loads(
            archive.read(
                "Roastery.Report/definition/pages/seasonaltrends/"
                "visuals/combo02/visual.json"
            ).decode("utf-8")
        )
    # The archive already carries the styled content.
    labels = combo["visual"]["objects"]["labels"]
    assert len(labels) == len(EXPECTED_KEYS) + 1


# -- byte fidelity -----------------------------------------------------------------
def _combo01_path(report_dir: Path) -> Path:
    return (
        report_dir
        / "definition"
        / "pages"
        / "monthlyperformance"
        / "visuals"
        / "combo01"
        / "visual.json"
    )


def test_apply_preserves_absent_trailing_newline(report_dir):
    # Power BI Desktop saves visual.json WITHOUT a trailing newline; the
    # styler must not add one (a byte change outside the rebuilt arrays).
    path = _combo01_path(report_dir)
    path.write_bytes(path.read_bytes().rstrip(b"\n"))

    assert _run(report_dir).exit_code == 0
    styled = path.read_bytes()
    assert not styled.endswith(b"\n")
    assert json.loads(styled.decode("utf-8"))  # still valid JSON

    # And the second pass sees nothing left to do.
    result = _run(report_dir, "--dry-run")
    assert result.exit_code == 0, result.output


def test_apply_keeps_existing_trailing_newline(report_dir):
    path = _combo01_path(report_dir)
    assert path.read_bytes().endswith(b"\n")  # fixture convention
    assert _run(report_dir).exit_code == 0
    assert path.read_bytes().endswith(b"\n")


def test_apply_never_rewrites_line_endings(report_dir):
    # Desktop-saved PBIP files use LF; writing through text mode would
    # silently turn every line ending into os.linesep (CRLF on Windows).
    assert _run(report_dir).exit_code == 0
    assert b"\r" not in _combo01_path(report_dir).read_bytes()
