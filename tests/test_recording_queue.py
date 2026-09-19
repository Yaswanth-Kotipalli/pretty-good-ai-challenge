"""The pending-recording queue must never lose an undownloaded media URL.

Recordings are the highest-stakes artifact in this project: the assessment is
graded on the audio first. A failed download has to stay queued so re-running
the downloader retries it, instead of discarding the only copy of the URL.
"""
import json

import pgai_challenge.recording as recording


def _queue(tmp_path, items):
    """Point the module at a temp dir and seed its pending queue."""
    recording.RECORDING_DIR = tmp_path
    queue = tmp_path / "pending.jsonl"
    queue.write_text(
        "\n".join(json.dumps(item) for item in items) + "\n", encoding="utf-8"
    )
    return queue


def _writes_a_file(url, dest, account_sid, auth_token, **kwargs):
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"audio")
    return dest


def test_failed_download_stays_queued_for_retry(tmp_path, monkeypatch):
    # Arrange: two queued recordings; the second one never downloads
    queue = _queue(
        tmp_path,
        [
            {
                "scenario_id": "book_physical",
                "recording_sid": "RS_ok",
                "recording_url": "https://example.invalid/ok",
            },
            {
                "scenario_id": "refill_urgent",
                "recording_sid": "RS_bad",
                "recording_url": "https://example.invalid/bad",
            },
        ],
    )

    def fake_download(url, dest, account_sid, auth_token, **kwargs):
        if url.endswith("bad"):
            raise RuntimeError("recording never became downloadable")
        return _writes_a_file(url, dest, account_sid, auth_token)

    monkeypatch.setattr(recording, "download_recording", fake_download)

    # Act
    done = recording.download_pending("ACxxx", "token")

    # Assert: the successful one left the queue, the failed one survived
    assert len(done) == 1
    remaining = [json.loads(l) for l in queue.read_text().splitlines() if l.strip()]
    assert [r["recording_sid"] for r in remaining] == ["RS_bad"]


def test_queue_is_emptied_when_everything_succeeds(tmp_path, monkeypatch):
    # Arrange
    queue = _queue(
        tmp_path,
        [
            {
                "scenario_id": "cancel",
                "recording_sid": "RS1",
                "recording_url": "https://example.invalid/1",
            }
        ],
    )
    monkeypatch.setattr(recording, "download_recording", _writes_a_file)

    # Act
    done = recording.download_pending("ACxxx", "token")

    # Assert
    assert len(done) == 1
    assert queue.read_text().strip() == ""
