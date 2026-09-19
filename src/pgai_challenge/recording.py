"""Download Twilio call recordings, tolerating Twilio's callback race.

Twilio fires the recording-status callback *before* the media file is
actually downloadable from their CDN, so the first download attempts
return 404. Instead of failing, we retry with backoff. (This exact bug
bit a previous submission's build; the retry loop is the fix.)
"""
import time
from pathlib import Path

import requests

RECORDING_DIR = Path("recordings")


def download_recording(
    recording_url: str,
    dest: Path,
    account_sid: str,
    auth_token: str,
    attempts: int = 12,
    base_delay: float = 5.0,
) -> Path:
    """Download one recording, retrying on 404 until the media is ready."""
    url = recording_url if recording_url.endswith(".mp3") else recording_url + ".mp3"
    last_status = None
    for i in range(attempts):
        resp = requests.get(url, auth=(account_sid, auth_token), timeout=30)
        last_status = resp.status_code
        if resp.status_code == 200 and resp.content:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.content)
            return dest
        if resp.status_code == 404:
            time.sleep(base_delay * (i + 1))  # linear backoff: 5s, 10s, 15s, ...
            continue
        resp.raise_for_status()
    raise RuntimeError(
        f"Recording not downloadable after {attempts} attempts "
        f"(last status {last_status}): {url}"
    )


def download_pending(account_sid: str, auth_token: str) -> list:
    """Download every recording queued by the /recording-callback webhook.

    Only successfully downloaded entries leave the queue. Recordings are the
    single highest-stakes artifact in this project, so a failed download must
    stay queued and be retryable by re-running this module -- draining the
    queue up front would discard the only copy of the media URL.
    """
    queue = RECORDING_DIR / "pending.jsonl"
    done = []
    if not queue.exists():
        return done
    import json

    lines = [l for l in queue.read_text(encoding="utf-8").splitlines() if l.strip()]
    still_pending = []
    for line in lines:
        item = json.loads(line)
        dest = RECORDING_DIR / f"{item['scenario_id']}_{item['recording_sid']}.mp3"
        try:
            download_recording(
                item["recording_url"], dest, account_sid, auth_token
            )
            done.append(str(dest))
        except Exception as e:  # noqa: BLE001 - keep going, report at the end
            print(f"FAILED {item['recording_sid']}: {e} (left queued, re-run to retry)")
            still_pending.append(line)
    queue.write_text(
        "\n".join(still_pending) + ("\n" if still_pending else ""), encoding="utf-8"
    )
    return done


def main() -> None:
    from .config import load_settings

    settings = load_settings()
    done = download_pending(settings.twilio_account_sid, settings.twilio_auth_token)
    print(f"Downloaded {len(done)} recording(s).")
    for d in done:
        print(" -", d)


if __name__ == "__main__":
    main()
