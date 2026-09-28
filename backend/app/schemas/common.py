"""Shared backend boundary types. Dates in business requests are scenario dates."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

PhoneNumber = Annotated[str, StringConstraints(pattern=r"^0[0-9]{9}$")]
NonNegativeVND = Annotated[int, Field(ge=0)]
Channel = Literal["hotline", "chat_fanpage", "zalo_oa", "web_chat", "other"]
Outcome = Literal["hen_goi_lai", "chot_don", "tu_choi", "chuyen_may", "khac"]
PaymentMethod = Literal["COD", "bank", "momo", "zalopay"]


class ToolError(BaseModel):
    error: str
