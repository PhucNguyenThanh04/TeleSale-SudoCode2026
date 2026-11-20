
import unittest
from unittest.mock import AsyncMock
from uuid import uuid4

from app.mcp_servers.mcp_memory.services.memory import read, write
from app.configs import Settings
from test_mcp_memory import TurnRepo


class LangMemOnlyContract(unittest.IsolatedAsyncioTestCase):
    def test_runtime_has_no_memory_mode_selector(self):
        settings = Settings()
        self.assertFalse(hasattr(settings, "langmem_mode"))
        self.assertFalse(hasattr(settings, "fact_extraction_mode"))

    async def test_legacy_fact_action_is_unavailable_without_mode_selection(self):
        result = await write(None, "fact", "C1", str(uuid4()),
                             {"key": "preferred_color", "value": "xanh",
                              "op": "set", "source": "customer"})
        self.assertEqual(result, {"error": "unknown_memory_action"})

    async def test_default_read_uses_langmem_store(self):
        class Repo(TurnRepo):
            async def facts(self, *_):
                raise AssertionError("legacy fact table was read")

            async def order_links(self, *_):
                return []

        projector = AsyncMock()
        projector.list_fact_versions.return_value = []
        projector.list_episode_versions.return_value = []
        result = await read(Repo(), "C1", str(uuid4()), projector=projector)
        self.assertEqual(result["profile"], {})
        projector.list_fact_versions.assert_awaited_once_with("C1")
