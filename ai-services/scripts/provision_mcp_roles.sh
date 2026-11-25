#!/bin/sh
set -eu

export PGPASSWORD="$(cat /run/secrets/postgres_password)"
catalog_password="$(cat /run/secrets/mcp_catalog_password)"
order_password="$(cat /run/secrets/mcp_order_password)"
memory_password="$(cat /run/secrets/mcp_memory_password)"
knowledge_password="$(cat /run/secrets/mcp_knowledge_password)"

for password in "$catalog_password" "$order_password" "$memory_password" "$knowledge_password"; do
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
SELECT 'CREATE ROLE mcp_knowledge LOGIN' WHERE NOT EXISTS
    (SELECT 1 FROM pg_roles WHERE rolname='mcp_knowledge') \gexec
ALTER ROLE mcp_knowledge LOGIN PASSWORD '$knowledge_password';
ALTER ROLE mcp_catalog PASSWORD '$catalog_password';
ALTER ROLE mcp_order PASSWORD '$order_password';
ALTER ROLE mcp_memory PASSWORD '$memory_password';

GRANT CONNECT ON DATABASE "$PGDATABASE" TO mcp_catalog, mcp_order, mcp_memory, mcp_knowledge;
SQL
psql -X -q -v ON_ERROR_STOP=1 -f /mcp_grants.sql
