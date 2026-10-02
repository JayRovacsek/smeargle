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
