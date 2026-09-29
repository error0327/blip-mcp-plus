"""
FastMCP Server for Blip (blip.net).
Provides minimal-token, production-grade tools for AI agents to list paired devices,
check daemon health, and dispatch files to mobile phones without host UI prompts.
"""

from __future__ import annotations

import os
from typing import Annotated, Any
from pydantic import Field

from mcp.server.fastmcp import FastMCP
from blip_mcp.core import BlipClient

# Initialize FastMCP with crisp metadata
mcp = FastMCP(
    name="blip-server",
    instructions=(
        "Use this server to send files directly from this computer to the user's mobile phone "
        "or paired devices via the Blip app (blip.net) with zero prompt on the PC."
    ),
)

_client = BlipClient()


@mcp.tool(
    name="send_file",
    description="Send a local file directly to a paired phone or device via Blip. Only requires acceptance on the receiving device.",
)
def send_file(
    file_path: Annotated[str, Field(description="Absolute or relative path to the file to send.")],
    device: Annotated[str | None, Field(description="Optional device name (e.g. 'iPhone', 'Galaxy'), device ID, or peer ID. If omitted, sends to the primary phone.")] = None,
) -> dict[str, Any]:
    """Sends a local file to the paired phone with zero desktop prompts."""
    res = _client.send(files=[file_path], peer_id=device)
    return {
        "success": res.success,
        "message": res.message,
        "files": res.files,
        "device_id": res.device_id,
        "transfer_id": res.transfer_id,
        "elapsed_seconds": res.elapsed_seconds,
    }


@mcp.tool(
    name="list_devices",
    description="List all paired devices (phones, tablets, PCs) recognized in the local Blip app with names and OS.",
)
def list_devices() -> list[dict[str, Any]]:
    """Lists paired Blip devices."""
    ctx = _client.get_context()
    return [
        {
            "name": d.name,
            "kind": d.kind,
            "device_id": d.device_id,
            "peer_id": d.peer_id,
            "is_primary": d.is_primary,
            "is_local": d.is_local,
            "transfer_count": d.transfer_count,
        }
        for d in ctx.devices
    ]


@mcp.tool(
    name="get_status",
    description="Get Blip application health, user account info, and recent transfer summary.",
)
def get_status() -> dict[str, Any]:
    """Gets Blip daemon status and recent transfers."""
    ctx = _client.get_context()
    recent = [
        {
            "transfer_id": t.transfer_id,
            "files": t.files,
            "timestamp": t.timestamp,
        }
        for t in ctx.recent_transfers[:3]
    ]
    return {
        "is_running": ctx.is_running,
        "executable_found": bool(ctx.executable_path and ctx.executable_path.exists()),
        "user_email": ctx.user_email,
        "primary_device": ctx.primary_peer.name if ctx.primary_peer else None,
        "primary_device_id": ctx.primary_peer.device_id if ctx.primary_peer else None,
        "recent_transfers": recent,
    }


def main():
    """Main entrypoint for MCP server stdio execution."""
    mcp.run()


if __name__ == "__main__":
    main()
