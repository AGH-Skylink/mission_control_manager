from __future__ import annotations

import asyncio
import time
from typing import Dict, Any

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from loguru import logger
from pydantic import BaseModel, validator

from audio_manager.mixer import AudioMixer, FRAME_SIZE, FS, MAX_INT16
from audio_manager.ptt_manager import PTTManager
from audio_manager.models import PTTState
from audio_manager.logger import SystemMonitor
from audio_manager.config_loader import load_engine_config


app = FastAPI(title="Mission Control Manager API", version="0.1.0")
engine_cfg = load_engine_config()
mixer = AudioMixer()
mixer.config.headroom_db = float(engine_cfg.get("headroom_db", mixer.config.headroom_db))
ptt_manager = PTTManager(channels=range(1, mixer.num_channels + 1))
monitor = SystemMonitor(service_name="mission-control-audio")


class MatrixIn(BaseModel):
    uplink: Dict[int, Dict[int, float]] | None = None
    downlink: Dict[int, Dict[int, float]] | None = None
    headroom_db: float | None = None

    @validator("uplink", "downlink", pre=True)
    def _keys_to_int(cls, v):
        if v is None:
            return v
        return {
            int(ch): {int(tid): float(gain) for tid, gain in row.items()}
            for ch, row in v.items()
        }


class MuteRequest(BaseModel):
    mute: bool


class PTTRequestIn(BaseModel):
    tablet_id: int
    channel: int
    priority: int = 1


class PTTReleaseIn(BaseModel):
    tablet_id: int
    channel: int


@app.get("/health")
async def health() -> Dict[str, Any]:
    payload = {
        "status": "ok",
        "ts": time.time(),
        "num_channels": mixer.num_channels,
        "num_tablets": mixer.num_tablets,
        "fs": FS,
        "frame_size": FRAME_SIZE,
        "config": engine_cfg,
    }
    monitor.log_event("health.check", event_data=payload, level="DEBUG")
    return payload


@app.get("/state")
async def state() -> Dict[str, Any]:
    vu_db = mixer.vu_levels_db()
    config = {
        "headroom_db": mixer.config.headroom_db,
        "tablet_mute": mixer.config.tablet_mute,
        "channel_mute": mixer.config.channel_mute,
        "uplink": mixer.config.uplink,
        "downlink": mixer.config.downlink,
    }
    ptt = ptt_manager.snapshot()

    return {
        "ts": time.time(),
        "vu_db": vu_db,
        "config": config,
        "ptt": ptt,
    }


@app.post("/matrix")
async def update_matrix(matrix: MatrixIn) -> Dict[str, Any]:
    changed = {
        "uplink_changed": matrix.uplink is not None,
        "downlink_changed": matrix.downlink is not None,
        "headroom_changed": matrix.headroom_db is not None,
    }

    if matrix.uplink is not None:
        mixer.set_uplink_matrix(matrix.uplink)
    if matrix.downlink is not None:
        mixer.set_downlink_matrix(matrix.downlink)
    if matrix.headroom_db is not None:
        mixer.config.headroom_db = float(matrix.headroom_db)

    monitor.log_event(
        "matrix.updated",
        event_data=changed,
        message="Mixing matrix / headroom updated",
    )

    return await state()


@app.post("/channel/{channel}/mute")
async def mute_channel(channel: int, req: MuteRequest) -> Dict[str, Any]:
    mixer.set_channel_mute(channel, req.mute)
    monitor.log_event(
        "channel.mute",
        event_data={"channel": channel, "mute": req.mute},
        message="Channel mute updated",
    )
    return await state()


@app.post("/tablet/{tablet_id}/mute")
async def mute_tablet(tablet_id: int, req: MuteRequest) -> Dict[str, Any]:
    mixer.set_tablet_mute(tablet_id, req.mute)
    monitor.log_event(
        "tablet.mute",
        event_data={"tablet_id": tablet_id, "mute": req.mute},
        message="Tablet mute updated",
    )
    return await state()


@app.post("/ptt/request")
async def ptt_request(req: PTTRequestIn) -> Dict[str, Any]:
    new_state: PTTState = ptt_manager.request_ptt(
        tablet_id=req.tablet_id, channel=req.channel, priority=req.priority
    )
    channel_state = ptt_manager.get_channel_state(req.channel)
    tablet_channels = ptt_manager.get_tablet_channels(req.tablet_id)

    monitor.log_event(
        "ptt.request",
        event_data={
            "tablet_id": req.tablet_id,
            "channel": req.channel,
            "priority": req.priority,
            "ptt_state": new_state.value,
            "channel_active_tablets": channel_state["active_tablets"],
        },
        message="PTT request handled",
    )

    return {
        "tablet_id": req.tablet_id,
        "channel": req.channel,
        "ptt_state": new_state.value,
        "channel_state": channel_state,
        "tablet_channels": tablet_channels,
    }


@app.post("/ptt/release")
async def ptt_release(req: PTTReleaseIn) -> Dict[str, Any]:
    new_state: PTTState = ptt_manager.release_ptt(
        tablet_id=req.tablet_id, channel=req.channel
    )
    channel_state = ptt_manager.get_channel_state(req.channel)
    tablet_channels = ptt_manager.get_tablet_channels(req.tablet_id)

    monitor.log_event(
        "ptt.release",
        event_data={
            "tablet_id": req.tablet_id,
            "channel": req.channel,
            "ptt_state": new_state.value,
            "channel_active_tablets": channel_state["active_tablets"],
        },
        message="PTT release handled",
    )

    return {
        "tablet_id": req.tablet_id,
        "channel": req.channel,
        "ptt_state": new_state.value,
        "channel_state": channel_state,
        "tablet_channels": tablet_channels,
    }


@app.get("/ptt/state")
async def ptt_state() -> Dict[str, Any]:
    """Globalny snapshot PTT dla wszystkich kanałów."""
    return ptt_manager.snapshot()


@app.post("/config/reload")
async def reload_config() -> Dict[str, Any]:
    global engine_cfg
    engine_cfg = load_engine_config()
    mixer.config.headroom_db = float(
        engine_cfg.get("headroom_db", mixer.config.headroom_db)
    )
    monitor.log_event(
        "config.reload",
        event_data=engine_cfg,
        message="Engine config reloaded",
    )
    return {"config": engine_cfg, "state": await state()}


@app.websocket("/ws/vu")
async def websocket_vu(ws: WebSocket) -> None:
    await ws.accept()
    monitor.log_event(
        "ws.vu.connected",
        event_data={},
        message="VU websocket client connected",
    )

    try:
        while True:
            payload = {
                "ts": time.time(),
                "vu_db": mixer.vu_levels_db(),
            }
            await ws.send_json(payload)
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        monitor.log_event(
            "ws.vu.disconnected",
            event_data={},
            message="VU websocket client disconnected",
        )
    except Exception as e:
        monitor.log_error_event(
            "ws.vu.error",
            exc=e,
            event_data={},
            message="Error in VU websocket",
        )
        logger.exception("Error in VU websocket")
    finally:
        try:
            await ws.close()
        except Exception:
            pass
        monitor.log_event(
            "ws.vu.closed",
            event_data={},
            message="VU websocket closed",
        )


async def _engine_loop() -> None:
    monitor.log_event(
        "engine.start",
        event_data={},
        message="Audio engine simulation loop starting",
    )

    freqs = {tid: 300.0 + 10.0 * tid for tid in range(1, mixer.num_tablets + 1)}
    t = 0.0
    frame_dt = FRAME_SIZE / FS

    try:
        zeros = np.zeros(FRAME_SIZE, dtype=np.int16)

        while True:
            loop_start = time.perf_counter()

            for tid in range(1, mixer.num_tablets + 1):
                f = freqs[tid]
                t_vec = t + np.arange(FRAME_SIZE) / FS
                samples = 0.05 * np.sin(2.0 * np.pi * f * t_vec)  # ok. -26 dBFS
                pcm = (samples * MAX_INT16).astype(np.int16)
                mixer.push_tablet_frame(tid, pcm)

            for ch in range(1, mixer.num_channels + 1):
                mixer.push_channel_frame(ch, zeros)

            mixer.step()

            t += frame_dt

            elapsed = time.perf_counter() - loop_start
            sleep_time = max(0.0, frame_dt - elapsed)
            await asyncio.sleep(sleep_time)
    except asyncio.CancelledError:
        monitor.log_event(
            "engine.cancelled",
            event_data={},
            message="Audio engine simulation cancelled",
        )
    except Exception as e:
        monitor.log_error_event(
            "engine.fatal_error",
            exc=e,
            event_data={},
            message="Audio engine fatal error",
        )
        logger.exception("Audio engine fatal error")
    finally:
        monitor.log_event(
            "engine.stopped",
            event_data={},
            message="Audio engine simulation fully stopped",
        )


@app.on_event("startup")
async def startup() -> None:
    try:
        asyncio.create_task(_engine_loop())
        monitor.log_event(
            "api.startup",
            event_data={
                "num_channels": mixer.num_channels,
                "num_tablets": mixer.num_tablets,
                "fs": FS,
                "frame_size": FRAME_SIZE,
            },
            message="Mission Control Manager API started successfully",
        )
    except Exception as e:
        monitor.log_error_event(
            "api.startup_error",
            exc=e,
            event_data={},
            message="Startup error",
        )
        logger.exception("Startup error")
