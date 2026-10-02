from smeargle.cli import main


def test_version_exits_zero(capsys):
    code = main(["--version"])
    assert code == 0
    assert "smeargle" in capsys.readouterr().out


def test_help_lists_subcommands(capsys):
    code = main(["--help"])
    out = capsys.readouterr().out
    assert code == 0
    for command in ("run", "extract", "map", "resume", "validate", "status"):
        assert command in out


def test_extract_reports_not_implemented(capsys):
    code = main(["extract"])
    err = capsys.readouterr().err
    assert code == 2
    assert "not implemented in Phase 2" in err


def test_unknown_option_is_usage_error():
    code = main(["--nope"])
    assert code == 2


def test_run_requires_an_input(tmp_path, capsys):
    code = main(
        ["--state-dir", str(tmp_path / "state"), "--output", str(tmp_path / "out"), "run"]
    )
    assert code == 2
    assert "requires at least one --input" in capsys.readouterr().err


def test_status_without_state_reports_nothing(tmp_path, capsys):
    code = main(["--state-dir", str(tmp_path / "missing"), "status"])
    assert code == 0
    assert "no runs recorded" in capsys.readouterr().out


def test_validate_rejects_invalid_catalog(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"catalog": {"metadata": {"title": "T"}}}', encoding="utf-8")
    code = main(
        ["--state-dir", str(tmp_path / "state"), "validate", "-c", str(bad)]
    )
    assert code == 4


def test_invalid_log_format_is_usage_error(capsys):
    code = main(["--log-format", "xml", "run"])
    err = capsys.readouterr().err
    assert code == 2
    assert "log-format" in err


def test_missing_config_file_is_usage_error(tmp_path, capsys):
    code = main(["--config", str(tmp_path / "nope.toml"), "run"])
    err = capsys.readouterr().err
    assert code == 2
    assert "not found" in err


def test_unsupported_config_extension_is_usage_error(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text("{}")
    code = main(["--config", str(path), "run"])
    err = capsys.readouterr().err
    assert code == 2
    assert "invalid configuration" in err


def test_invalid_config_value_is_usage_error(tmp_path, capsys):
    path = tmp_path / "bad.toml"
    path.write_text("[mapping]\nextract_gate_threshold = 5.0\n")
    code = main(["--config", str(path), "run"])
    err = capsys.readouterr().err
    assert code == 2
    assert "invalid configuration" in err
