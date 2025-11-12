# Mission Control Manager — core mixer & API scaffold

To jest punkt startowy z działającym mikserem i API:

- Równoległy miks **bez kolejek PTT** (wiele tabletów może mówić naraz).
- Matryce routingu: uplink (tablety→kanały) i downlink (kanały→tablety).
- **Headroom** + **soft-limiter** (brak clipu przy wielu mówcach).
- **VU** (RMS→dBFS) z wygładzeniem, WebSocket ~10 Hz dla UI.

Uruchom:
```bash
pip install -r requirements.txt
uvicorn api:app --reload --port 8000
