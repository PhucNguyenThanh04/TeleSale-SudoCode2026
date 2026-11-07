"""Commands for the public voice demo; no customer resolution here."""

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


class End(Command):
    event: Literal["end"]


_commands = TypeAdapter(Annotated[Start | PlaybackFinished | End, Field(discriminator="event")])


def parse_command(payload: object) -> Start | PlaybackFinished | End:
    return _commands.validate_python(payload)
