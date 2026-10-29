#!/bin/sh
set -eu

export PGPASSWORD="$(cat /run/secrets/postgres_password)"
catalog_password="$(cat /run/secrets/mcp_catalog_password)"
order_password="$(cat /run/secrets/mcp_order_password)"
memory_password="$(cat /run/secrets/mcp_memory_password)"

# Passwords are generated as hex, which makes SQL interpolation unambiguous.
for password in "$catalog_password" "$order_password" "$memory_password"; do
    case "$password" in
        *[!0-9a-f]*|"") echo 'MCP database passwords must be nonempty hex strings' >&2; exit 1 ;;
    esac
done

psql -X -q -v ON_ERROR_STOP=1 <<SQL
SELECT 'CREATE ROLE mcp_catalog LOGIN' WHERE NOT EXISTS
    (SELECT 1 FROM pg_roles WHERE rolname='mcp_catalog') \gexec
SELECT 'CREATE ROLE mcp_order LOGIN' WHERE NOT EXISTS
    (SELECT 1 FROM pg_roles WHERE rolname='mcp_order') \gexec
SELECT 'CREATE ROLE mcp_memory LOGIN' WHERE NOT EXISTS
    (SELECT 1 FROM pg_roles WHERE rolname='mcp_memory') \gexec
ALTER ROLE mcp_catalog PASSWORD '$catalog_password';
ALTER ROLE mcp_order PASSWORD '$order_password';
ALTER ROLE mcp_memory PASSWORD '$memory_password';

GRANT CONNECT ON DATABASE "$PGDATABASE" TO mcp_catalog, mcp_order, mcp_memory;
GRANT USAGE ON SCHEMA btc_source, app_runtime TO mcp_catalog, mcp_order;
GRANT USAGE ON SCHEMA ai_memory TO mcp_memory;
GRANT USAGE ON SCHEMA langmem_store TO mcp_memory;
GRANT SELECT ON btc_source.products, btc_source.variants, btc_source.promotions,
    btc_source.inventory_events, btc_source.customers, btc_source.crm_orders,
    btc_source.crm_sessions TO mcp_catalog, mcp_order;
GRANT SELECT ON btc_source.policy_chunks TO mcp_catalog;
GRANT SELECT ON app_runtime.tool_orders, app_runtime.promo_uses TO mcp_catalog;
GRANT SELECT, INSERT, UPDATE ON app_runtime.tool_orders, app_runtime.tool_updates,
    app_runtime.tool_callbacks, app_runtime.tool_handoffs, app_runtime.promo_uses TO mcp_order;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA app_runtime TO mcp_order;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA ai_memory TO mcp_memory;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA langmem_store TO mcp_memory;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA ai_memory, langmem_store TO mcp_memory;
GRANT SELECT, INSERT, UPDATE ON app_runtime.tool_operations TO mcp_order;
SQL
