"""Start local MCP servers and the LangMem worker together."""

import os
import subprocess
import sys
import time
from pathlib import Path

from sqlalchemy.engine import make_url

from app.configs import get_settings


def run_all(*, secrets_dir: Path | None = None) -> None:
    """Run MCP services and LangMem with separate database roles until stopped."""
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("Set DATABASE_URL in ai-services/.env for the local MCP launcher")
    database = make_url(settings.database_url.get_secret_value())
    if not database.host or not database.database:
        raise RuntimeError("DATABASE_URL must include a host and database name")

    ai_root = Path(__file__).resolve().parents[2]
    secrets = secrets_dir or ai_root.parent / "secrets"
    token_file = secrets / "mcp_internal_token"
    roles = (
        ("catalog", settings.mcp_catalog_port),
        ("order", settings.mcp_order_port),
        ("memory", settings.mcp_memory_port),
    )
    if len({port for _, port in roles}) != len(roles):
        raise RuntimeError("MCP ports must be distinct")
    required = [token_file, *(secrets / f"mcp_{name}_password" for name, _ in roles)]
    missing = [path.name for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"Missing MCP secret files: {', '.join(missing)}")

    base_env = os.environ.copy()
    base_env.update({
        "DATABASE_URL": "",  # Each child must use its own role, not the admin DSN in .env.
        "MCP_DB_HOST": database.host,
        "MCP_DB_PORT": str(database.port or 5432),
        "MCP_DB_NAME": database.database,
        "MCP_INTERNAL_TOKEN_FILE": str(token_file),
        "MCP_HOST": settings.mcp_host,
        "LLM_API_KEY": "unused-for-mcp",
        "LLM_MODEL": "unused-for-mcp",
    })
    children: list[tuple[str, subprocess.Popen]] = []
    try:
        for name, port in roles:
            child_env = {**base_env,
                         "MCP_DB_USER": f"mcp_{name}",
                         "MCP_DB_PASSWORD_FILE": str(secrets / f"mcp_{name}_password"),
                         f"MCP_{name.upper()}_PORT": str(port)}
            child = subprocess.Popen(
                [sys.executable, "-m", f"app.mcp_servers.mcp_{name}.server"],
                cwd=ai_root, env=child_env, start_new_session=True,
            )
            children.append((name, child))
            print(f"Started mcp-{name} on {settings.mcp_host}:{port}", flush=True)
        worker_env = {**os.environ,
                      "DATABASE_URL": "",
                      "MCP_DB_HOST": database.host,
                      "MCP_DB_PORT": str(database.port or 5432),
                      "MCP_DB_NAME": database.database,
                      "MCP_DB_USER": "mcp_memory",
                      "MCP_DB_PASSWORD_FILE": str(secrets / "mcp_memory_password"),
                      "LANGMEM_MODE": "enabled"}
        worker = subprocess.Popen(
            [sys.executable, "-m", "app.mcp_servers.mcp_memory.distiller_worker"],
            cwd=ai_root, env=worker_env, start_new_session=True,
        )
        children.append(("langmem-worker", worker))
        print("Started langmem-worker", flush=True)
        while True:
            for name, child in children:
                code = child.poll()
                if code is not None:
                    raise RuntimeError(f"mcp-{name} exited with code {code}")
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        for _, child in children:
            if child.poll() is None:
                child.terminate()
        for _, child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    run_all()
