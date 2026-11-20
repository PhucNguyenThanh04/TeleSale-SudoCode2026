import time
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

from app.agent.harness.context import load_context
from test_deep_memory import turn
from test_scoped_context import Tools


class BriefProductStateTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        blocker = patch('socket.socket.connect', side_effect=AssertionError('offline brief test'))
        blocker.start()
        self.addCleanup(blocker.stop)
