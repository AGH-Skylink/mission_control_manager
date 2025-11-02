import requests
from loguru import logger
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

class AudioEngineClient:
    def __init__(self, base_url: str = "http://localhost:8000",timeout=(3.05, 10)):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        retries = Retry(total=3, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504])
        self.session.mount("https://", HTTPAdapter(max_retries=retries))
        self.session.mount("http://", HTTPAdapter(max_retries=retries))

    def get_vu_levels(self):
        url = f"{self.base_url}/vu_levels"
        try:
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()
            return {"ok": True, "data": response.json()}
        except requests.HTTPError as e:
            logger.exception(f"HTTP error ({e.response.status_code}) for GET {url}")
            return {"ok": False, "error": str(e)}
        except (requests.Timeout, requests.ConnectionError) as e:
            logger.exception(f"Network error for GET {url}")
            return {"ok": False, "error": "network timeout/connection error"}
        except ValueError as e:
            logger.exception(f"Invalid JSON from {url}")
            return {"ok": False, "error": "invalid json"}

    def set_ptt_state(self, channel_id: int, mute: bool = False, gate_open: bool = True):
        url = f"{self.base_url}/ptt_state"
        payload = {"channel_id": channel_id, "mute": mute, "gate_open": gate_open}
        try:
            response = requests.post(url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            return {"ok": True, "data": response.json()}
        except requests.HTTPError as e:
            status = getattr(e.response, "status_code", "?")
            logger.exception(f"HTTP {status} for POST {url} payload={payload}")
            return {"ok": False, "error": f"http {status}"}
        except (requests.Timeout, requests.ConnectionError) as e:
            logger.exception(f"Network error for POST {url} payload={payload}")
            return {"ok": False, "error": "network timeout/connection error"}
        except ValueError as e:
            logger.exception(f"Invalid JSON from {url} for payload={payload}")
            return {"ok": False, "error": "invalid json"}