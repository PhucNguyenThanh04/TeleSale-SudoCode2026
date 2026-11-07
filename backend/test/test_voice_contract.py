import pytest
from pydantic import ValidationError

from app.schemas.voice import parse_command


def test_start_keeps_identity_and_date():
    command = parse_command({"event": "start", "channel": "zalo_oa",
                             "channel_identity": "zalo_dung99", "on": "2026-10-15"})
    assert command.channel_identity == "zalo_dung99"
    assert command.on.isoformat() == "2026-10-15"


@pytest.mark.parametrize("payload", [
    {"event": "start", "channel": "invalid", "channel_identity": "x", "on": "2026-10-15"},
    {"event": "start", "channel": "zalo_oa", "channel_identity": " ", "on": "2026-10-15"},
    {"event": "start", "channel": "zalo_oa", "on": "bad-date"},
    {"event": "playback_finished"},
    {"event": "unknown"},
])
def test_invalid_commands(payload):
    with pytest.raises(ValidationError):
        parse_command(payload)


def test_playback_and_end():
    assert parse_command({"event": "playback_finished", "turn_id": "t1"}).turn_id == "t1"
    assert parse_command({"event": "end"}).event == "end"
