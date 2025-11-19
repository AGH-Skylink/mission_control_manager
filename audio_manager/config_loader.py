from __future__ import annotations

import json
import os
from typing import Dict, Any
from loguru import logger

try:
    from .mixer import FS, FRAME_SIZE
except Exception:
    FS = 44100
    FRAME_SIZE = 1024

DEFAULT_CONFIG: Dict[str, Any] = {
    "fs": FS,
    "frame_size": FRAME_SIZE,
    "headroom_db": 12.0,
}


def load_engine_config(
    path: str = "config.json",
    example_path: str = "config.example.json",
) -> Dict[str, Any]:

    cfg = DEFAULT_CONFIG.copy()
    chosen: str | None = None

    if os.path.exists(path):
        chosen = path
    elif os.path.exists(example_path):
        chosen = example_path

    if chosen is None:
        logger.warning(
            "No config.json or config.example.json found, using built-in defaults: "
            f"{cfg!r}"
        )
        return cfg

    try:
        with open(chosen, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("config JSON root must be an object")

        for key in DEFAULT_CONFIG.keys():
            if key in data:
                cfg[key] = data[key]

        logger.info(f"Loaded audio engine config from {chosen}: {cfg!r}")
    except Exception as exc:
        logger.exception(
            f"Failed to load config from {chosen}, falling back to defaults"
        )
        return cfg

    if cfg["fs"] != FS:
        logger.warning(
            "Config fs != FS defined in code "
            f"(config={cfg['fs']}, code={FS}). Using code value for processing."
        )
    if cfg["frame_size"] != FRAME_SIZE:
        logger.warning(
            "Config frame_size != FRAME_SIZE defined in code "
            f"(config={cfg['frame_size']}, code={FRAME_SIZE}). "
            "Using code value for processing."
        )

    return cfg
