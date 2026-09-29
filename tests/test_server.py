"""
Unit and integration tests for FastMCP server tools.
"""

from __future__ import annotations

from pathlib import Path
from blip_mcp.server import mcp, list_devices, get_status, send_file


def test_mcp_tool_registration():
    # Verify tools are registered in FastMCP
    tool_names = [t.name for t in mcp._tool_manager.list_tools()]
    assert "send_file" in tool_names
    assert "list_devices" in tool_names
    assert "get_status" in tool_names


def test_mcp_list_devices():
    devices = list_devices()
    assert isinstance(devices, list)
    assert len(devices) >= 1
    has_primary = any(d["is_primary"] for d in devices)
    assert has_primary is True
    # Verify name and kind are present
    for d in devices:
        assert "name" in d
        assert "kind" in d


def test_mcp_get_status():
    status = get_status()
    assert isinstance(status, dict)
    assert status["is_running"] is True
    assert status["executable_found"] is True
    assert "recent_transfers" in status


def test_mcp_send_file(tmp_path: Path):
    test_file = tmp_path / "mcp_tool_test.txt"
    test_file.write_text("FastMCP automated test")

    res = send_file(file_path=str(test_file), device="iPhone")
    assert res["success"] is True
    assert res["device_id"] is not None
    assert str(test_file.resolve()) in res["files"]
