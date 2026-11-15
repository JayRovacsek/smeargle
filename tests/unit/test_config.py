from pathlib import Path

from smeargle.config import JevSettings, Settings


def test_defaults():
    s = Settings.load()
    assert s.mapping.extract_gate_threshold == 0.5
    assert s.state_dir == Path(".smeargle")
    assert s.llm.temperature == 0.0
    assert s.execution.log_format == "text"


def test_jev_transport_defaults_to_chat():
    assert JevSettings().transport == "chat"


def test_jev_transport_env_override(monkeypatch):
    monkeypatch.setenv("SMEARGLE_JEV__TRANSPORT", "systemone")
    s = Settings.load()
    assert s.jev.transport == "systemone"


def test_file_overrides_defaults(tmp_path):
    cfg = tmp_path / "smeargle.toml"
    cfg.write_text("[mapping]\nextract_gate_threshold = 0.6\n")
    s = Settings.load(config_file=cfg)
    assert s.mapping.extract_gate_threshold == 0.6


def test_env_overrides_file(tmp_path, monkeypatch):
    cfg = tmp_path / "smeargle.toml"
    cfg.write_text("[mapping]\nextract_gate_threshold = 0.6\n")
    monkeypatch.setenv("SMEARGLE_MAPPING__EXTRACT_GATE_THRESHOLD", "0.7")
    s = Settings.load(config_file=cfg)
    assert s.mapping.extract_gate_threshold == 0.7


def test_cli_overrides_env_and_file(tmp_path, monkeypatch):
    cfg = tmp_path / "smeargle.toml"
    cfg.write_text("[mapping]\nextract_gate_threshold = 0.6\n")
    monkeypatch.setenv("SMEARGLE_MAPPING__EXTRACT_GATE_THRESHOLD", "0.7")
    s = Settings.load(
        config_file=cfg,
        overrides={"mapping": {"extract_gate_threshold": 0.8}},
    )
    assert s.mapping.extract_gate_threshold == 0.8


def test_yaml_file_is_supported(tmp_path):
    cfg = tmp_path / "smeargle.yaml"
    cfg.write_text("mapping:\n  mapped_threshold: 0.65\n")
    s = Settings.load(config_file=cfg)
    assert s.mapping.mapped_threshold == 0.65


def test_secrets_are_referenced_not_stored():
    s = Settings.load()
    assert not hasattr(s.llm, "api_key")
    assert not hasattr(s.jev, "api_key")
