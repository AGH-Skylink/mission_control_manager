# Mission Control Manager – Audio Backend

Audio backend for the **Mission Control Panel** – audio mixer and PTT logic for 4 channels and up to 16 tablets, with HTTP/WebSocket API and structured logging for monitoring.

---

## 1. System overview

This service is responsible for:

- audio mixing:
  - **uplink**: 16 tablets → 4 channels,
  - **downlink**: 4 channels → 16 tablets,
- handling **PTT (Push-To-Talk)**:
  - multiple tablets can talk on the same channel at the same time (no floor-control / no queuing),
  - the server only tracks who currently holds PTT,
- computing **VU levels (RMS → dBFS)** for tablets and channels,
- simple **logging and monitoring**:
  - structured JSON logs to `system.log`,
  - health-check and state snapshot endpoints,
- simple **JSON configuration** (headroom, audio parameters),
- a small Python HTTP client to conveniently use the API.

Default audio parameters (consistent with `config.example.json`):

- sample rate: `fs = 44100 Hz`,
- frame size: `frame_size = 1024` samples,
- resolution: `16 bit` (int16 PCM),
- default headroom: `12 dB` (can be adjusted at runtime).

---

## 2. Running the service

### 2.1. Requirements

- Python 3.10+
- Installed packages (minimal set):
  - `fastapi`
  - `uvicorn[standard]`
  - `numpy`
  - `loguru`
  - `requests`

Example setup:

```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install fastapi "uvicorn[standard]" numpy loguru requests
```

(Run `pip install -r requirements.txt`.)

### 2.2. Starting the server

In the project directory:

```bash
python3 main.py
```

The server starts by default on:

- http://localhost:8000

FastAPI automatically exposes documentation:

- Swagger UI: http://localhost:8000/docs  
- ReDoc: http://localhost:8000/redoc

In the logs you should see events such as:

- `api.startup` – application startup,
- `engine.start` – start of the simulated audio engine loop.

---

## 3. Module architecture

### 3.1. `audio_manager/mixer.py` – audio mixing engine

Main class: **`AudioMixer`**

- Parameters:
  - `num_channels` – number of channels (default 4),
  - `num_tablets` – number of tablets (default 16).
- Stores configuration in `MixConfig`:
  - `uplink: Dict[channel, Dict[tablet_id, gain]]`,
  - `downlink: Dict[tablet_id, Dict[channel, gain]]`,
  - `tablet_mute: Dict[tablet_id, bool]`,
  - `channel_mute: Dict[channel, bool]`,
  - `headroom_db: float`.
- Working buffers:
  - `_tablet_in[tablet_id]`, `_tablet_out[tablet_id]` – float32 frames in range `[-1, 1]`,
  - `_chan_in[channel]`, `_chan_out[channel]` – same for channels.

Key methods:

- **Routing and configuration**:
  - `set_uniform_routing(gain_db=-12.0)` – default matrix: everyone to everyone with the same gain,
  - `set_uplink_matrix(matrix)` / `set_downlink_matrix(matrix)` – direct matrix configuration,
  - `set_tablet_mute(tid, mute)` / `set_channel_mute(ch, mute)` – mute per tablet/channel.
- **Frame I/O (external world)**:
  - `push_tablet_frame(tid, pcm_i16)` / `pull_tablet_frame(tid)`,
  - `push_channel_frame(ch, pcm_i16)` / `pull_channel_frame(ch)`,
  - internally converts `int16` ⇄ `float32 [-1, 1]`.
- **Mixing**:
  - `step()` – performs one processing step:
    1. uplink: `tablet_in` → channels (with headroom management and soft limiter),
    2. downlink: channels → `tablet_out`,
    3. updates RMS values for VU meters.
- **VU levels**:
  - `vu_levels_db()` – returns a dictionary:
    ```json
    {
      "tablets": { "1": dBFS, ... },
      "channels": { "1": dBFS, ... }
    }
    ```

### 3.2. `audio_manager/ptt_manager.py` – PTT logic

Class: **`PTTManager`**

- State:
  - `active_ptt: Dict[channel, Set[tablet_id]]` – who currently holds PTT on which channel,
  - `ptt_history: List[dict]` – in-memory PTT event log.
- No queuing, no floor-control:
  - **multiple tablets can have PTT active on the same channel at the same time**,
  - PTT is purely logical information for UI/logging; it does not gate audio yet.

Key methods:

- `request_ptt(tablet_id, channel, priority=1) -> PTTState`:
  - press / maintain PTT,
  - adds the tablet to `active_ptt[channel]`,
  - logs the event, returns `PTTState.ACTIVE`.
- `release_ptt(tablet_id, channel) -> PTTState`:
  - release PTT,
  - removes the tablet from `active_ptt[channel]`,
  - logs the event, returns `PTTState.IDLE`.
- `get_channel_state(channel)`:
  - returns channel state (IDLE/ACTIVE) and list of active tablets.
- `get_tablet_channels(tablet_id)`:
  - returns list of channels where this tablet currently has PTT active.
- `snapshot()`:
  - global PTT state:
    ```json
    {
      "timestamp": ...,
      "channels": { "1": [tablet_id, ...], "2": [...], ... }
    }
    ```

### 3.3. `audio_manager/logger.py` – SystemMonitor

Class: **`SystemMonitor`**

- Configures `loguru`:
  - logs to stderr,
  - logs to `system.log` (rotating file).
- Methods:
  - `log_event(event_type, event_data=None, level="INFO", message="")`:
    - writes a JSON record like:
      ```json
      {
        "ts": ...,
        "service": "mission-control-audio",
        "event_type": "matrix.updated",
        "message": "Mixing matrix / headroom updated",
        "data": { ... }
      }
      ```
  - `log_error_event(event_type, exc, event_data=None, message="")`:
    - error event (`logger.exception`) + stacktrace,
  - `time_block(event_type, event_data=None, message="")` – context manager for timing code blocks.

Example `system.log` snippet:

```text
2025-11-19 14:09:09.700 | INFO  | {"ts": ..., "service": "mission-control-audio", "event_type": "api.startup", ...}
2025-11-19 14:09:09.701 | INFO  | {"ts": ..., "service": "mission-control-audio", "event_type": "engine.start", ...}
2025-11-19 14:09:24.458 | DEBUG | {"ts": ..., "service": "mission-control-audio", "event_type": "health.check", ...}
...
```

### 3.4. `audio_manager/config_loader.py` – configuration from JSON

Function: **`load_engine_config(path="config.json", example_path="config.example.json")`**

- Strategy:
  1. try `config.json` (runtime override),
  2. if missing – try `config.example.json`,
  3. if both fail – use `DEFAULT_CONFIG`.

- Supported keys:
  - `fs` – sample rate (sanity-check only),
  - `frame_size` – frame size (sanity-check only),
  - `headroom_db` – actually used by the mixer.

If `fs`/`frame_size` in config differ from code constants – a **warning** is logged, but the service still runs.

Endpoint **`POST /config/reload`** allows reloading the config file and updating `headroom_db` at runtime.

### 3.5. `audio_manager/client.py` – HTTP client

Class: **`AudioEngineClient`**

- Uses `requests.Session` + `urllib3.Retry` with backoff.
- All methods return a dict of the form:
  ```python
  {"ok": bool, "data": ..., "error": str | None}
  ```

Key methods:

- Health / state:
  - `get_health()` → `GET /health`,
  - `get_state()` → `GET /state`,
  - `get_vu_levels()` → extracts VU from `/state`.
- Mixing:
  - `update_matrix(uplink=None, downlink=None, headroom_db=None)` → `POST /matrix`,
  - `mute_channel(channel, mute=True)` → `POST /channel/{ch}/mute`,
  - `mute_tablet(tablet_id, mute=True)` → `POST /tablet/{tid}/mute`.
- PTT:
  - `ptt_request(tablet_id, channel, priority=1)` → `POST /ptt/request`,
  - `ptt_release(tablet_id, channel)` → `POST /ptt/release`,
  - `get_ptt_state()` → `GET /ptt/state`.

### 3.6. `audio_manager/api.py` – FastAPI application

Defines the **`app = FastAPI(...)`** instance and all HTTP/WS endpoints.

Also starts the `_engine_loop()` task during application startup.

---

## 4. Audio simulation – `_engine_loop()`

In `api.py` there is an async function:

```python
async def _engine_loop() -> None:
    ...
```

Its role:

- simulate audio streams from tablets:
  - for each `tablet_id` it generates a sine wave with a different frequency (`300 Hz + 10 * id`),
  - amplitude is about `0.05` (~ -26 dBFS),
  - converts to int16 and passes to `mixer.push_tablet_frame(...)`,
- input channels (`chan_in`) currently receive **silence** (`zeros`),
- calls `mixer.step()` for each frame,
- tries to maintain a real-time cadence (`FRAME_SIZE / FS` seconds per frame).

In production this code is intended to be replaced by the real audio engine (Jun), which will:

- read from audio devices (4 channels),
- write output frames from `mixer.pull_channel_frame(ch)` / `mixer.pull_tablet_frame(tid)` back to hardware.

---

## 5. API reference

### 5.1. `GET /health`

Simple healthcheck for monitoring and basic tests.

**Response (JSON):**

```json
{
  "status": "ok",
  "ts": 1763557764.4585571,
  "num_channels": 4,
  "num_tablets": 16,
  "fs": 44100,
  "frame_size": 1024,
  "config": {
    "fs": 44100,
    "frame_size": 1024,
    "headroom_db": 12.0
  }
}
```

### 5.2. `GET /state`

Full system snapshot (VU, mix configuration, PTT).

**Response (JSON):**

```json
{
  "ts": ...,
  "vu_db": {
    "tablets": { "1": -240.0, "...": -240.0 },
    "channels": { "1": -51.78, "2": -51.78, "3": -51.78, "4": -51.78 }
  },
  "config": {
    "headroom_db": 12.0,
    "tablet_mute": { "1": true },
    "channel_mute": { "1": true },
    "uplink": {
      "1": { "1": 0.251..., "2": 0.251..., "...": 0.251... },
      "2": { },
      "3": { },
      "4": { }
    },
    "downlink": {
      "1": { "1": 0.251..., "2": 0.251..., "3": 0.251..., "4": 0.251... },
      "...": { }
    }
  },
  "ptt": {
    "timestamp": ...,
    "channels": {
      "1": [1, 5],
      "2": [],
      "3": [],
      "4": []
    }
  }
}
```

### 5.3. `POST /matrix`

Partial update of mix matrices and headroom.

**Request body (JSON):**

```json
{
  "uplink": {
    "1": { "1": 0.2, "2": 0.3 },
    "2": { "1": 0.1, "3": 0.5 }
  },
  "downlink": {
    "1": { "1": 0.5, "2": 0.5 },
    "2": { "1": 0.7 }
  },
  "headroom_db": 6.0
}
```

All fields are optional – e.g. you can send only:

```json
{ "headroom_db": 6.0 }
```

**Response:** current `state` (same format as `GET /state`).

### 5.4. `POST /channel/{channel}/mute`

Mute/unmute a channel.

**Request body:**

```json
{ "mute": true }
```

**Response:** current `state`.

### 5.5. `POST /tablet/{tablet_id}/mute`

Mute/unmute a tablet.

**Request body:**

```json
{ "mute": true }
```

**Response:** current `state`.

### 5.6. `POST /ptt/request`

Tablet requests (or maintains) PTT on a channel.

**Request body:**

```json
{
  "tablet_id": 1,
  "channel": 1,
  "priority": 1
}
```

> Note: `priority` is currently **ignored** by the logic (no queue), but it is logged and can be used in the future.

**Response:**

```json
{
  "tablet_id": 1,
  "channel": 1,
  "ptt_state": "ACTIVE",
  "channel_state": {
    "channel": 1,
    "state": "ACTIVE",
    "active_tablets": [1]
  },
  "tablet_channels": [1]
}
```

### 5.7. `POST /ptt/release`

Tablet releases PTT on a channel.

**Request body:**

```json
{
  "tablet_id": 1,
  "channel": 1
}
```

**Response:**

```json
{
  "tablet_id": 1,
  "channel": 1,
  "ptt_state": "IDLE",
  "channel_state": {
    "channel": 1,
    "state": "IDLE",
    "active_tablets": []
  },
  "tablet_channels": []
}
```

### 5.8. `GET /ptt/state`

Global PTT snapshot.

**Response:**

```json
{
  "timestamp": ...,
  "channels": {
    "1": [1, 3],
    "2": [],
    "3": [5],
    "4": []
  }
}
```

### 5.9. `POST /config/reload`

Manually reload configuration from `config.json` / `config.example.json`.

**Response:**

```json
{
  "config": { "fs": 44100, "frame_size": 1024, "headroom_db": 6.0 },
  "state": { ... }   // current state as in GET /state
}
```

### 5.10. `WS /ws/vu` – VU WebSocket

WebSocket sending VU data ~10 times per second:

```json
{
  "ts": 1763557764.50,
  "vu_db": {
    "tablets": { "1": -240.0, "2": -240.0, "...": -240.0 },
    "channels": { "1": -51.7, "2": -51.7, "3": -51.7, "4": -51.7 }
  }
}
```

On the client side (frontend/tablet) you can use:

- JavaScript `WebSocket` + chart/LED-style visualization,
- or any WebSocket library in Python/TypeScript.

---

## 6. Example usage of `AudioEngineClient`

```python
from audio_manager.client import AudioEngineClient

client = AudioEngineClient(base_url="http://localhost:8000")

# Healthcheck
health = client.get_health()
print("Health:", health)

# Full state snapshot
state = client.get_state()
print("State:", state)

# Only VU levels
vu = client.get_vu_levels()
print("VU:", vu)

# Change headroom
client.update_matrix(headroom_db=6.0)

# PTT – tablet 1 on channel 1
client.ptt_request(tablet_id=1, channel=1)
print("PTT snapshot:", client.get_ptt_state())

# Release PTT
client.ptt_release(tablet_id=1, channel=1)

# Mute a channel and a tablet
client.mute_channel(channel=1, mute=True)
client.mute_tablet(tablet_id=1, mute=True)
```

---

## 7. PTT semantics (important design assumption)

- **No queuing / no floor-control**:
  - multiple tablets can have PTT active on the same channel,
  - PTT does *not* gate audio – it is a logical state only,
  - the audio engine does **not** mute tablets without PTT (in the current version).
- This keeps the system simple and robust against race conditions:
  - UI/tablets can decide locally what to do with PTT (for example, client-side gating),
  - the backend provides a central history and monitoring of PTT events.

If floor-control is needed in the future (only one active speaker, priorities), the `PTTManager` can be extended with:

- per-channel queues,
- `PENDING` / `CONFLICT` states,
- pre-emption based on priority.

