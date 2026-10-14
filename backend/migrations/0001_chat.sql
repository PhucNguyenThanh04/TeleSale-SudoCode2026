-- Run after the BTC source import. Runtime conversations stay separate from btc_source.
CREATE SCHEMA IF NOT EXISTS app_runtime;

CREATE TABLE IF NOT EXISTS app_runtime.chat_sessions (
    id uuid PRIMARY KEY,
    created_by text NOT NULL,
    caller_phone text NOT NULL CHECK (caller_phone ~ '^0[0-9]{9}$'),
    channel text NOT NULL CHECK (channel IN ('hotline', 'chat_fanpage', 'zalo_oa', 'web_chat', 'other')),
    call_date date NOT NULL,
    customer_id text,
    identity_status text NOT NULL CHECK (identity_status IN ('known', 'unknown', 'ambiguous')),
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS chat_sessions_customer_idx
    ON app_runtime.chat_sessions (customer_id, created_at DESC);

CREATE TABLE IF NOT EXISTS app_runtime.chat_messages (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id uuid NOT NULL REFERENCES app_runtime.chat_sessions(id) ON DELETE CASCADE,
    turn_no integer NOT NULL CHECK (turn_no > 0),
    role text NOT NULL CHECK (role IN ('customer', 'agent')),
    content text NOT NULL CHECK (length(content) > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (session_id, turn_no, role)
);

CREATE INDEX IF NOT EXISTS chat_messages_session_idx
    ON app_runtime.chat_messages (session_id, turn_no);
