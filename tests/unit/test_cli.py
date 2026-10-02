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


def test_subcommand_reports_not_implemented(capsys):
    code = main(["run"])
    err = capsys.readouterr().err
    assert code == 2
    assert "not implemented in Phase 1" in err


def test_unknown_option_is_usage_error():
    code = main(["--nope"])
    assert code == 2


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
