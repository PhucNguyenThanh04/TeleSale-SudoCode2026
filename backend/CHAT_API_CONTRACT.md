# Backend chat and structured tool contract

`POST /api/chat` is an authenticated **operator/channel-adapter** endpoint for
simulated incoming calls and messages. Its Bearer JWT authenticates the
operator, not the customer. A real customer-channel authentication integration
is still required before exposing this API as a public widget.

## Database and processes

Import the BTC release into `btc_source`, then apply these additive migrations
in order: `backend/migrations/0001_chat.sql`, `backend/migrations/0002_tools.sql`,
`backend/migrations/0003_channel_identity.sql`, and
`ai-services/migrations/0001_memory.sql` through
`ai-services/migrations/0004_pending_facts.sql`. The first schema is the immutable BTC
snapshot; `app_runtime` holds chat, orders, callbacks and handoffs; `ai_memory`
holds turns, episodes and facts. Set the same `AI_INTERNAL_TOKEN` in
`backend/.env` and `ai-services/.env` for the backend-to-AI request header.

## Operator chat request

The first turn has no `session_id` and provides a trusted channel identity:

```json
{
  "client_msg_id": "11111111-1111-4111-8111-111111111111",
  "session_id": null,
  "channel": "chat_fanpage",
  "channel_identity": "fb.hoa.479",
  "call_date": "2026-10-15",
  "text": "shop oi ...",
  "customer_input_mode": "chat_teencode"
}
```

For `hotline`, use `caller_phone` or `channel_identity` containing the caller
number. Subsequent turns send `session_id`, `text`, and optionally a new
`client_msg_id`. A return interaction starts a **new** session. A shared phone
is ambiguous; AI may stage masked fact candidates but cannot read or write a
customer profile until identity is resolved. An authenticated operator who has
checked the caller separately can call
`POST /api/chat/{session_id}/verify-identity` with `customer_id`, `phone`, and
`confirmation: "operator_verified"`. A phone stated in chat is not proof by
itself. The response includes `client_msg_id`, `session_id`, `agent_text`, `identity_status`,
`needs_handoff`, `handoff_ticket_id`, and optionally `call_brief`.

## Backend to AI service

The backend sends `POST {AI_SERVICE_URL}/v1/chat/turns` with
`X-AI-Internal-Token`, using the same
`client_msg_id` and session ID:

```json
{
  "client_msg_id": "11111111-1111-4111-8111-111111111111",
  "session_id": "22222222-2222-4222-8222-222222222222",
  "channel": "chat_fanpage",
  "channel_identity": "fb.hoa.479",
  "on": "2026-10-15",
  "text": "shop oi ...",
  "input_mode": "chat_teencode"
}
```

The AI service resolves the trusted channel identity using `crm.get_customer`.
The backend checks both response IDs and nonempty `agent_text`. Timeout,
non-2xx, or malformed responses return 503 and roll back the new chat turn.
Text PII is masked before the external model call; business tools still receive
trusted contact details where needed. The AI service provides the returning
customer's Call Brief and refreshes current price/stock against `on`.

## Structured MCP tools

The AI service calls three separate MCP servers on host loopback ports
`8011`, `8012` and `8013`. Catalog and order connect directly to PostgreSQL
with distinct roles; catalog also owns `crm.get_customer`. Order verifies
customer identity and order ownership against PostgreSQL before business
operations. Tool names and required parameter names remain those in BTC's
`schemas/tools.schema.json`.
