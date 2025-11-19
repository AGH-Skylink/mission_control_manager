import time
from typing import List, Dict, Set
from .models import PTTState, PTTRequest


class PTTManager:
    def __init__(self, channels=range(1, 5)):
        self.active_ptt: Dict[int, Set[int]] = {}
        self.ptt_history: List[dict] = []

        for ch in channels:
            self.active_ptt[ch] = set()

    def _log_ptt_event(self, request: PTTRequest, state: PTTState) -> None:
        event = {
            "timestamp": request.timestamp or time.time(),
            "tablet_id": request.tablet_id,
            "channel": request.channel,
            "state": state.value,
            "priority": request.priority,
        }
        self.ptt_history.append(event)

        if len(self.ptt_history) > 1000:
            self.ptt_history = self.ptt_history[-1000:]

    def request_ptt(self, tablet_id: int, channel: int, priority: int = 1) -> PTTState:
        if channel not in self.active_ptt:
            self.active_ptt[channel] = set()

        if tablet_id in self.active_ptt[channel]:
            return PTTState.ACTIVE

        self.active_ptt[channel].add(tablet_id)

        req = PTTRequest(
            tablet_id=tablet_id,
            channel=channel,
            priority=priority,
            timestamp=time.time(),
            state=PTTState.ACTIVE,
        )
        self._log_ptt_event(req, PTTState.ACTIVE)

        return PTTState.ACTIVE

    def release_ptt(self, tablet_id: int, channel: int) -> PTTState:
        if channel not in self.active_ptt or tablet_id not in self.active_ptt[channel]:
            return PTTState.IDLE

        self.active_ptt[channel].remove(tablet_id)

        req = PTTRequest(
            tablet_id=tablet_id,
            channel=channel,
            priority=1,
            timestamp=time.time(),
            state=PTTState.IDLE,
        )
        self._log_ptt_event(req, PTTState.IDLE)

        return PTTState.IDLE

    def get_channel_state(self, channel: int) -> dict:
        active = sorted(self.active_ptt.get(channel, set()))
        state = PTTState.ACTIVE if active else PTTState.IDLE
        return {
            "channel": channel,
            "state": state.value,
            "active_tablets": active,
        }

    def get_tablet_channels(self, tablet_id: int) -> List[int]:
        return sorted(
            ch for ch, tablets in self.active_ptt.items() if tablet_id in tablets
        )

    def snapshot(self) -> dict:
        return {
            "timestamp": time.time(),
            "channels": {
                ch: sorted(tablets) for ch, tablets in self.active_ptt.items()
            },
        }
