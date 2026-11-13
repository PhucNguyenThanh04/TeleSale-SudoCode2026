"""The call UI and worklet must be served by the voice gateway itself."""
from fastapi.testclient import TestClient

from app.configs import VoiceSettings
from gateway_fixture import create_app


def test_voice_site_and_capture_worklet_are_available():
    with TestClient(create_app(VoiceSettings(_env_file=None))) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'lang="vi"' in page.text
        assert 'id="start-call"' in page.text
        assert 'id="end-call"' in page.text
        for asset in ("call.js", "audio.js", "capture-worklet.js", "style.css"):
            response = client.get(f"/assets/{asset}")
            assert response.status_code == 200
            if asset.endswith(".js"):
                assert "javascript" in response.headers["content-type"]
        assert client.get("/assets/../backend/.env").status_code == 404
