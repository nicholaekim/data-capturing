# Input Logger POC

Minimal proof-of-concept input logger that captures keyboard and mouse events with high-resolution timestamps.

## Features

- Logs keyboard key presses and releases
- Logs mouse movements (as deltas, not absolute coordinates)
- Logs mouse button clicks and scroll events
- High-resolution timestamps (nanoseconds via `time.perf_counter_ns`)
- Wall-clock timestamps (milliseconds since epoch)
- Buffered writes with periodic flushing
- Graceful shutdown on ESC key or Ctrl+C
- Session metadata manifest

## Requirements

- Python 3.10+
- macOS, Linux, or Windows

## Setup

```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
# macOS/Linux:
source venv/bin/activate
# Windows:
# venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## Usage

```bash
python input_logger_poc.py
```

Press **ESC** to stop logging and save the session.

## Output Files

Each session creates a timestamped directory (e.g., `session_20240310_143022_a1b2c3d4/`) containing:

### `events.jsonl`
Newline-delimited JSON with one event per line:

```json
{"t_ns":12345,"t_wall_ms":1710000000123,"type":"key_down","key":"w"}
{"t_ns":22345,"t_wall_ms":1710000000223,"type":"key_up","key":"w"}
{"t_ns":32345,"t_wall_ms":1710000000323,"type":"mouse_move","dx":12,"dy":-4}
{"t_ns":42345,"t_wall_ms":1710000000423,"type":"mouse_button","button":"left","state":"down"}
{"t_ns":52345,"t_wall_ms":1710000000523,"type":"mouse_scroll","dx":0,"dy":-1}
```

### `session_manifest.json`
Session metadata:

```json
{
  "session_id": "a1b2c3d4-...",
  "schema_version": "1.0.0",
  "platform": "Darwin",
  "python_version": "3.11.0",
  "started_at_iso": "2024-03-10T19:30:22.123456+00:00",
  "ended_at_iso": "2024-03-10T19:35:10.654321+00:00"
}
```

## Event Schema

| Field | Type | Description |
|-------|------|-------------|
| `t_ns` | int | Nanoseconds since session start |
| `t_wall_ms` | int | Milliseconds since Unix epoch |
| `type` | string | Event type: `key_down`, `key_up`, `mouse_move`, `mouse_button`, `mouse_scroll` |
| `key` | string | Key name (keyboard events only) |
| `dx`, `dy` | int | Delta movement (mouse_move, mouse_scroll) |
| `button` | string | Button name: `left`, `right`, `middle` (mouse_button only) |
| `state` | string | `down` or `up` (mouse_button only) |

## Permissions / Accessibility

### macOS
You may need to grant **Accessibility** and **Input Monitoring** permissions:
1. Go to **System Preferences → Security & Privacy → Privacy**
2. Add your terminal app (e.g., Terminal, iTerm2) to:
   - **Accessibility**
   - **Input Monitoring**

### Linux
You may need to run with `sudo` or add your user to the `input` group:
```bash
sudo usermod -aG input $USER
# Log out and back in for changes to take effect
```

### Windows
No special permissions required in most cases.

## Notes

- Mouse movements are logged as **deltas** (`dx`, `dy`), not absolute coordinates
- Events are buffered and flushed every 100 events or every 1 second
- No external network calls are made
