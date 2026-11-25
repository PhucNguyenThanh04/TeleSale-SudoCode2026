from pathlib import Path
import re

from app.system_start import pg_connect, quoted


async def provision(dsn, passwords):
    if set(passwords) != {'catalog', 'order', 'memory', 'knowledge'}:
        raise ValueError('All four MCP passwords are required')
    if any(not re.fullmatch('[0-9a-f]+', value) for value in passwords.values()):
        raise ValueError('MCP database passwords must be nonempty hex strings')
    connection = await pg_connect(dsn)
    try:
        async with connection.transaction():
            database = await connection.fetchval('SELECT current_database()')
            for name, password in passwords.items():
                role = 'mcp_' + name
                if not await connection.fetchval('SELECT 1 FROM pg_roles WHERE rolname=$1', role):
                    await connection.execute(f'CREATE ROLE {quoted(role)} LOGIN')
                statement = await connection.fetchval(
                    "SELECT format('ALTER ROLE %I LOGIN PASSWORD %L', $1::text, $2::text)", role, password)
                await connection.execute(statement)
                await connection.execute(f'GRANT CONNECT ON DATABASE {quoted(database)} TO {quoted(role)}')
            await connection.execute(Path(__file__).with_name('mcp_grants.sql').read_text())
    finally:
        await connection.close()
