"""Reset mutable runtime data before a controlled evaluation run."""

import asyncpg


async def reset_runtime_database(
    dsn: str, *, expected_database: str | None = None,
    expected_server_started_at: str | None = None,
    expected_server_host: str | None = None, expected_server_port: int | None = None, app_env: str
) -> None:
    if app_env == "production":
        raise ValueError("Runtime reset is unavailable in production")
    if not expected_database:
        raise ValueError("Expected database identity is required")
    normalized_dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    connection = await asyncpg.connect(normalized_dsn)
    try:
        async with connection.transaction():
            database = await connection.fetchval("SELECT current_database()")
            if database != expected_database:
                raise ValueError("Runtime reset database identity does not match the MCP database")
            if expected_server_host is not None:
                endpoint = await connection.fetchrow(
                    "SELECT inet_server_addr()::text AS host, inet_server_port() AS port")
                if endpoint["host"] != expected_server_host or endpoint["port"] != expected_server_port:
                    raise ValueError("Runtime reset endpoint does not match MCP services")
            if expected_server_started_at is not None:
                actual_started_at = await connection.fetchval(
                    "SELECT pg_postmaster_start_time()")
                if actual_started_at.isoformat() != expected_server_started_at:
                    raise ValueError("Runtime reset server identity does not match MCP services")
            await connection.execute("SET LOCAL lock_timeout = '5s'")
            tables = [row["tablename"] for row in await connection.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'runtime' ORDER BY tablename"
            )]
            if "store_migrations" not in tables or len(tables) < 2:
                raise ValueError("Runtime schema is incomplete")
            mutable = [name for name in tables if name not in {"store_migrations", "demo_users"}]
            qualified = []
            for name in mutable:
                safe_name = name.replace('"', '""')
                qualified.append(f'runtime."{safe_name}"')
            await connection.execute('LOCK TABLE ' + ', '.join(qualified) + ' IN ACCESS EXCLUSIVE MODE')
            worker_sequence = None
            if 'langmem_distillation_jobs' in mutable:
                worker_sequence = await connection.fetchrow(
                    'SELECT last_value,is_called FROM runtime.langmem_distillation_jobs_job_id_seq')
            await connection.execute("TRUNCATE TABLE " + ", ".join(qualified) + " RESTART IDENTITY")
            # An old worker claim must never match a job created after reset.
            if worker_sequence:
                await connection.execute(
                    "SELECT setval('runtime.langmem_distillation_jobs_job_id_seq', $1, $2)",
                    worker_sequence['last_value'], worker_sequence['is_called'])
            if await connection.fetchval("SELECT to_regclass('runtime.tool_order_seq')"):
                await connection.execute("ALTER SEQUENCE runtime.tool_order_seq RESTART WITH 600001")
    finally:
        await connection.close()


async def probe_runner_database(dsn: str) -> dict:
    """Read the actual reset connection identity before warm-up/model calls."""
    connection = await asyncpg.connect(dsn.replace("postgresql+asyncpg://", "postgresql://", 1))
    try:
        row = await connection.fetchrow("SELECT current_database() AS database, "
            "inet_server_addr()::text AS host, inet_server_port() AS port, "
            "pg_postmaster_start_time() AS server_started_at")
        return {"database":row["database"],"host":row["host"],"port":row["port"],
                "server_started_at":row["server_started_at"].isoformat()}
    finally:
        await connection.close()
