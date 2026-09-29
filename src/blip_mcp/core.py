"""
Core client and reverse-engineered interface for Blip (blip.net).
Provides cross-platform executable discovery, local state inspection,
peer device resolution, and zero-prompt direct file transfer.
"""

from __future__ import annotations

import base64
import glob
import json
import os
import platform
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Device:
    """Represents a paired Blip peer device."""
    device_id: str
    user_id: str
    is_local: bool
    is_primary: bool
    kind: str = "Unknown"
    name: str = "Unknown Device"
    transfer_count: int = 0

    @property
    def peer_id(self) -> str:
        """Formatted peer string accepted by Blip CLI: <user_id>:<device_id>."""
        return f"{self.user_id}:{self.device_id}"

    @property
    def display_name(self) -> str:
        """Human-readable display with OS/Kind badge."""
        if self.is_local:
            return f"{self.name} [Local PC]"
        return f"{self.name} ({self.kind})"


@dataclass
class TransferRecord:
    """Metadata for a past or in-flight file transfer."""
    transfer_id: str
    files: list[str]
    timestamp: float
    metadata_file: str | None = None


@dataclass
class BlipContext:
    """Current state and authentication context of the local Blip installation."""
    user_id: str | None = None
    user_email: str | None = None
    local_device_id: str | None = None
    devices: list[Device] = field(default_factory=list)
    recent_transfers: list[TransferRecord] = field(default_factory=list)
    state_dir: Path | None = None
    executable_path: Path | None = None
    is_running: bool = False

    @property
    def primary_peer(self) -> Device | None:
        """Returns the primary target peer device (e.g. mobile phone)."""
        for d in self.devices:
            if d.is_primary and not d.is_local:
                return d
        for d in self.devices:
            if not d.is_local:
                return d
        return None


@dataclass
class TransferResult:
    """Result of an automated transfer dispatch."""
    success: bool
    message: str
    files: list[str]
    peer_id: str | None = None
    device_id: str | None = None
    transfer_id: str | None = None
    elapsed_seconds: float = 0.0
    command_output: str | None = None


class BlipClient:
    """
    High-level programmatic controller for the Blip desktop application.
    Discovers local installations, extracts paired peer IDs, and sends
    files directly without requiring GUI confirmation on the host machine.
    """

    def __init__(self, executable_path: str | Path | None = None, state_dir: str | Path | None = None):
        self.executable_path = Path(executable_path) if executable_path else self.find_executable()
        self.state_dir = Path(state_dir) if state_dir else self.find_state_dir()

    @staticmethod
    def find_executable() -> Path | None:
        """Discovers the Blip desktop executable across supported platforms."""
        system = platform.system()

        # 1. Standard PATH resolution
        exe_name = "blip.exe" if system == "Windows" else "blip"
        resolved = shutil.which(exe_name) or shutil.which("blip")
        if resolved:
            return Path(resolved).resolve()

        if system == "Windows":
            # 2. Windows AppExecutionAlias
            localappdata = os.environ.get("LOCALAPPDATA", "")
            if localappdata:
                alias = Path(localappdata) / "Microsoft" / "WindowsApps" / "blip.exe"
                if alias.is_file():
                    return alias

            # 3. WindowsApps package location
            pkg_pattern = r"C:\Program Files\WindowsApps\BlipStudioInc.BlipApp_*_x64__*\bin\Blip.exe"
            matches = glob.glob(pkg_pattern)
            if matches:
                return Path(matches[-1])

            # 4. Standard Program Files
            for pf in [os.environ.get("ProgramFiles", "C:\\Program Files"), os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")]:
                candidate = Path(pf) / "Blip" / "bin" / "Blip.exe"
                if candidate.is_file():
                    return candidate

        elif system == "Darwin":
            # macOS .app bundles
            candidates = [
                Path("/Applications/Blip.app/Contents/MacOS/Blip"),
                Path.home() / "Applications/Blip.app/Contents/MacOS/Blip",
            ]
            for c in candidates:
                if c.is_file():
                    return c

        elif system == "Linux":
            # Linux snap and bin paths
            candidates = [
                Path("/var/lib/snapd/snap/bin/blip"),
                Path("/snap/bin/blip"),
                Path("/usr/bin/blip"),
                Path("/usr/local/bin/blip"),
            ]
            for c in candidates:
                if c.is_file():
                    return c

        return None

    @staticmethod
    def find_state_dir() -> Path | None:
        """Discovers Blip's application state directory containing state.dat and metadata."""
        system = platform.system()

        if system == "Windows":
            localappdata = os.environ.get("LOCALAPPDATA", "")
            if localappdata:
                # Packaged MSIX app location
                pattern = os.path.join(localappdata, "Packages", "BlipStudioInc.BlipApp_*", "LocalCache", "Local", "net.blip.desktop")
                matches = glob.glob(pattern)
                if matches:
                    return Path(matches[-1])

                # Standalone fallback
                candidate = Path(localappdata) / "net.blip.desktop"
                if candidate.is_dir():
                    return candidate

        elif system == "Darwin":
            candidates = [
                Path.home() / "Library" / "Application Support" / "net.blip.desktop",
                Path.home() / "Library" / "Caches" / "net.blip.desktop",
            ]
            for c in candidates:
                if c.is_dir():
                    return c

        elif system == "Linux":
            candidates = [
                Path.home() / ".config" / "net.blip.desktop",
                Path.home() / ".local" / "share" / "net.blip.desktop",
            ]
            for c in candidates:
                if c.is_dir():
                    return c

        return None

    @staticmethod
    def is_running() -> bool:
        """Checks if the Blip application process is currently running."""
        system = platform.system()
        try:
            if system == "Windows":
                out = subprocess.check_output(
                    ["tasklist", "/FI", "IMAGENAME eq Blip.exe", "/NH"],
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
                )
                return "Blip.exe" in out
            else:
                out = subprocess.check_output(["pgrep", "-f", "Blip"], text=True)
                return bool(out.strip())
        except Exception:
            return False

    def ensure_running(self, timeout_seconds: float = 3.0) -> bool:
        """Ensures that Blip is running in the background. Launches it if necessary."""
        if self.is_running():
            return True

        if not self.executable_path or not self.executable_path.exists():
            return False

        try:
            # Start minimized / in background
            kwargs: dict[str, Any] = {}
            if platform.system() == "Windows" and hasattr(subprocess, "CREATE_NO_WINDOW"):
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

            subprocess.Popen([str(self.executable_path), "--background"], **kwargs)

            # Wait for process to spawn
            start = time.time()
            while time.time() - start < timeout_seconds:
                if self.is_running():
                    time.sleep(0.5)  # Allow IPC socket to initialize
                    return True
                time.sleep(0.2)
            return self.is_running()
        except Exception:
            return False

    @staticmethod
    def _extract_jwt_payload(data: bytes) -> dict[str, Any] | None:
        """Extracts and parses user/device claims from embedded JWT in state.dat."""
        matches = re.findall(b"eyJ[A-Za-z0-9_-]+\\.eyJ[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+", data)
        for m in matches:
            parts = m.split(b".")
            if len(parts) >= 2:
                try:
                    payload_b64 = parts[1]
                    padded = payload_b64 + b"=" * (-len(payload_b64) % 4)
                    payload_json = base64.urlsafe_b64decode(padded)
                    payload = json.loads(payload_json)
                    if "user_id" in payload and "device_id" in payload:
                        return payload
                except Exception:
                    continue
        return None

    def get_context(self) -> BlipContext:
        """Parses Blip local state to extract credentials, paired peers, and recent transfers."""
        ctx = BlipContext(
            state_dir=self.state_dir,
            executable_path=self.executable_path,
            is_running=self.is_running(),
        )

        if not self.state_dir or not self.state_dir.exists():
            return ctx

        state_file = self.state_dir / "state.dat"
        if not state_file.is_file():
            return ctx

        raw_state: bytes | None = None
        for _ in range(5):
            try:
                with open(state_file, "rb") as f:
                    raw_state = f.read()
                break
            except (PermissionError, OSError):
                time.sleep(0.1)

        if not raw_state:
            return ctx

        jwt = self._extract_jwt_payload(raw_state)
        if jwt:
            ctx.user_id = jwt.get("user_id")
            ctx.user_email = jwt.get("user_email")
            ctx.local_device_id = jwt.get("device_id")

        # Discover all UUIDs in state.dat
        uuid_matches = re.findall(b"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", raw_state)
        uuid_counts: dict[str, int] = {}
        for u in uuid_matches:
            s = u.decode("ascii").lower()
            uuid_counts[s] = uuid_counts.get(s, 0) + 1

        # Read recent TransferMetadata to identify transfer IDs and transfer history
        meta_dir = self.state_dir / "TransferMetadata" if self.state_dir else None
        known_transfer_ids: set[str] = set()
        recent_records: list[TransferRecord] = []

        if meta_dir and meta_dir.is_dir():
            pb_files = glob.glob(str(meta_dir / "*.pb"))
            pb_files.sort(key=os.path.getmtime, reverse=True)
            for pb in pb_files:
                pb_path = Path(pb)
                known_transfer_ids.add(pb_path.stem.lower())
                if len(recent_records) < 10:
                    try:
                        with open(pb_path, "rb") as pf:
                            content = pf.read()
                        str_matches = re.findall(b"[\x20-\x7E]{2,}", content)
                        decoded = [s.decode("latin-1") for s in str_matches]
                        file_candidates = [
                            s for s in decoded
                            if ("." in s or "\\" in s or "/" in s) and not s.startswith("http") and not s.startswith("downloads://")
                        ]
                        recent_records.append(
                            TransferRecord(
                                transfer_id=pb_path.stem,
                                files=file_candidates[:5] or ["(payload)"],
                                timestamp=pb_path.stat().st_mtime,
                                metadata_file=str(pb_path),
                            )
                        )
                    except Exception:
                        continue

        ctx.recent_transfers = recent_records

        # Extract device names and kinds from protobuf records in state.dat
        # Protobuf layout: Tag 1 (UUID string 36b), Tag 2 (varint OS kind), Tag 3 (string name)
        device_meta: dict[str, tuple[str, str]] = {}
        dev_pattern = re.compile(b"\n\\$([0-9a-fA-F-]{36})\x10(.)\x1a(.)")
        for m in dev_pattern.finditer(raw_state):
            d_id = m.group(1).decode("ascii").lower()
            k_byte = ord(m.group(2))
            n_len = ord(m.group(3))
            n_pos = m.end()
            n_str = raw_state[n_pos : n_pos + n_len].decode("utf-8", errors="replace")
            k_str = {1: "Linux", 2: "iOS", 3: "Android", 4: "Windows", 5: "macOS"}.get(k_byte, "Mobile/Tablet")
            device_meta[d_id] = (n_str, k_str)

        # Classify devices: exclude user_id, local_dev, and any known transfer IDs
        devices: list[Device] = []
        user_id = ctx.user_id or ""
        local_dev = ctx.local_device_id or ""

        candidates = [
            (uid, count) for uid, count in uuid_counts.items()
            if uid != user_id and uid != local_dev and uid not in known_transfer_ids and count >= 5
        ]
        candidates.sort(key=lambda x: x[1], reverse=True)

        if candidates:
            primary_uid, primary_count = candidates[0]
            p_name, p_kind = device_meta.get(primary_uid, ("Primary Mobile Device", "Mobile"))
            devices.append(
                Device(
                    device_id=primary_uid,
                    user_id=user_id,
                    is_local=False,
                    is_primary=True,
                    kind=p_kind,
                    name=p_name,
                    transfer_count=primary_count,
                )
            )
            for uid, count in candidates[1:]:
                c_name, c_kind = device_meta.get(uid, (f"Peer Device ({uid[:8]})", "Peer"))
                devices.append(
                    Device(
                        device_id=uid,
                        user_id=user_id,
                        is_local=False,
                        is_primary=False,
                        kind=c_kind,
                        name=c_name,
                        transfer_count=count,
                    )
                )

        if local_dev:
            l_name, l_kind = device_meta.get(local_dev, ("This Computer", "Windows"))
            devices.insert(
                0,
                Device(
                    device_id=local_dev,
                    user_id=user_id,
                    is_local=True,
                    is_primary=False,
                    kind=l_kind,
                    name=l_name,
                    transfer_count=uuid_counts.get(local_dev, 0),
                )
            )

        ctx.devices = devices
        return ctx

    def send(
        self,
        files: str | Path | list[str | Path],
        peer_id: str | None = None,
        auto_launch: bool = True,
    ) -> TransferResult:
        """
        Sends one or more files directly to a paired device.
        
        Args:
            files: Single file path or list of file paths to send.
            peer_id: Optional peer formatted as '<user_id>:<device_id>'.
                     If omitted, automatically resolves the primary mobile peer.
            auto_launch: If True, launches the Blip background process if not running.
        """
        t0 = time.time()

        # Normalize file list
        raw_list = [files] if isinstance(files, (str, Path)) else list(files)
        if not raw_list:
            return TransferResult(
                success=False,
                message="No files specified for transfer.",
                files=[],
                elapsed_seconds=0.0,
            )

        resolved_files: list[str] = []
        for f in raw_list:
            p = Path(f).expanduser().resolve()
            if not p.exists():
                return TransferResult(
                    success=False,
                    message=f"File not found: '{f}'",
                    files=[],
                    elapsed_seconds=time.time() - t0,
                )
            if not p.is_file():
                return TransferResult(
                    success=False,
                    message=f"Path is not a regular file: '{f}'",
                    files=[],
                    elapsed_seconds=time.time() - t0,
                )
            resolved_files.append(str(p))

        # Check executable
        if not self.executable_path or not self.executable_path.exists():
            return TransferResult(
                success=False,
                message="Blip executable not found. Please verify Blip is installed.",
                files=resolved_files,
                elapsed_seconds=time.time() - t0,
            )

        # Ensure Blip daemon is active
        if auto_launch and not self.is_running():
            launched = self.ensure_running()
            if not launched:
                return TransferResult(
                    success=False,
                    message="Failed to launch Blip application in the background.",
                    files=resolved_files,
                    elapsed_seconds=time.time() - t0,
                )

        # Resolve peer_id if provided as name, device_id, or peer_id
        target_peer: str | None = None
        target_device_id: str | None = None
        ctx = self.get_context()

        if peer_id:
            # Check if peer_id matches a known device name, device_id, or peer_id
            matched_dev: Device | None = None
            query = peer_id.strip().lower()
            for d in ctx.devices:
                if not d.is_local and (
                    query == d.device_id.lower()
                    or query in d.name.lower()
                    or query == d.peer_id.lower()
                ):
                    matched_dev = d
                    break

            if matched_dev:
                target_peer = matched_dev.peer_id
                target_device_id = matched_dev.device_id
            else:
                target_peer = peer_id
                if ":" in target_peer:
                    target_device_id = target_peer.split(":", 1)[1]
        else:
            primary = ctx.primary_peer
            if not primary:
                return TransferResult(
                    success=False,
                    message="No paired peer device found in Blip state. Connect your phone in the Blip app first.",
                    files=resolved_files,
                    elapsed_seconds=time.time() - t0,
                )
            target_peer = primary.peer_id
            target_device_id = primary.device_id

        # Record metadata count prior to transfer to detect newly created transfer ID
        pre_meta: set[str] = set()
        meta_dir = self.state_dir / "TransferMetadata" if self.state_dir else None
        if meta_dir and meta_dir.is_dir():
            pre_meta = set(os.listdir(meta_dir))

        # Build CLI command
        # Syntax: blip.exe --peer <userId>:<deviceId> --file <path1> <path2> ...
        cmd = [str(self.executable_path), "--peer", target_peer]
        for rf in resolved_files:
            cmd.extend(["--file", rf])

        try:
            kwargs: dict[str, Any] = {
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "text": True,
                "timeout": 15,
            }
            if platform.system() == "Windows" and hasattr(subprocess, "CREATE_NO_WINDOW"):
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

            proc = subprocess.run(cmd, **kwargs)

            # Wait briefly and inspect if new metadata .pb appeared
            transfer_id: str | None = None
            if meta_dir and meta_dir.is_dir():
                time.sleep(0.5)
                post_meta = set(os.listdir(meta_dir)) - pre_meta
                if post_meta:
                    transfer_id = Path(list(post_meta)[0]).stem

            if proc.returncode == 0:
                elapsed = time.time() - t0
                return TransferResult(
                    success=True,
                    message=f"Successfully dispatched {len(resolved_files)} file(s) to device {target_device_id or target_peer}. Accept notification on the phone.",
                    files=resolved_files,
                    peer_id=target_peer,
                    device_id=target_device_id,
                    transfer_id=transfer_id,
                    elapsed_seconds=round(elapsed, 2),
                    command_output=proc.stdout.strip() if proc.stdout else None,
                )
            else:
                return TransferResult(
                    success=False,
                    message=f"Blip command exited with code {proc.returncode}: {proc.stderr.strip() or proc.stdout.strip()}",
                    files=resolved_files,
                    peer_id=target_peer,
                    device_id=target_device_id,
                    elapsed_seconds=round(time.time() - t0, 2),
                    command_output=(proc.stderr + "\n" + proc.stdout).strip(),
                )
        except Exception as e:
            return TransferResult(
                success=False,
                message=f"Failed to execute Blip CLI: {e}",
                files=resolved_files,
                peer_id=target_peer,
                device_id=target_device_id,
                elapsed_seconds=round(time.time() - t0, 2),
            )
