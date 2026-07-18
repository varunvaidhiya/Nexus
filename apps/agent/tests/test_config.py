from pathlib import Path

import pytest

from nexus_agent.config import load_config


def test_load_config(tmp_path: Path) -> None:
    config_file = tmp_path / "nexus-agent.toml"
    config_file.write_text(
        """
[backend]
url = "http://localhost:8000/"
token = "nxd_test"

[agent]
machine_name = "laptop"
interval_seconds = 60
state_path = "/tmp/state.json"

[tools.claude_code]
enabled = true
root = "/some/root"

[tools.cursor]
enabled = false
"""
    )
    config = load_config(config_file)
    assert config.backend_url == "http://localhost:8000"  # trailing slash stripped
    assert config.token == "nxd_test"
    assert config.machine_name == "laptop"
    assert config.interval_seconds == 60
    assert config.state_path == Path("/tmp/state.json")
    assert config.tools["claude_code"].enabled
    assert config.tools["claude_code"].root == Path("/some/root")
    assert not config.tools["cursor"].enabled


def test_defaults(tmp_path: Path) -> None:
    config_file = tmp_path / "nexus-agent.toml"
    config_file.write_text('[backend]\nurl = "http://x"\ntoken = "t"\n')
    config = load_config(config_file)
    assert config.machine_name == "local"
    assert list(config.tools) == ["claude_code"]
    assert config.tools["claude_code"].enabled


def test_missing_token_rejected(tmp_path: Path) -> None:
    config_file = tmp_path / "nexus-agent.toml"
    config_file.write_text('[backend]\nurl = "http://x"\n')
    with pytest.raises(ValueError, match="url and token"):
        load_config(config_file)


def test_missing_file_rejected(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.toml")
