from __future__ import annotations
import base64
import io
import json
import os
from openai import AsyncOpenAI
from PIL import Image, ImageOps

# Vision model that reads the label. Override with OPENAI_MODEL if needed.
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

# Phone photos are often 12 MP. We don't need that to read a label, and a
# smaller image is faster and cheaper to send, so we cap the longest side.
MAX_IMAGE_SIDE = 1280

SUPPORTED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}

# Reads OPENAI_API_KEY from the environment (loaded from .env in main.py).
client = AsyncOpenAI()

_PROMPT = """You are reading a U.S. alcohol beverage label for a TTB compliance check.

Copy each field exactly as it is printed on the label — keep the original
spelling, capitalization, and punctuation. Transcribe only what you can actually
see. If a field is not on the label, or you cannot read it clearly, return null.
Never guess a value and never copy the descriptions below.

Return a JSON object with exactly these keys:
  brand_name          the brand the product is sold under
  class_type          the class or type designation (what kind of beverage it is)
  alcohol_content     the alcohol statement (percent alcohol by volume and/or proof)
  net_contents        the net contents (the volume)
  bottler_info        the bottler / producer name and address
  country_of_origin   the country of origin, if shown (usually only on imports)
  government_warning  the full government warning paragraph, word for word

For the warning, include the "GOVERNMENT WARNING:" heading when it is present and
copy the whole statement. If you cannot actually read the warning, return null
rather than filling in the standard text from memory."""


def _prepare_image(image_base64: str) -> str:
    """Fix orientation, shrink, and re-encode the image as a JPEG data payload."""
    raw = base64.b64decode(image_base64)
    image = Image.open(io.BytesIO(raw))
    image = ImageOps.exif_transpose(image)  # honor the camera's rotation tag
    image = image.convert("RGB")
    image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return base64.b64encode(buffer.getvalue()).decode()


async def extract_label_fields(image_base64: str, mime_type: str) -> dict[str, str | None]:
    if mime_type not in SUPPORTED_MIME_TYPES:
        raise ValueError(f"Unsupported image type: {mime_type}. Use JPEG, PNG, or WebP.")

    data_url = f"data:image/jpeg;base64,{_prepare_image(image_base64)}"

    response = await client.chat.completions.create(
        model=MODEL,
        temperature=0,
        max_tokens=700,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Extract the label fields from this image."},
                    {"type": "image_url", "image_url": {"url": data_url, "detail": "high"}},
                ],
            },
        ],
    )

    return json.loads(response.choices[0].message.content)
