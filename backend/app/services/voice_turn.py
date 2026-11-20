import asyncio
from dataclasses import dataclass, field
from uuid import uuid4


@dataclass
class VoiceTurn:
    turn_id: str
    text: str
    client_msg_id: str = field(default_factory=lambda: str(uuid4()))
    interrupted: bool = False
    request_started: bool = False
    played_chars: int = 0
    marks: set[int] = field(default_factory=lambda: {0})
    playback: asyncio.Event = field(default_factory=asyncio.Event)
    interruption: asyncio.Event = field(default_factory=asyncio.Event)
    response: dict | None = None
