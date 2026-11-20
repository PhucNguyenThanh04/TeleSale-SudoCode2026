from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.agent import PrepareSessionRequest, Channel


class TimelineRequest(PrepareSessionRequest):
    offset: int = Field(default=0, ge=0, strict=True)
    limit: int = Field(default=10, ge=1, le=20, strict=True)


class TimelineItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    session_id: str = Field(min_length=1)
    on: date
    channel: Channel
    summary: str = Field(max_length=800)
    outcome: Literal['hen_goi_lai', 'chot_don', 'tu_choi', 'chuyen_may', 'khac'] = 'khac'
    summary_status: Literal['ready', 'pending', 'unavailable'] = 'ready'


class TimelinePage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['available', 'not_applicable'] = 'available'
    items: list[TimelineItem] = Field(default_factory=list)
    offset: int = Field(default=0, ge=0, strict=True)
    limit: int = Field(default=10, ge=1, le=20, strict=True)
    total: int = Field(default=0, ge=0, strict=True)
    next_offset: int | None = Field(default=None, ge=0, strict=True)

    @model_validator(mode='after')
    def consistent_page(self):
        end = self.offset + len(self.items)
        expected_next = end if end < self.total else None
        if (len(self.items) > self.limit or self.items and end > self.total
                or self.next_offset != expected_next
                or self.next_offset is not None and not self.items
                or self.status == 'not_applicable' and (self.items or self.total)):
            raise ValueError('Inconsistent timeline page')
        return self


class TimelineResponse(BaseModel):
    session_id: str
    timeline: TimelinePage
