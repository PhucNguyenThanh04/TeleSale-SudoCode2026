CREATE SCHEMA IF NOT EXISTS app_runtime;
CREATE SEQUENCE IF NOT EXISTS app_runtime.tool_order_seq START WITH 600001;
CREATE TABLE IF NOT EXISTS app_runtime.tool_orders (
    order_id text PRIMARY KEY, customer_id text, customer_phone text NOT NULL,
    sku text NOT NULL, qty integer NOT NULL, price_vnd bigint NOT NULL,
    total_vnd bigint NOT NULL, payment text NOT NULL, address text,
    promos jsonb NOT NULL DEFAULT '[]', created_on date NOT NULL,
    status text NOT NULL DEFAULT 'created'
);
CREATE INDEX IF NOT EXISTS tool_orders_phone_idx ON app_runtime.tool_orders(customer_phone);
CREATE TABLE IF NOT EXISTS app_runtime.tool_updates (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id text NOT NULL, action text NOT NULL, result jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS app_runtime.tool_callbacks (
    callback_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_phone text NOT NULL, callback_at timestamptz NOT NULL, note text
);
CREATE TABLE IF NOT EXISTS app_runtime.tool_handoffs (
    ticket_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, brief jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS app_runtime.promo_uses (
    customer_phone text NOT NULL, promo_code text NOT NULL,
    PRIMARY KEY(customer_phone, promo_code)
);
