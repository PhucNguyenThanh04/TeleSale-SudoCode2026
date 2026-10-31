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
GRANT USAGE ON SCHEMA btc_source TO mcp_catalog, mcp_order;
GRANT USAGE ON SCHEMA runtime TO mcp_catalog, mcp_order, mcp_memory;
GRANT SELECT ON btc_source.products, btc_source.variants, btc_source.promotions,
    btc_source.inventory_events, btc_source.customers, btc_source.crm_orders,
    btc_source.crm_sessions TO mcp_catalog, mcp_order;
GRANT SELECT ON btc_source.policy_chunks TO mcp_catalog;
GRANT SELECT ON runtime.tool_orders, runtime.promo_uses TO mcp_catalog;
GRANT SELECT, INSERT, UPDATE ON runtime.tool_orders, runtime.tool_updates,
    runtime.tool_callbacks, runtime.tool_handoffs, runtime.promo_uses,
    runtime.tool_operations TO mcp_order;
GRANT USAGE, SELECT ON SEQUENCE runtime.tool_order_seq,
    runtime.tool_updates_id_seq, runtime.tool_callbacks_callback_id_seq,
    runtime.tool_handoffs_ticket_id_seq TO mcp_order;
GRANT SELECT, INSERT, UPDATE, DELETE ON runtime.turns, runtime.episodes,
    runtime.facts, runtime.order_links, runtime.write_operations,
    runtime.pending_facts, runtime.erasure_requests,
    runtime.langmem_distillation_jobs TO mcp_memory;
GRANT USAGE, SELECT ON SEQUENCE runtime.langmem_distillation_jobs_job_id_seq TO mcp_memory;
DO \$\$ BEGIN
    IF to_regclass('runtime.store') IS NOT NULL THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON runtime.store,
            runtime.store_migrations TO mcp_memory;
    END IF;
END \$\$;
SQL
