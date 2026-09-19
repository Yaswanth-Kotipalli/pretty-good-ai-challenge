"""Offline tests for the Twilio webhook server (no network, no credentials)."""
from pgai_challenge import server
from pgai_challenge.config import Settings


def _test_settings(**overrides):
    base = dict(
        twilio_account_sid="ACxxx",
        twilio_auth_token="tok",
        caller_number="+13334445555",
        livekit_url="wss://x.livekit.cloud",
        livekit_api_key="k",
        livekit_api_secret="s",
        sip_host="abc123.sip.livekit.cloud",
        deepgram_api_key="dg",
        openai_api_key="oa",
        public_base_url="https://example.ngrok-free.app",
    )
    base.update(overrides)
    return Settings(**base)


def test_twiml_bridges_to_livekit_room():
    app = server.create_app(_test_settings())
    client = app.test_client()
    resp = client.post("/twiml/book_physical")
    assert resp.status_code == 200
    xml = resp.get_data(as_text=True)
    assert "<Dial" in xml
    assert "<Sip>" in xml
    assert "sip:pgai-test@abc123.sip.livekit.cloud" in xml
    assert "record-from-answer" in xml


def test_twiml_includes_sip_auth_when_configured():
    app = server.create_app(_test_settings(sip_trunk_user="u", sip_trunk_password="p"))
    xml = app.test_client().post("/twiml/book_physical").get_data(as_text=True)
    assert 'username="u"' in xml


def test_twiml_never_dials_assessment_number_directly():
    # The assessment number is dialed by the Twilio REST API (runner.py),
    # never inside TwiML. The TwiML leg only bridges to our LiveKit room.
    app = server.create_app(_test_settings())
    xml = app.test_client().post("/twiml/book_physical").get_data(as_text=True)
    assert "+18054398008" not in xml


def test_recording_callback_queues_download():
    app = server.create_app(_test_settings())
    client = app.test_client()
    resp = client.post(
        "/recording-callback?scenario_id=book_physical",
        data={"CallSid": "CA1", "RecordingSid": "RS1",
              "RecordingUrl": "https://api.twilio.com/x"},
    )
    assert resp.status_code == 204


def test_server_port_from_env_is_respected(monkeypatch):
    from unittest.mock import MagicMock, patch

    monkeypatch.setenv("PORT", "5050")
    mock_app = MagicMock()
    with patch.object(server, "create_app", return_value=mock_app):
        server.main()
        mock_app.run.assert_called_once_with(host="0.0.0.0", port=5050)


def test_server_default_port_is_5000(monkeypatch):
    from unittest.mock import MagicMock, patch

    monkeypatch.delenv("PORT", raising=False)
    mock_app = MagicMock()
    with patch.object(server, "create_app", return_value=mock_app):
        server.main()
        mock_app.run.assert_called_once_with(host="0.0.0.0", port=5000)
