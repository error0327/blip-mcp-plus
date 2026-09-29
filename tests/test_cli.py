"""
Unit and integration tests for the blip-mcp CLI.
"""

from __future__ import annotations

import json
from pathlib import Path
from click.testing import CliRunner

from blip_mcp.cli import cli


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "blip-mcp" in result.output
    assert "devices" in result.output
    assert "send" in result.output


def test_cli_devices_json():
    runner = CliRunner()
    result = runner.invoke(cli, ["devices", "--json"])
    assert result.exit_code == 0

    data = json.loads(result.output)
    assert isinstance(data, list)
    assert len(data) >= 1
    # Check required fields
    for dev in data:
        assert "name" in dev
        assert "device_id" in dev
        assert "peer_id" in dev


def test_cli_status_json():
    runner = CliRunner()
    result = runner.invoke(cli, ["status", "--json"])
    assert result.exit_code == 0

    data = json.loads(result.output)
    assert isinstance(data, dict)
    assert data["is_running"] is True
    assert "user_email" in data


def test_cli_send_missing_file():
    runner = CliRunner()
    result = runner.invoke(cli, ["send", "non_existent_random_file_999.txt", "--json"])
    assert result.exit_code != 0


def test_cli_send_success(tmp_path: Path):
    f = tmp_path / "cli_test_file.txt"
    f.write_text("CLI test payload")

    runner = CliRunner()
    result = runner.invoke(cli, ["send", str(f), "--json"])
    assert result.exit_code == 0

    data = json.loads(result.output)
    assert data["success"] is True
    assert len(data["files"]) == 1
    assert data["device_id"] is not None
