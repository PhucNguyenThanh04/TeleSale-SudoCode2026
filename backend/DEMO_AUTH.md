# Demo authentication

The demo gateway is `app.voice_main:app`. Two backend-owned accounts map to two
existing `btc_source.customers` profiles. BTC tables are not modified. The
`customer_id` assignment is unique; channel identity comes from the assigned
profile on the server, even if the browser sends another value.

## Setup

1. Install backend dependencies from `backend/requirements.txt` (including
   `PyJWT`, `pwdlib[argon2]` and `asyncpg`). Load BTC data into PostgreSQL first.
2. In `backend/.env`, configure `DATABASE_URL`, `DEMO_JWT_SECRET` (a random key
   at least 32 characters), `DEMO_JWT_MINUTES=60`, and the two account groups
   shown in `.env.example`: username, initial password and existing BTC customer ID.
   Use profiles whose phone/Facebook/Zalo identities are not shared with other
   customers. The seed rejects missing profiles and ambiguous identities.
3. Run from the repository root:

   ```bash
   PYTHONPATH=backend backend/.venv/bin/python -m app.seed_demo_users
   backend/.venv/bin/python -m uvicorn app.voice_main:app --app-dir backend --host 127.0.0.1 --port 8000
   ```

The seed applies `backend/migrations/0007_demo_users.sql` and creates accounts in
one transaction. Running it again preserves existing passwords and assignments;
changing seed variables does not reset an existing account. Database passwords
are Argon2 hashes. Keep `.env` private and out of Git. Initial password variables
can be removed after seeding if you will not rerun the seed command.

Open `/login`, then `/` for voice or `/chat` for text. Use two separate browser
profiles, or a normal window and an incognito window, for two simultaneous
accounts: tabs in the same browser profile share a login cookie. Available
channels and their identities are taken from the assigned BTC profile.

## API and lifetime

- `POST /api/auth/login`: JSON `{ "username": "demo1", "password": "..." }`.
  Sets the `demo_access` HttpOnly, SameSite=Strict cookie; returns the account
  and assigned customer profile, never the JWT or password hash.
- `GET /api/auth/me`: current account and profile; 401 if absent/invalid/expired.
- `POST /api/auth/logout`: removes the browser cookie.
- Text/voice WebSockets and knowledge APIs require login. WebSocket handshakes
  and writes reject a foreign Origin. JWT verification fixes HS256 and validates
  issuer, audience, subject, issued-at and expiry.
- Open WebSockets close with 4401 when their JWT expires. A fresh login is
  required. Each new conversation still gets its own server-generated UUID.
- Set `DEMO_COOKIE_SECURE=true` when serving HTTPS. For a reverse proxy, forward
  the public Host and scheme and configure Uvicorn to trust forwarded headers
  only from that proxy. Do not use a different origin for the frontend.

Scope: demo access tokens only; no refresh tokens or token revocation list.
Logout deletes the local cookie; a copied JWT and other already-open sockets
remain valid until expiry. Knowledge operations retain the gateway's existing
server-configured reviewer permissions; demo accounts do not have separate
reviewer roles. Customer memory and business data are separated by the assigned
BTC customers, not by duplicating customer records or the AI runtime.

## Focused offline verification

```bash
PYTHONPATH=backend:backend/test backend/.venv/bin/python -m pytest -q \
  backend/test/test_demo_auth.py backend/test/test_text_gateway.py \
  backend/test/test_voice_websocket.py backend/test/test_voice_flow.py \
  backend/test/test_knowledge_gateway.py backend/test/test_text_browser.py \
  -o asyncio_default_fixture_loop_scope=function
```

Transport-only tests explicitly use `gateway_fixture.create_app` with a fixed
principal. Auth tests use the real password/JWT/route implementation and replace
only persistence and external AI/speech. The text browser test uses the real
login form, HttpOnly cookie, profile UI, chat WebSocket and logout in Chrome.
`test_demo_auth_database.py` optionally uses `DEMO_TEST_DATABASE_URL`; its fixture
writes are rolled back and it tests the real migration, seed and repository.
No verification calls a model, speech inference, benchmark or live evaluation.
