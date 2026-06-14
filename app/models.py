from __future__ import annotations
from typing import Literal
from pydantic import BaseModel


class LabelApplication(BaseModel):
    brand_name: str
    class_type: str
    alcohol_content: str
    net_contents: str
    bottler_info: str
    country_of_origin: str = ""


class VerifyRequest(BaseModel):
    image_base64: str
    mime_type: str
    application: LabelApplication


class FieldResult(BaseModel):
    field: str
    label: str
    status: Literal["pass", "fail"]
    expected: str
    found: str | None
    note: str | None = None


class WarningResult(BaseModel):
    status: Literal["pass", "fail"]
    found: str | None
    note: str


class VerificationResponse(BaseModel):
    overall_status: Literal["pass", "fail"]
    fields: list[FieldResult]
    government_warning: WarningResult
    processing_time_ms: int
