"""Send files supplied by ChatGPT through the local Blip desktop app."""

import logging
import os
import re
import tempfile
import time
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from typing_extensions import NotRequired, TypedDict

from blip_mcp.core import BlipClient

mcp = FastMCP("Chat file sender for Blip")
blip = BlipClient()
MAX_BYTES = 256 * 1024 * 1024


class ChatFile(TypedDict):
    download_url: str
    file_id: str
    file_name: NotRequired[str]
    mime_type: NotRequired[str]


def checked_url(raw: str) -> httpx.URL:
    url = httpx.URL(raw)
    host = url.host.lower()
    extra = {h.strip().lower() for h in os.getenv("BLIP_CHAT_FILE_HOSTS", "").split(",") if h.strip()}
    allowed = host == "oaiusercontent.com" or host.endswith(".oaiusercontent.com") or host in extra
    if not allowed or url.scheme != "https" or url.userinfo or url.port not in (None, 443):
        raise ValueError("Unsupported file download host. Check BLIP_CHAT_FILE_HOSTS on the PC.")
    return url


def safe_name(value: str) -> str:
    name = re.sub(r'[^\w .()-]', "_", value.replace("\\", "/").split("/")[-1]).strip(" .")[:120].rstrip(" .")
    if not name:
        return "chat-file"
    if re.fullmatch(r"CON|AUX|PRN|NUL|COM[0-9¹²³]|LPT[0-9¹²³]", name.split(".")[0].rstrip(), re.I):
        return "_" + name
    return name


def download(client: httpx.Client, raw: str, path: Path) -> None:
    deadline = time.monotonic() + 300
    url = checked_url(raw)
    for _ in range(5):
        with client.stream("GET", url, headers={"Accept-Encoding": "identity"}) as response:
            if response.is_redirect and "location" in response.headers:
                url = checked_url(str(url.join(response.headers["location"])))
                continue
            if response.status_code != 200:
                raise ValueError(f"File download returned HTTP {response.status_code}. Select the file again.")
            if response.headers.get("content-encoding", "identity") != "identity":
                raise ValueError("Unexpected file encoding.")
            length = response.headers.get("content-length")
            if length and int(length) > MAX_BYTES:
                raise ValueError("File exceeds the 256 MiB limit.")
            total = 0
            with path.open("xb") as output:
                for chunk in response.iter_bytes(chunk_size=65536):
                    total += len(chunk)
                    if total > MAX_BYTES or time.monotonic() > deadline:
                        raise ValueError("File exceeded the size or transfer time limit.")
                    output.write(chunk)
            if length and total != int(length):
                raise ValueError("Incomplete download.")
            return
    raise ValueError("Too many download redirects.")


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
def list_devices() -> list[dict[str, str]]:
    """List available Blip recipients and their device IDs."""
    return [{"name": d.name, "id": d.device_id} for d in blip.get_context().devices if not d.is_local]


@mcp.tool(meta={"openai/fileParams": ["file"]}, annotations=ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, openWorldHint=True, idempotentHint=False))
def send_chat_file(file: ChatFile, device: str = "") -> dict[str, str]:
    """Send a file provided by the current chat to a paired Blip device. Specify an exact device name or ID when several are paired."""
    peers = [d for d in blip.get_context().devices if not d.is_local]
    if device:
        peers = [d for d in peers if device.casefold() in (d.name.casefold(), d.device_id.casefold())]
    if len(peers) != 1:
        raise ValueError("Select one paired recipient by exact name or ID using list_devices.")
    peer = peers[0]
    root = Path.home() / ".blip-mcp" / "outbox"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(dir=root))
    path = folder / safe_name(file.get("file_name") or "chat-file")
    try:
        with httpx.Client(timeout=30, trust_env=False) as client:
            download(client, file["download_url"], path)
    except Exception as exc:
        path.unlink(missing_ok=True)
        folder.rmdir()
        if isinstance(exc, httpx.HTTPError) or isinstance(exc, httpx.InvalidURL):
            raise ValueError("File download failed. Select the chat file again.") from None
        raise
    # Blip can read the file after its command exits, including on a resumed transfer.
    result = blip.send(path, peer_id=peer.peer_id)
    if not result.success:
        raise ValueError("Blip could not confirm dispatch. Check the desktop app before retrying.")
    return {"status": "dispatched", "recipient": peer.name, "file_name": path.name}


def main():
    # Signed download URLs are private credentials.
    logging.getLogger('httpx').setLevel(logging.WARNING)
    mcp.run()
