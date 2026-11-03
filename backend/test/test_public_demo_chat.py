"""Public BTC simulator keeps explicit channel identity without weakening validation."""

import unittest
from datetime import date

from fastapi import HTTPException

from app.api.chat import validate_public_demo_turn
from app.schemas.chat import ChatRequest


class PublicDemoChatTests(unittest.TestCase):
    def request(self, channel: str, identity: str) -> ChatRequest:
        return ChatRequest(
            text="Xin chào", channel=channel, channel_identity=identity,
            call_date=date(2026, 10, 15),
        )

    def test_accepts_seed_identity_for_each_supported_channel(self):
        for channel, identity in (
            ("hotline", "0984726714"),
            ("chat_fanpage", "fb.hoa.479"),
            ("zalo_oa", "zalo_hoa73"),
        ):
            with self.subTest(channel=channel):
                validate_public_demo_turn(self.request(channel, identity))

    def test_rejects_anonymous_web_channel(self):
        with self.assertRaises(HTTPException) as caught:
            validate_public_demo_turn(self.request("web_chat", "browser-session"))
        self.assertEqual(caught.exception.status_code, 422)

    def test_rejects_invalid_hotline_number(self):
        with self.assertRaises(HTTPException) as caught:
            validate_public_demo_turn(self.request("hotline", "not-a-phone"))
        self.assertEqual(caught.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
