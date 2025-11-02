from pydantic import BaseModel
from typing import Dict,List
from enum import Enum

class PTTState(str, Enum):
    IDLE = "IDLE"
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    CONFLICT = "CONFLICT"

class PTTRequest(BaseModel):
    tablet_id: int
    channel: int
    priority: int = 1
    timestamp: float
    state: PTTState = PTTState.IDLE

class MixingMatrix(BaseModel):
    downlink: Dict[str, List[str]]
    uplink: Dict[str, List[str]]
    priorities: Dict[int, int]
