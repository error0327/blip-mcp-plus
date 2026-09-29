"""
Unit tests for BlipClient core discovery, parsing, and execution.
"""

from __future__ import annotations

import base64
import json
import pytest
from pathlib import Path

from blip_mcp.core import BlipClient, Device, BlipContext, TransferResult


def test_find_executable():
    exe = BlipClient.find_executable()
    # On this machine, Blip is installed
    assert exe is not None
    assert exe.exists()


def test_find_state_dir():
    state_dir = BlipClient.find_state_dir()
    assert state_dir is not None
    assert state_dir.is_dir()


def test_jwt_extraction_mock():
    header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=")
    payload = base64.urlsafe_b64encode(
        b'{"user_id":"test-user-123","device_id":"test-device-456","user_email":"test@example.com"}'
    ).rstrip(b"=")
    signature = b"fake-sig"
    token = b"eyJ" + header[3:] + b"." + payload + b"." + signature

    data = b"prefix_noise_" + token + b"_suffix_noise"
    extracted = BlipClient._extract_jwt_payload(data)

    assert extracted is not None
    assert extracted["user_id"] == "test-user-123"
    assert extracted["device_id"] == "test-device-456"
    assert extracted["user_email"] == "test@example.com"


def test_get_context():
    client = BlipClient()
    ctx = client.get_context()

    assert isinstance(ctx, BlipContext)
    assert ctx.user_id is not None
    assert ctx.local_device_id is not None
    assert ctx.primary_peer is not None
    assert ctx.primary_peer.is_primary is True
    assert ctx.primary_peer.is_local is False
    assert ctx.primary_peer.device_id != ctx.local_device_id


def test_send_validation_missing_file():
    client = BlipClient()
    res = client.send(files=["non_existent_file_12345.xyz"])
    assert res.success is False
    assert "File not found" in res.message


def test_send_validation_empty_files():
    client = BlipClient()
    res = client.send(files=[])
    assert res.success is False
    assert "No files specified" in res.message


def test_send_valid_file(tmp_path: Path):
    test_file = tmp_path / "core_test.txt"
    test_file.write_text("Automated core test payload.")

    client = BlipClient()
    res = client.send(files=test_file)

    assert res.success is True
    assert res.device_id is not None
    assert str(test_file.resolve()) in res.files
