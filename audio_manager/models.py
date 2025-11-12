from pydantic import BaseModel
from typing import Dict
from enum import Enum

class PTTState(str, Enum):
    IDLE = "IDLE"
    ACTIVE = "ACTIVE"

class PTTRequest(BaseModel):
    tablet_id: int
    channel: int
    priority: int = 1
    timestamp: float | None = None
    state: PTTState = PTTState.IDLE

class MixingMatrix(BaseModel):
    downlink: Dict[int, Dict[int, float]]
    uplink: Dict[int, Dict[int, float]]