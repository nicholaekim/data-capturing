# data-capturing
Here’s a **pipeline report** for a downloadable “gameplay data capture” product that collects **human input + synchronized observations** for training **world models / agents**. I’m going to assume **Windows-first** because it’s the cleanest path and covers most PC gaming.

---

## 1) Product goal and data contract

### What you’re producing

A **client app** users install that:

1. records **inputs** (keyboard/mouse/controller) with accurate timestamps
2. records **observations** (game video frames + optional audio + optional system metadata)
3. optionally records **game state** *when available* (via integrations)
4. packages it into a **standard dataset format**
5. uploads it securely to your backend (batch or streaming)

### The “minimum useful dataset”

Even without game-state hooks, you can produce a dataset suitable for imitation / sequence modeling:

* **Input stream**: key down/up, mouse delta, mouse buttons, wheel, gamepad
* **Observation stream**: video frames (or encoded video) with timestamps
* **Sync layer**: a shared clock so you can align “what the user did” to “what changed on screen”

---

## 2) High-level pipeline chart (end-to-end)

**Client (User PC)**

1. **Installer + Permissions**
2. **Capture Agent**

   * Input Hook
   * Screen Capture
   * (Optional) Audio Capture
   * (Optional) Game Integrations (plugins, APIs)
3. **Time Sync + Session Manager**
4. **Local Buffer / Event Store**
5. **Encoder / Packager**
6. **Uploader (Batch or Stream)**
7. **Crash Recovery + Retry + Backpressure**

**Backend (Your infra)**
8. **API Gateway + Auth**
9. **Ingest Service**
10. **Validation + De-identification (if needed)**
11. **Object Storage (raw)**
12. **Metadata DB (index)**
13. **Processing Jobs (ETL)**
14. **Dataset Registry + Versioning**
15. **Analytics / Monitoring Dashboard**
16. **Export for Training (RL/IL/world model)**

---

## 3) Client-side technical architecture (the hard part)

### 3.1 Input capture module

**Purpose:** capture raw human actions with minimal latency and correct ordering.

**Windows approaches:**

* **Keyboard/mouse**: low-level hooks (Windows API) for key down/up, mouse move (delta), buttons, wheel
* **Gamepads**: XInput / Raw Input

**Data you must log**

* `t_event` (high-resolution timestamp)
* `device_id` (keyboard/mouse/gamepad)
* event type + payload
* optional: active window title / process id (for session attribution)

**Important constraints**

* Must be robust against high polling rate mice
* Must avoid dropped events when CPU spikes
* Must not trigger anti-cheat (more on that below)

### 3.2 Observation capture module (screen/video)

You have two baseline options:

**Option A: record video (recommended early)**

* Capture frames and encode to **H.264/H.265** using hardware encoder when possible
* Log: video container + precise timestamp mapping (PTS) so you can align events to frames

**Option B: capture sparse frames**

* Save JPEG/PNG frames at X fps with timestamps (simpler but bigger and less smooth)

**Core requirements**

* Fixed capture FPS (e.g., 30 or 60)
* Accurate frame timestamps
* Hardware encoding path to keep performance acceptable

### 3.3 (Optional) Game state capture

Best-case: **native integration**, not computer vision.

**Ways to get game state**

* Game SDK / mod API / telemetry endpoints (rare)
* Plugin (Unity/Unreal) for games you control
* External telemetry (e.g., specific titles or engines that expose data)

**Fallback if no integration**

* derive pseudo-state from screen (computer vision / OCR) — doable, but much noisier.

### 3.4 Time synchronization layer

This is non-negotiable. Your dataset lives or dies on alignment.

**Use a single monotonic clock** on the client:

* `t0 = monotonic_ns()` at session start
* Every input event and every frame uses that same clock reference
* Store mapping from monotonic → wall clock for backend ordering

### 3.5 Local buffer / event store (offline-first)

Users will disconnect / crash / close laptop. You need local durability.

**Recommended**

* **SQLite** event table + append-only design
* separate file for video (MP4)
* periodic checkpoints

**What it solves**

* Crash recovery
* Upload retries
* Backpressure if network slow
* Ability to “review what is being uploaded” for trust

### 3.6 Packaging format (dataset output)

Use a format that is friendly for training.

**Simple but solid v1**

* `session_manifest.json` (metadata)
* `events.jsonl` (inputs, time-stamped)
* `video.mp4` (screen recording)
* `checksums.txt`

**Manifest fields**

* session_id, user_id (pseudonymous), game/process, start/end times
* capture settings (fps, resolution, input devices)
* schema version
* hash of each file for integrity

### 3.7 Uploader

Start with **batch upload**. Streaming is harder and you don’t need it first.

**Batch design**

* chunk video (or upload whole video if small)
* upload events in chunks (e.g., 5–30 seconds) or at end of session
* resumable uploads with chunk hashes

**Transport**

* HTTPS with signed requests
* optionally multipart upload directly to object storage using pre-signed URLs

---

## 4) Backend technical architecture

### 4.1 API & auth

You need **strong device/session identity** without making users do anything technical.

**Auth pattern**

* user installs app → app obtains a device token (OAuth device flow or one-time code)
* backend issues **short-lived upload tokens** (JWT or similar)
* uploads are authorized per session id + user id

### 4.2 Ingestion service

Responsibilities:

* accept upload metadata
* validate schema version
* store raw objects
* write index records

### 4.3 Storage layout

**Raw object storage**

* `raw/{user_id}/{session_id}/video.mp4`
* `raw/{user_id}/{session_id}/events.jsonl`
* `raw/{user_id}/{session_id}/manifest.json`

**Metadata DB (Postgres)**

* sessions table: user_id, game, duration, fps, resolution, status, hashes
* ingestion status: received → validated → processed → exported

### 4.4 Processing / ETL

Jobs you’ll want:

* verify checksums
* parse JSONL events into columnar format (Parquet)
* generate alignment indices (frame_id ↔ time range ↔ events)
* optional: generate training-ready windows (e.g., 2–10 second clips)

### 4.5 Dataset registry & versioning

Treat datasets like software releases.

* dataset_id, version, schema_version
* train/val/test splits
* provenance: which sessions included, filtering rules

---

## 5) Data quality requirements (what makes it usable for world models)

### 5.1 Minimum alignment guarantee

You should be able to answer:

* “What inputs happened between frame N and N+1?”
* “Given event E at time T, what frame(s) reflect its consequence?”

So you need:

* stable timestamping
* consistent video frame pacing
* consistent input event ordering

### 5.2 Sampling and smoothing

Mouse move events can be extremely dense.
You’ll probably need:

* raw capture + optionally a downsampled “model-ready” stream
* keep raw always; derive processed later

### 5.3 Session labeling (lightweight)

At minimum:

* game name / executable hash
* resolution / graphics settings (optional)
* “type of play” tag (user-selected or inferred later)

---

## 6) Security, privacy, and compliance requirements

This product touches sensitive data (screen + inputs). If you ignore this, you will not get adoption.

**Must-haves**

* explicit opt-in and clear explanation of what is collected
* “pause capture” hotkey + tray indicator
* local preview (“what will upload”)
* encryption in transit (TLS) and at rest (server)
* strong auth tokens, rotation, revoke capability

**Hard line**

* never capture when not in the target game window (window/process whitelist)
* never capture passwords typed into browsers, chat apps, etc.

**Anti-cheat reality check**
Many competitive games use anti-cheat that can treat hooks/overlays as suspicious. You need to:

* start with **games without strict anti-cheat**, or
* capture in ways that don’t resemble cheating tools
* expect some titles to be off-limits unless you get partnerships

---

## 7) Suggested tech stack (practical choices)

### Client (Windows-first)

* App shell/UI: **C# (.NET)** or **C++**
* Input hooks: WinAPI low-level hooks / Raw Input / XInput
* Screen capture: Desktop Duplication API (DXGI) path
* Encoding: hardware encoders (NVENC/AMF/QSV) if using C++ stack; or use a reliable library wrapper
* Local store: SQLite
* Networking: HTTPS client + resumable upload logic

### Backend

* API: Node/Go/Python (FastAPI) — pick what you can ship fastest
* Auth: JWT + device enrollment flow
* Storage: S3-style object storage
* DB: Postgres
* Processing: container jobs (Docker) + queue
* Analytics: basic dashboards + ingestion metrics

---

## 8) MVP phases (so you don’t drown)

### MVP0: Prove capture works locally

* input → events.jsonl
* screen → video.mp4
* manifest.json
* no upload

### MVP1: Add batch upload

* create session
* upload artifacts
* server stores + indexes

### MVP2: Add processing + training-ready export

* align frames ↔ events
* generate Parquet + clip windows

### MVP3: Add integrations (game state, engine plugins)

* for games you control or partner with

---

## 9) Your “starter blueprint” deliverables (what you should produce first)

If you want the cleanest start, build these 4 artifacts:

1. **Event schema** (JSONL fields for each input type)
2. **Session manifest schema**
3. **Client module diagram** (Capture → Sync → Store → Package → Upload)
4. **Backend endpoints** (create session, upload chunk, finalize session, get status)

If you tell me **Windows-only yes/no** and whether you’re okay starting with **“video + inputs” only** (no game state yet), I’ll write:

* the exact JSONL schema (copy-paste ready)
* the exact API endpoint list with request/response shapes
* and a clean ASCII “chart” you can drop into a doc/pitch deck.
