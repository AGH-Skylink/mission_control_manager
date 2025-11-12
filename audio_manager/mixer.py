from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from typing import Dict

FS = 44100
SAMPLE_WIDTH_BITS = 16
FRAME_SIZE = 1024
MAX_INT16 = 32767.0

def dbfs(x_rms: float, eps: float = 1e-12) -> float:
    return 20.0 * np.log10(max(x_rms,eps))

@dataclass
class VUState:
    tablet_rms: Dict[int,float] = field(default_factory=dict)
    channel_rms: Dict[int,float] = field(default_factory=dict)

@dataclass
class MixConfig:
    tablet_mute: Dict[int,bool] = field(default_factory=dict)
    channel_mute: Dict[int,bool] = field(default_factory=dict)
    uplink:  Dict[int, Dict[int, float]] = field(default_factory=dict)
    downlink:  Dict[int, Dict[int, float]] = field(default_factory=dict)
    headroom_db: float = 12.0


class AudioMixer:
    def __init__(self, num_channels: int = 4, num_tablets: int = 16):
        self.num_channels = num_channels
        self.num_tablets = num_tablets
        self.config = MixConfig()
        self._tablet_in = { tid : np.zeros(FRAME_SIZE, dtype=np.float32) for tid in range(1, num_tablets + 1)}
        self._tablet_out = { tid : np.zeros(FRAME_SIZE, dtype=np.float32) for tid in range(1, num_tablets + 1)}
        self._chan_in = { ch : np.zeros(FRAME_SIZE, dtype=np.float32)  for ch in range(1, num_channels + 1)}
        self._chan_out = {ch : np.zeros(FRAME_SIZE, dtype=np.float32)  for ch in range(1, num_channels + 1)}
        self._ema_alpha = 0.5
        self.vu = VUState(
            tablet_rms={ tid : 0.0  for tid in range(1, self.num_tablets + 1)},
            channel_rms={ ch : 0.0 for ch in range(1, self.num_channels + 1)}
        )
        for ch in range(1, self.num_channels + 1):
            self.config.uplink[ch] = {}
        for tid in range(1, self.num_tablets + 1):
            self.config.downlink[tid] = {}
        self.set_uniform_routing(gain_db=-12.0)

    def set_uniform_routing(self, gain_db: float = -12.0):
        g = 10 **(gain_db / 20.0)
        for ch in range(1, self.num_channels + 1):
            self.config.uplink[ch] ={ tid : g for tid in range(1, self.num_tablets + 1)}
        for tid in range(1, self.num_tablets + 1):
            self.config.downlink[tid] = { ch : g for ch in range(1, self.num_channels + 1)}

    def _soft_limit(self, x: np.ndarray , knee : float = 0.9) -> np.ndarray :
        y = np.tanh(x / knee) * knee
        return y

    def _update_rms(self, kind : str, key: int, frame):
        rms = float(np.sqrt(np.mean(np.square(frame))))
        if kind == 'tablet':
            last = self.vu.tablet_rms.get(key, 0.0)
            self.vu.tablet_rms[key] = last * (1-self._ema_alpha) +rms * self._ema_alpha
        else :
            last = self.vu.channel_rms.get(key, 0.0)
            self.vu.channel_rms[key] = last * (1 - self._ema_alpha) + rms * self._ema_alpha

    def vu_levels_db(self):
        return {
            "tablets" : { tid : float(dbfs(v*1.0000001)) for tid, v in self.vu.tablet_rms.items() },
            "channels" : { ch : float(dbfs(v*1.0000001)) for ch, v in self.vu.channel_rms.items() },
        }

    @staticmethod
    def _to_float(pcm_i16 : np.ndarray) -> np.ndarray:
        if pcm_i16.dtype != np.int16:
            pcm_i16 = pcm_i16.astype(np.int16, copy=False)
        return pcm_i16.astype(np.float32)/MAX_INT16

    @staticmethod
    def _from_float(x : np.ndarray) -> np.ndarray:
        x = np.clip(x, -1.0, 1.0)
        return (x*MAX_INT16).astype(np.int16)


    def set_uplink_matrix(self, matrix: Dict[int, Dict[int, float]]):
        self.config.uplink= {int(ch) : {int(tid) : float(gain) for tid, gain in row.items()} for ch, row in matrix.items()}

    def set_downlink_matrix(self, matrix: Dict[int, Dict[int, float]]):
        self.config.downlink = {int(tid) : { int(ch) : float (gain) for ch,gain in row.items()} for tid, row in matrix.items()}

    def set_tablet_mute(self, tid, mute):
        self.config.tablet_mute[int(tid)] = bool(mute)

    def set_channel_mute(self, ch, mute):
        self.config.channel_mute[int(ch)] = bool(mute)

    def push_tablet_frame(self, tid, pcm_i16 : np.ndarray):
        self._tablet_in[int(tid)] = self._to_float(pcm_i16)

    def pull_tablet_frame(self, tid) -> np.ndarray :
        return self._from_float(self._tablet_out[tid])

    def push_channel_frame(self, ch, pcm_i16 : np.ndarray):
        self._chan_in[int(ch)] = self._to_float(pcm_i16)

    def pull_channel_frame(self, ch) -> np.ndarray :
        return self._from_float(self._chan_out[ch])

    def step(self):
        for ch, mapping in self.config.uplink.items():
            acc = np.zeros(FRAME_SIZE, dtype=np.float32)
            if self.config.channel_mute.get(ch, False):
                self._chan_out[ch] = acc
                self._update_rms('channel', ch, acc)
                continue

            sum_g = sum(g for tid, g in mapping.items() if not self.config.tablet_mute.get(tid, False))
            headroom_lin = 10.0 ** (-self.config.headroom_db / 20.0)
            norm = 1.0 if sum_g <= 0 else min(1.0, headroom_lin / max(sum_g, 1e-9))

            for tid, g in mapping.items():
                if self.config.tablet_mute.get(tid, False):
                    continue
                acc += self._tablet_in[tid] * g*norm

            self._chan_out[ch] = self._soft_limit(acc)
            self._update_rms('channel', ch, acc)


        for tid, mapping in self.config.downlink.items():
            acc = np.zeros(FRAME_SIZE, dtype=np.float32)
            if self.config.tablet_mute.get(tid, False):
                self._tablet_out[tid] = acc
                self._update_rms('tablet', tid, acc)
                continue

            sum_g = sum(g for ch, g in mapping.items() if not self.config.channel_mute.get(ch, False))
            headroom_lin = 10.0 ** (-self.config.headroom_db / 20.0)
            norm = 1.0 if sum_g <= 0 else min(1.0, headroom_lin/ max(sum_g, 1e-9))

            for ch, g in mapping.items():
                if self.config.channel_mute.get(ch, False):
                    continue
                acc += self._chan_in[ch] * g*norm

            self._tablet_out[tid] = self._soft_limit(acc)
            self._update_rms('tablet', tid, acc)

