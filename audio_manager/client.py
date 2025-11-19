import requests
from typing import Any, Dict, Optional

from loguru import logger
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter


class AudioEngineClient:
    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        timeout: tuple[float, float] = (3.05, 10.0),
        max_retries: int = 3,
        backoff_factor: float = 0.3,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

        session = requests.Session()
        retries = Retry(
            total=max_retries,
            backoff_factor=backoff_factor,
            status_forcelist=(500, 502, 503, 504),
        )
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        self.session = session

    def _request(
        self,
        method: str,
        path: str,
        json: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"

        try:
            response = self.session.request(
                method=method.upper(),
                url=url,
                json=json,
                timeout=self.timeout,
            )
            response.raise_for_status()

            try:
                data = response.json()
            except ValueError:
                data = response.text

            return {"ok": True, "data": data, "error": None}

        except requests.HTTPError as e:
            status = getattr(e.response, "status_code", "?")
            logger.exception(
                f"HTTP {status} for {method.upper()} {url} payload={json!r}"
            )
            return {"ok": False, "data": None, "error": f"http {status}"}

        except (requests.Timeout, requests.ConnectionError):
            logger.exception(
                f"Network error for {method.upper()} {url} payload={json!r}"
            )
            return {
                "ok": False,
                "data": None,
                "error": "network timeout/connection error",
            }

        except Exception:
            logger.exception(
                f"Unexpected error for {method.upper()} {url} payload={json!r}"
            )
            return {"ok": False, "data": None, "error": "unexpected error"}


    def get_health(self) -> Dict[str, Any]:
        return self._request("GET", "/health")

    def get_state(self) -> Dict[str, Any]:
        return self._request("GET", "/state")

    def get_vu_levels(self) -> Dict[str, Any]:
        res = self.get_state()
        if not res["ok"]:
            return res

        state = res["data"] or {}
        vu = state.get("vu_db")
        return {"ok": True, "data": vu, "error": None}

    def update_matrix(
        self,
        uplink: Optional[Dict[int, Dict[int, float]]] = None,
        downlink: Optional[Dict[int, Dict[int, float]]] = None,
        headroom_db: Optional[float] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if uplink is not None:
            payload["uplink"] = uplink
        if downlink is not None:
            payload["downlink"] = downlink
        if headroom_db is not None:
            payload["headroom_db"] = float(headroom_db)

        return self._request("POST", "/matrix", json=payload)

    def mute_channel(self, channel: int, mute: bool = True) -> Dict[str, Any]:
        return self._request(
            "POST",
            f"/channel/{channel}/mute",
            json={"mute": bool(mute)},
        )

    def mute_tablet(self, tablet_id: int, mute: bool = True) -> Dict[str, Any]:
        return self._request(
            "POST",
            f"/tablet/{tablet_id}/mute",
            json={"mute": bool(mute)},
        )

    def ptt_request(
        self,
        tablet_id: int,
        channel: int,
        priority: int = 1,
    ) -> Dict[str, Any]:

        payload = {
            "tablet_id": int(tablet_id),
            "channel": int(channel),
            "priority": int(priority),
        }
        return self._request("POST", "/ptt/request", json=payload)

    def ptt_release(self, tablet_id: int, channel: int) -> Dict[str, Any]:
        payload = {
            "tablet_id": int(tablet_id),
            "channel": int(channel),
        }
        return self._request("POST", "/ptt/release", json=payload)

    def get_ptt_state(self) -> Dict[str, Any]:
        return self._request("GET", "/ptt/state")
