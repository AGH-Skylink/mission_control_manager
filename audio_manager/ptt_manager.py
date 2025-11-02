import time, sys
from typing import List, Dict, Set
from queue import PriorityQueue
from models import PTTState, PTTRequest

class PTTManager:
    def __init__(self, channels = range(1,5)):
        self.ptt_queues: Dict[int, PriorityQueue] = {}
        self.active_ptt: Dict[int, Set[id]] = {}
        self.ptt_history: List[dict] = []

        for ch in channels:
            self.ptt_queues[ch] = PriorityQueue()
            self.active_ptt[ch] = set()

    def _log_ptt_event(self, request: PTTRequest, state: PTTState):
        self.ptt_history.append({
            "timestamp": time.time(),
            "tablet_id": request.tablet_id,
            "channel": request.channel,
            "state": state,
            "priority": request.priority
        })

    def request_ptt(self,tablet_id: int, channel: int, priority: int=1) -> PTTState:
        request = PTTRequest(tablet_id=tablet_id, channel=channel, priority=priority)

        if tablet_id in self.active_ptt[channel]:
            return PTTState.ACTIVE

        self.active_ptt[channel].add(tablet_id)
        self._log_ptt_event(request, PTTState.ACTIVE)
        return PTTState.ACTIVE
