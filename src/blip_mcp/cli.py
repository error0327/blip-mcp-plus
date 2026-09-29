"""
Command Line Interface for Blip MCP & File Dispatcher.
Offers rich human-friendly terminal formatting and machine-readable JSON output.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from blip_mcp.core import BlipClient

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        if sys.stdout.encoding.lower() != "utf-8":
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr.encoding.lower() != "utf-8":
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

console = Console(highlight=False)
err_console = Console(stderr=True, highlight=False)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(package_name="blip-mcp")
def cli():
    """blip-mcp: Send files directly to paired mobile devices via Blip with zero host prompt."""
    pass


@cli.command(name="send")
@click.argument("files", nargs=-1, required=True, type=click.Path(exists=True))
@click.option("-p", "--peer", "peer_id", default=None, help="Target peer formatted as <user_id>:<device_id>.")
@click.option("--json", "json_output", is_flag=True, help="Output response in machine-readable JSON.")
def send_cmd(files: tuple[str, ...], peer_id: str | None, json_output: bool):
    """Send one or more files directly to a paired device."""
    client = BlipClient()
    result = client.send(files=list(files), peer_id=peer_id)

    if json_output:
        click.echo(
            json.dumps(
                {
                    "success": result.success,
                    "message": result.message,
                    "files": result.files,
                    "peer_id": result.peer_id,
                    "device_id": result.device_id,
                    "transfer_id": result.transfer_id,
                    "elapsed_seconds": result.elapsed_seconds,
                },
                indent=2,
            )
        )
        sys.exit(0 if result.success else 1)

    if result.success:
        console.print(
            Panel(
                f"[bold green][OK] Transfer Dispatched![/bold green]\n\n"
                f"[bold]Target Device:[/bold] {result.device_id or 'Auto-detected Phone'}\n"
                f"[bold]Files ({len(result.files)}):[/bold]\n"
                + "\n".join(f"  * {f}" for f in result.files)
                + (f"\n[bold]Transfer ID:[/bold] {result.transfer_id}" if result.transfer_id else "")
                + f"\n\n[cyan]Check your phone and tap 'Accept' to download.[/cyan]",
                title="Blip File Transfer",
                border_style="green",
            )
        )
    else:
        err_console.print(
            Panel(
                f"[bold red][ERROR] Transfer Failed[/bold red]\n\n{result.message}",
                title="Blip Error",
                border_style="red",
            )
        )
        sys.exit(1)


@cli.command(name="devices")
@click.option("--json", "json_output", is_flag=True, help="Output devices in machine-readable JSON.")
def devices_cmd(json_output: bool):
    """List paired devices and detected phone/tablets."""
    client = BlipClient()
    ctx = client.get_context()

    if json_output:
        click.echo(
            json.dumps(
                [
                    {
                        "name": d.name,
                        "device_id": d.device_id,
                        "peer_id": d.peer_id,
                        "is_primary": d.is_primary,
                        "is_local": d.is_local,
                        "transfer_count": d.transfer_count,
                    }
                    for d in ctx.devices
                ],
                indent=2,
            )
        )
        return

    table = Table(title="Blip Paired Devices", border_style="cyan")
    table.add_column("Device Name", style="bold white")
    table.add_column("Role", style="magenta")
    table.add_column("Device ID", style="dim")
    table.add_column("Transfers", justify="right")

    for d in ctx.devices:
        role = "[Mobile] Primary" if d.is_primary else ("[PC] Local" if d.is_local else "[Peer]")
        table.add_row(d.name, role, d.device_id, str(d.transfer_count))

    console.print(table)


@cli.command(name="status")
@click.option("--json", "json_output", is_flag=True, help="Output status in machine-readable JSON.")
def status_cmd(json_output: bool):
    """Show Blip daemon health, account info, and recent transfers."""
    client = BlipClient()
    ctx = client.get_context()

    if json_output:
        click.echo(
            json.dumps(
                {
                    "is_running": ctx.is_running,
                    "executable": str(ctx.executable_path) if ctx.executable_path else None,
                    "user_email": ctx.user_email,
                    "user_id": ctx.user_id,
                    "primary_device": ctx.primary_peer.name if ctx.primary_peer else None,
                    "recent_transfers_count": len(ctx.recent_transfers),
                },
                indent=2,
            )
        )
        return

    running_badge = "[bold green]Running[/bold green]" if ctx.is_running else "[bold yellow]Stopped[/bold yellow]"
    console.print(
        Panel(
            f"[bold]Daemon Status:[/bold] {running_badge}\n"
            f"[bold]Account Email:[/bold] {ctx.user_email or 'Not logged in'}\n"
            f"[bold]User ID:[/bold] {ctx.user_id or 'Unknown'}\n"
            f"[bold]Executable:[/bold] {ctx.executable_path or 'Not found'}\n"
            f"[bold]Primary Target:[/bold] {ctx.primary_peer.name if ctx.primary_peer else 'None found'}",
            title="Blip Status",
            border_style="blue",
        )
    )

    if ctx.recent_transfers:
        table = Table(title="Recent Transfers", border_style="dim")
        table.add_column("Transfer ID", style="dim")
        table.add_column("Files", style="white")
        table.add_column("Timestamp", style="cyan")
        for t in ctx.recent_transfers[:5]:
            table.add_row(t.transfer_id, ", ".join(t.files), str(t.timestamp))
        console.print(table)


@cli.command(name="serve")
def serve_cmd():
    """Start the Model Context Protocol (MCP) server over stdio."""
    from blip_mcp.server import mcp
    mcp.run()


def main():
    cli()


if __name__ == "__main__":
    main()
