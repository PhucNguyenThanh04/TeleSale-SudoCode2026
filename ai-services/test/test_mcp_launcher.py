"""The local launcher preserves one database role per MCP process."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pydantic import SecretStr

from app.mcp_servers.run import run_all


class MCPLauncherTest(unittest.TestCase):
    def test_starts_three_roles_and_stops_all_on_child_failure(self):
        settings = SimpleNamespace(
            database_url=SecretStr("postgresql+asyncpg://admin:hidden@127.0.0.1:5432/telesale"),
            mcp_host="127.0.0.1", mcp_catalog_port=8011,
            mcp_order_port=8012, mcp_memory_port=8013,
        )
        with tempfile.TemporaryDirectory() as directory:
            secrets = Path(directory)
            for name in ("mcp_internal_token", "mcp_catalog_password",
                         "mcp_order_password", "mcp_memory_password"):
                (secrets / name).write_text("test-only", encoding="utf-8")
            children = [Mock() for _ in range(3)]
            for child in children:
                child.poll.return_value = 1
            with patch("app.mcp_servers.run.get_settings", return_value=settings), \
                 patch("app.mcp_servers.run.subprocess.Popen", side_effect=children) as popen:
                with self.assertRaisesRegex(RuntimeError, "mcp-catalog exited"):
                    run_all(secrets_dir=secrets)

            self.assertEqual(popen.call_count, 3)
            for (name, port), call in zip((("catalog", 8011), ("order", 8012),
                                           ("memory", 8013)), popen.call_args_list):
                self.assertEqual(call.args[0][-1], f"app.mcp_servers.mcp_{name}.server")
                env = call.kwargs["env"]
                self.assertEqual(env["DATABASE_URL"], "")
                self.assertEqual(env["MCP_DB_USER"], f"mcp_{name}")
                self.assertEqual(env["MCP_DB_PASSWORD_FILE"],
                                 str(secrets / f"mcp_{name}_password"))
                self.assertEqual(env[f"MCP_{name.upper()}_PORT"], str(port))
