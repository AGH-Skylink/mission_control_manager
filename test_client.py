from audio_manager.client import AudioEngineClient

def main() -> None:
    client = AudioEngineClient(base_url="http://localhost:8000")

    print("=== /health ===")
    print(client.get_health(), "\n")

    print("=== /state (VU + config + PTT) ===")
    state = client.get_state()
    print(state, "\n")

    print("=== Ustawiam headroom_db = 6 dB przez /matrix ===")
    res = client.update_matrix(headroom_db=6.0)
    print(res, "\n")

    print("=== PTT: tablet 1 na kanale 1 – request ===")
    res = client.ptt_request(tablet_id=1, channel=1, priority=1)
    print(res, "\n")

    print("=== PTT: globalny snapshot ===")
    print(client.get_ptt_state(), "\n")

    print("=== PTT: tablet 1 na kanale 1 – release ===")
    res = client.ptt_release(tablet_id=1, channel=1)
    print(res, "\n")

    print("=== Mute kanału 1 ===")
    res = client.mute_channel(channel=1, mute=True)
    print(res, "\n")

    print("=== Mute tablet 1 ===")
    res = client.mute_tablet(tablet_id=1, mute=True)
    print(res, "\n")


if __name__ == "__main__":
    main()