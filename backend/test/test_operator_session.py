"""Local cookie session replaces browser Bearer credentials."""

import unittest

from fastapi import HTTPException, Response
from starlette.requests import Request

from app.api.deps import get_current_user_id
from app.api.operator_session import COOKIE_NAME, local_session, visitor_session


class _Redis:
    def __init__(self):
        self.values = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ex):
        self.values[key] = value

    async def expire(self, key, ex):
        return key in self.values


def _request(cookie=None, *, host="127.0.0.1", client="127.0.0.1"):
    headers = [(b"host", f"{host}:8000".encode())]
    if cookie:
        headers.append((b"cookie", f"{COOKIE_NAME}={cookie}".encode()))
    return Request({"type": "http", "method": "POST", "path": "/api/auth/local-session",
                    "scheme": "http", "headers": headers, "client": (client, 1234),
                    "server": (host, 8000), "query_string": b""})


class OperatorSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_cookie_reused_and_other_browser_cannot_access(self):
        redis = _Redis()
        response = Response()
        self.assertEqual(await local_session(_request(), response, redis), {"status": "ready"})
        cookie_header = response.headers["set-cookie"]
        self.assertIn("httponly", cookie_header.lower())
        self.assertIn("samesite=strict", cookie_header.lower())
        token = cookie_header.split(";", 1)[0].split("=", 1)[1]
        operator = await get_current_user_id(_request(token), redis)
        self.assertTrue(operator.startswith("local-demo:"))
        repeat = Response()
        await local_session(_request(token), repeat, redis)
        self.assertNotIn("set-cookie", repeat.headers)
        with self.assertRaises(HTTPException) as missing:
            await get_current_user_id(_request(), redis)
        self.assertEqual(missing.exception.status_code, 401)

    async def test_demo_session_rejects_non_local_request(self):
        with self.assertRaises(HTTPException) as remote:
            await local_session(_request(host="example.com"), Response(), _Redis())
        self.assertEqual(remote.exception.status_code, 403)

    async def test_public_browser_identity_is_pseudonymous_and_reused(self):
        redis = _Redis()
        first = Response()
        result = await visitor_session(_request(host="telesale.ktoxz.id.vn"), first, redis)
        self.assertFalse(result["returning_browser"])
        self.assertIn("secure", first.headers["set-cookie"].lower())
        token = first.headers["set-cookie"].split(";", 1)[0].split("=", 1)[1]
        owner = await get_current_user_id(_request(token, host="telesale.ktoxz.id.vn"), redis)
        self.assertTrue(owner.startswith("web-visitor:"))
        again = Response()
        result = await visitor_session(_request(token, host="telesale.ktoxz.id.vn"), again, redis)
        self.assertTrue(result["returning_browser"])
        self.assertNotIn("set-cookie", again.headers)

    async def test_public_session_rejects_remote_direct_requests(self):
        with self.assertRaises(HTTPException) as remote:
            await visitor_session(_request(host="telesale.ktoxz.id.vn", client="10.0.0.8"),
                                  Response(), _Redis())
        self.assertEqual(remote.exception.status_code, 403)
