import sys
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from blip_mcp import chat
from blip_mcp.core import BlipContext, Device, TransferResult

URL = "https://files.oaiusercontent.com/example"
PHONE = Device("device", "user", False, True, name="Phone")


@pytest.mark.asyncio
async def test_published_stdio_tools():
    params = StdioServerParameters(command=str(Path(sys.executable).with_name(
        "blip-chat.exe" if sys.platform == "win32" else "blip-chat")))
    async with stdio_client(params) as streams, ClientSession(*streams) as session:
        await session.initialize()
        tools = {t.name: t for t in (await session.list_tools()).tools}
        assert set(tools) == {"send_chat_file", "list_devices"}
        tool = tools["send_chat_file"]
        assert tool.meta["openai/fileParams"] == ["file"]
        assert set(tool.inputSchema["$defs"]["ChatFile"]["required"]) == {"download_url", "file_id"}


def test_stage_and_dispatch(tmp_path, monkeypatch):
    data = b"%PDF-1.7\n" + bytes(range(256)) * 1024
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=data)))
    monkeypatch.setattr(chat.httpx, "Client", lambda **kw: client)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(chat.blip, "get_context", lambda: BlipContext(devices=[PHONE]))
    def dispatch(path, peer_id):
        assert path.read_bytes() == data
        assert peer_id == PHONE.peer_id
        return TransferResult(True, "Queued", [str(path)])
    monkeypatch.setattr(chat.blip, "send", dispatch)
    result = chat.send_chat_file(dict(download_url=URL, file_id="example", file_name="../report.pdf"))
    assert result == {"status": "dispatched", "recipient": "Phone", "file_name": "report.pdf"}
    assert next(tmp_path.rglob("report.pdf")).read_bytes() == data


@pytest.mark.parametrize("response", [
    httpx.Response(302, headers={"location": "http://localhost/private"}),
    httpx.Response(200, content=b"123456"),
    httpx.Response(403),
])
def test_failed_download_never_dispatches(tmp_path, monkeypatch, response):
    client = httpx.Client(transport=httpx.MockTransport(lambda r: response))
    monkeypatch.setattr(chat.httpx, "Client", lambda **kw: client)
    monkeypatch.setattr(chat, "MAX_BYTES", 5)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(chat.blip, "get_context", lambda: BlipContext(devices=[PHONE]))
    send = Mock()
    monkeypatch.setattr(chat.blip, "send", send)
    with pytest.raises(ValueError):
        chat.send_chat_file(dict(download_url=URL, file_id="example"))
    send.assert_not_called()
    assert list((tmp_path / ".blip-mcp" / "outbox").iterdir()) == []


def test_ambiguous_recipient(monkeypatch):
    monkeypatch.setattr(chat.blip, "get_context", lambda: BlipContext(devices=[PHONE, PHONE]))
    with pytest.raises(ValueError, match="Select one"):
        chat.send_chat_file(dict(download_url=URL, file_id="example"))
