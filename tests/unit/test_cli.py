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


def test_extract_and_map_remain_thin_placeholders(capsys):
    assert main(["extract"]) == 2
    assert main(["map"]) == 2
    assert "not implemented" in capsys.readouterr().err


def test_help_lists_pipeline_options(capsys):
    main(["--help"])
    out = capsys.readouterr().out
    for option in ("--llm-endpoint", "--jev-endpoint", "--mapped-threshold", "--concurrency"):
        assert option in out


def _minimal_inputs(tmp_path):
    document = tmp_path / "a.txt"
    document.write_text("MUST x", encoding="utf-8")
    catalog = tmp_path / "c.json"
    catalog.write_text('{"catalog": {"name": "V", "securityControls": []}}', encoding="utf-8")
    return document, catalog


def test_run_requires_llm_endpoint(tmp_path, capsys):
    document, catalog = _minimal_inputs(tmp_path)
    code = main(
        [
            "--state-dir", str(tmp_path / "s"), "--output", str(tmp_path / "o"),
            "--jev-endpoint", "https://jev.example",
            "run", "-i", str(document), "-c", str(catalog),
        ]
    )
    assert code == 2
    assert "--llm-endpoint" in capsys.readouterr().err


def test_run_requires_jev_endpoint(tmp_path, capsys):
    document, catalog = _minimal_inputs(tmp_path)
    code = main(
        [
            "--state-dir", str(tmp_path / "s"), "--output", str(tmp_path / "o"),
            "--llm-endpoint", "https://llm.example",
            "run", "-i", str(document), "-c", str(catalog),
        ]
    )
    assert code == 2
    assert "--jev-endpoint" in capsys.readouterr().err


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


def test_run_missing_input_returns_input_exit_code(tmp_path):
    catalog = tmp_path / "vendor.json"
    catalog.write_text(
        '{"catalog": {"name": "V", "securityControls": []}}', encoding="utf-8"
    )
    code = main(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "--output",
            str(tmp_path / "out"),
            "--llm-endpoint",
            "https://llm.example",
            "--jev-endpoint",
            "https://jev.example",
            "run",
            "-c",
            str(catalog),
            "-i",
            str(tmp_path / "missing.txt"),
        ]
    )
    assert code == 3


def test_validate_missing_catalog_returns_catalog_exit_code(tmp_path):
    code = main(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "validate",
            "-c",
            str(tmp_path / "missing.json"),
        ]
    )
    assert code == 4


def test_validate_malformed_catalog_returns_catalog_exit_code(tmp_path):
    malformed = tmp_path / "malformed.json"
    malformed.write_text('{"catalog": {}}', encoding="utf-8")
    code = main(
        ["--state-dir", str(tmp_path / "state"), "validate", "-c", str(malformed)]
    )
    assert code == 4


def _phase4_settings(tmp_path):
    from smeargle.config import Settings

    settings = Settings.load()
    settings.state_dir = tmp_path / "state"
    settings.output = tmp_path / "out"
    settings.llm.endpoint = "https://llm.example"
    settings.jev.endpoint = "https://jev.example"
    return settings


def test_llm_temperature_is_folded_into_config_hash(tmp_path):
    from smeargle.pipeline import run as run_pipeline

    digest_a = run_pipeline.config_hash(
        run_pipeline.redact(run_pipeline.config_snapshot(_phase4_settings(tmp_path)))
    )
    settings_b = _phase4_settings(tmp_path)
    settings_b.llm.temperature = 0.7
    digest_b = run_pipeline.config_hash(
        run_pipeline.redact(run_pipeline.config_snapshot(settings_b))
    )
    assert digest_a != digest_b


def test_nomination_cap_option_is_accepted(tmp_path, capsys):
    document = tmp_path / "a.txt"
    document.write_text("MUST x", encoding="utf-8")
    catalog = tmp_path / "c.json"
    catalog.write_text('{"catalog": {"securityControls": []}}', encoding="utf-8")
    code = main(
        [
            "--state-dir", str(tmp_path / "s"), "--output", str(tmp_path / "o"),
            "--nomination-cap", "5",
            "run", "-i", str(document), "-c", str(catalog),
        ]
    )
    assert code == 2
    assert "--llm-endpoint" in capsys.readouterr().err
