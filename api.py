from __future__ import annotations

import asyncio,time
from typing import Dict
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, validator
from loguru import logger
import numpy as np

from audio_manager.mixer import AudioMixer, FRAME_SIZE

app = FastAPI(title="Mission Control Manager API", version="0.1.0")
mixer = AudioMixer()


class MatrixIn(BaseModel):
    uplink: Dict[int, Dict[int, float]] | None = None
    downlink: Dict[int, Dict[int, float]] | None = None
    headroom_db: float | None = None

    @validator('headroom_db')
    def validate_headroom(cls, v):
        if v is not None and (v < 0 or v > 60):
            raise ValueError('Headroom must be between 0 and 60 dB')
        return v

@app.get("/health")
def health():
    try:
        if not hasattr(mixer, 'num_channels'):
            return {"ok": False, "error": "Mixer not initialized"}

        for tid in range(1, mixer.num_tablets + 1):
            if len(mixer._tablet_in.get(tid, [])) != FRAME_SIZE:
                return {"ok": False, "error": f"Tablet {tid} buffer corrupted"}

        vu_data = mixer.vu_levels_db()
        return {
            "ok": True,
            "ts": time.time(),
            "mixer_channels": mixer.num_channels,
            "mixer_tablets": mixer.num_tablets,
            "vu_working": True
        }

    except Exception as e:
        logger.error(f"Health endpoint error: {e}")
        return {"ok": False, "error": str(e), "ts": time.time()}

@app.get("/state")
def state():
    try:
        return {
            "vu_db": mixer.vu_levels_db(),
            "routing": {
                "uplink": mixer.config.uplink.copy(),
                "downlink": mixer.config.downlink.copy(),
            },
            "mute": {
                "tablets": mixer.config.tablet_mute.copy(),
                "channels": mixer.config.channel_mute.copy(),
            },
            "headroom_db": mixer.config.headroom_db,
            "frame_size": FRAME_SIZE,
            "ts": time.time()
        }
    except Exception as e:
        logger.error(f"State endpoint error: {e}")
        return {"ok": False, "error": "Could not retrieve system state", "ts": time.time()}

@app.post("/matrix")
def set_matrix(matrix: MatrixIn):
    try:
        if matrix.uplink is not None:
            mixer.set_uplink_matrix(matrix.uplink)
            logger.info(f"Uplink matrix updated: {len(matrix.uplink)} channels")
        if matrix.downlink is not None:
            mixer.set_downlink_matrix(matrix.downlink)
            logger.info(f"Downlink matrix updated: {len(matrix.downlink)} tablets")
        if matrix.headroom_db is not None:
            mixer.config.headroom_db = float(matrix.headroom_db)
            logger.info(f"Headroom db updated to: {matrix.headroom_db} db")

        return {"ok": True, "ts": time.time()}

    except Exception as e:
        logger.error(f"Matrix endpoint error: {e}")
        return {"ok": False, "error": str(e), "ts": time.time()}

@app.post("/channel/{ch}/mute")
def mute_channel(ch: int, mute: bool = True):
    try:
        if ch < 1 or ch > mixer.num_channels:
            return {"ok": False, "error": f"Channel {ch} out of range (1-{mixer.num_channels})", "ts": time.time()}

        mixer.set_channel_mute(ch, mute)
        logger.info(f"Channel {ch} mute set to {mute}")
        return {"ok": True, "channel": ch, "mute": mute, "ts": time.time()}

    except Exception as e:
        logger.error(f"Channel mute endpoint error: {e}")
        return {"ok": False, "error": str(e), "ts": time.time()}

@app.post("/tablet/{tid}/mute")
def mute_tablet(tid: int, mute: bool = True):
    try:
        if tid < 1 or tid > mixer.num_tablets:
            return {"ok": False, "error": f"Tablet {tid} out of range (1-{mixer.num_tablets})", "ts": time.time()}

        mixer.set_tablet_mute(tid, mute)
        logger.info(f"Tablet {tid} mute set to {mute}")
        return {"ok": True, "tablet": tid, "mute": mute, "ts": time.time()}

    except Exception as e:
        logger.error(f"Tablet mute endpoint error: {e}")
        return {"ok": False, "error": str(e), "ts": time.time()}

@app.websocket("/ws/vu")
async def ws_vu(ws: WebSocket):
    await ws.accept()
    logger.info("VU WebSocket connected")
    try:
        while True:
            try:
                vu_data = mixer.vu_levels_db()
                await ws.send_json(vu_data)
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"VU WebSocket send error: {e}")
                break
    except WebSocketDisconnect:
        logger.info("VU WebSocket disconnected")
        return


async def _engine_loop():
    t = 0.0
    logger.info("Audio engine simulation started")
    try:
        while True:
            try:
                for tid in range(1, 17):
                    freq = 300 + (tid % 5) * 110
                    phase = (t + tid) * freq * 2 * 3.14159265 / 44100.0
                    frame = (0.1 * np.sin(phase + np.arange(FRAME_SIZE) * (2 * np.pi * freq / 44100.0))).astype(
                        np.float32)
                    mixer.push_tablet_frame(tid, (frame * 32767.0).astype(np.int16))

                for ch in range(1, 5):
                    mixer.push_channel_frame(ch, np.zeros(FRAME_SIZE, dtype=np.int16))

                mixer.step()
                t += FRAME_SIZE

                if int(t) % (5 * 44100) < FRAME_SIZE:
                    logger.debug(f"Audio engine running, processed {t / 44100:.1f}s of audio")

                await asyncio.sleep(FRAME_SIZE / 44100.0)

            except Exception as e:
                logger.error(f"Audio engine processing error: {e}")
                await asyncio.sleep(1.0)

    except asyncio.CancelledError:
        logger.info("Audio engine simulation stopped (Cancelled)")
        raise

    except Exception as e:
        logger.error(f"Audio engine fatal error: {e}")
        logger.info("Audio engine simulation stopped due to fatal error")
    finally:
        logger.info("Audio engine simulation fully stopped")


@app.on_event("startup")
async def startup():
    try:
        asyncio.create_task(_engine_loop())
        logger.info("Mission Control Manager API started successfully")
    except Exception as e:
        logger.error(f"Startup error: {e}")

