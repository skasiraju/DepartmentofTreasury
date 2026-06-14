from __future__ import annotations
import time
from fastapi import APIRouter, HTTPException
from app.models import VerificationResponse, VerifyRequest
from app.services.extractor import extract_label_fields
from app.services.verifier import verify_label

router = APIRouter()


@router.post("/verify", response_model=VerificationResponse)
async def verify_label_endpoint(request: VerifyRequest) -> VerificationResponse:
    start_ms = int(time.time() * 1000)

    try:
        extracted = await extract_label_fields(request.image_base64, request.mime_type)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Label extraction failed: {exc}")

    return verify_label(extracted, request.application, start_ms)
