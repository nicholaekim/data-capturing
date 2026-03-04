#!/usr/bin/env python3
"""
Input Logger POC - Logs keyboard and mouse events to JSONL with high-resolution timestamps.
Press ESC to quit cleanly.
"""

from __future__ import annotations

import atexit
import json
import platform
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from pynput import keyboard, mouse

# === Configuration ===
FLUSH_INTERVAL_SEC: float = 1.0
FLUSH_EVENT_COUNT: int = 100
SCHEMA_VERSION: str = "1.0.0"

# === Global State ===
_session_start_ns: int = 0
_session_start_wall_ms: int = 0
_last_mouse_x: int | None = None
_last_mouse_y: int | None = None
_event_buffer: list[dict[str, Any]] = []
_buffer_lock = threading.Lock()
_events_file: Any = None
_session_dir: Path | None = None
_session_id: str = ""
_running: bool = False
_last_flush_time: float = 0.0


def _get_timestamps() -> tuple[int, int]:
    """Return (t_ns since session start, t_wall_ms since epoch)."""
    t_ns = time.perf_counter_ns() - _session_start_ns
    t_wall_ms = int(time.time() * 1000)
    return t_ns, t_wall_ms


def _write_event(event: dict[str, Any]) -> None:
    """Buffer an event and flush if needed."""
    global _last_flush_time
    # Print to terminal in real-time
    print(json.dumps(event, separators=(",", ":")))
    with _buffer_lock:
        _event_buffer.append(event)
        now = time.monotonic()
        should_flush = (
            len(_event_buffer) >= FLUSH_EVENT_COUNT
            or (now - _last_flush_time) >= FLUSH_INTERVAL_SEC
        )
        if should_flush:
            _flush_buffer()
            _last_flush_time = now


def _flush_buffer() -> None:
    """Write buffered events to file (must hold _buffer_lock)."""
    global _event_buffer
    if _events_file and _event_buffer:
        for evt in _event_buffer:
            _events_file.write(json.dumps(evt, separators=(",", ":")) + "\n")
        _events_file.flush()
        _event_buffer = []


def _flush_and_close() -> None:
    """Final flush and close of events file."""
    global _events_file
    with _buffer_lock:
        _flush_buffer()
    if _events_file:
        _events_file.close()
        _events_file = None


# === Keyboard Handlers ===
def _key_to_str(key: keyboard.Key | keyboard.KeyCode | None) -> str:
    """Convert pynput key to string representation."""
    if key is None:
        return "unknown"
    if isinstance(key, keyboard.KeyCode):
        if key.char:
            return key.char
        return f"vk:{key.vk}" if key.vk else "unknown"
    return key.name


def _on_key_press(key: keyboard.Key | keyboard.KeyCode | None) -> bool | None:
    """Handle key press event."""
    if not _running:
        return False
    t_ns, t_wall_ms = _get_timestamps()
    key_str = _key_to_str(key)
    _write_event({
        "t_ns": t_ns,
        "t_wall_ms": t_wall_ms,
        "type": "key_down",
        "key": key_str,
    })
    # Check for ESC to quit
    if key == keyboard.Key.esc:
        _stop_session()
        return False
    return None


def _on_key_release(key: keyboard.Key | keyboard.KeyCode | None) -> bool | None:
    """Handle key release event."""
    if not _running:
        return False
    t_ns, t_wall_ms = _get_timestamps()
    key_str = _key_to_str(key)
    _write_event({
        "t_ns": t_ns,
        "t_wall_ms": t_wall_ms,
        "type": "key_up",
        "key": key_str,
    })
    return None


# === Mouse Handlers ===
def _on_mouse_move(x: int, y: int) -> bool | None:
    """Handle mouse move event - logs deltas, not absolute coordinates."""
    global _last_mouse_x, _last_mouse_y
    if not _running:
        return False
    
    if _last_mouse_x is not None and _last_mouse_y is not None:
        dx = x - _last_mouse_x
        dy = y - _last_mouse_y
        if dx != 0 or dy != 0:
            t_ns, t_wall_ms = _get_timestamps()
            _write_event({
                "t_ns": t_ns,
                "t_wall_ms": t_wall_ms,
                "type": "mouse_move",
                "dx": dx,
                "dy": dy,
            })
    
    _last_mouse_x = x
    _last_mouse_y = y
    return None


def _on_mouse_click(
    x: int, y: int, button: mouse.Button, pressed: bool
) -> bool | None:
    """Handle mouse button event."""
    if not _running:
        return False
    t_ns, t_wall_ms = _get_timestamps()
    _write_event({
        "t_ns": t_ns,
        "t_wall_ms": t_wall_ms,
        "type": "mouse_button",
        "button": button.name,
        "state": "down" if pressed else "up",
    })
    return None


def _on_mouse_scroll(x: int, y: int, dx: int, dy: int) -> bool | None:
    """Handle mouse scroll event."""
    if not _running:
        return False
    t_ns, t_wall_ms = _get_timestamps()
    _write_event({
        "t_ns": t_ns,
        "t_wall_ms": t_wall_ms,
        "type": "mouse_scroll",
        "dx": dx,
        "dy": dy,
    })
    return None


# === Session Management ===
def _start_session(output_dir: Path | None = None) -> Path:
    """Initialize a new logging session."""
    global _session_start_ns, _session_start_wall_ms, _session_id
    global _events_file, _session_dir, _running, _last_flush_time
    global _last_mouse_x, _last_mouse_y
    
    _session_id = str(uuid4())
    _session_start_ns = time.perf_counter_ns()
    _session_start_wall_ms = int(time.time() * 1000)
    _last_flush_time = time.monotonic()
    _last_mouse_x = None
    _last_mouse_y = None
    
    # Create session directory
    base_dir = output_dir or Path.cwd()
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    _session_dir = base_dir / f"session_{timestamp_str}_{_session_id[:8]}"
    _session_dir.mkdir(parents=True, exist_ok=True)
    
    # Open events file
    events_path = _session_dir / "events.jsonl"
    _events_file = open(events_path, "w", encoding="utf-8")
    
    # Write initial manifest
    _write_manifest(started=True)
    
    _running = True
    return _session_dir


def _stop_session() -> None:
    """Stop the logging session and finalize files."""
    global _running
    _running = False


def _write_manifest(started: bool = False) -> None:
    """Write or update the session manifest."""
    if not _session_dir:
        return
    
    manifest_path = _session_dir / "session_manifest.json"
    now_iso = datetime.now(timezone.utc).isoformat()
    
    manifest: dict[str, Any] = {
        "session_id": _session_id,
        "schema_version": SCHEMA_VERSION,
        "platform": platform.system(),
        "python_version": platform.python_version(),
    }
    
    if started:
        manifest["started_at_iso"] = now_iso
        manifest["ended_at_iso"] = None
    else:
        # Read existing manifest to preserve started_at_iso
        if manifest_path.exists():
            with open(manifest_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
                manifest["started_at_iso"] = existing.get("started_at_iso", now_iso)
        else:
            manifest["started_at_iso"] = now_iso
        manifest["ended_at_iso"] = now_iso
    
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


def _cleanup() -> None:
    """Cleanup handler for graceful shutdown."""
    _flush_and_close()
    _write_manifest(started=False)


def _signal_handler(sig: int, frame: Any) -> None:
    """Handle interrupt signals."""
    _stop_session()


def main() -> None:
    """Main entry point."""
    print("=" * 50)
    print("Input Logger POC")
    print("=" * 50)
    print()
    print("Starting logging session...")
    print("Press ESC to stop and save.")
    print()
    
    # Register cleanup handlers
    atexit.register(_cleanup)
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
    
    # Start session
    try:
        session_dir = _start_session()
        print(f"Session ID: {_session_id}")
        print(f"Output dir: {session_dir}")
        print()
        print("Logging... (ESC to quit)")
        print()
        
        # Start listeners
        keyboard_listener = keyboard.Listener(
            on_press=_on_key_press,
            on_release=_on_key_release,
        )
        mouse_listener = mouse.Listener(
            on_move=_on_mouse_move,
            on_click=_on_mouse_click,
            on_scroll=_on_mouse_scroll,
        )
        
        keyboard_listener.start()
        mouse_listener.start()
        
        # Wait for ESC or interrupt
        while _running:
            time.sleep(0.1)
            # Periodic flush check
            with _buffer_lock:
                if time.monotonic() - _last_flush_time >= FLUSH_INTERVAL_SEC:
                    _flush_buffer()
        
        # Stop listeners
        keyboard_listener.stop()
        mouse_listener.stop()
        keyboard_listener.join(timeout=1.0)
        mouse_listener.join(timeout=1.0)
        
    finally:
        _cleanup()
    
    print()
    print("Session ended.")
    print(f"Files saved to: {_session_dir}")
    print("  - events.jsonl")
    print("  - session_manifest.json")


if __name__ == "__main__":
    main()