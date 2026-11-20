
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter

from .common import Channel

NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Start(Command):
    event: Literal["start"]
    channel: Channel
    channel_identity: NonEmpty
    on: date


class PlaybackFinished(Command):
    event: Literal["playback_finished"]
    turn_id: NonEmpty
    played_chars: int = Field(default=0, ge=0)


class PlaybackProgress(Command):
    event: Literal["playback_progress", "playback_stopped"]
    turn_id: NonEmpty
    played_chars: int = Field(ge=0)


class End(Command):
    event: Literal["end"]


_commands = TypeAdapter(Annotated[Start | PlaybackFinished | PlaybackProgress | End, Field(discriminator="event")])


def parse_command(payload: object) -> Start | PlaybackFinished | PlaybackProgress | End:
    return _commands.validate_python(payload)
