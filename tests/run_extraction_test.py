"""
Run the OpenAI label extractor over a random sample of the bottle photos and
report how it does on speed, coverage, and cost.

There is no ground-truth answer key for these photos, so this script does not
score correctness on its own. It runs the extraction, saves the exact image the
model saw next to its output, and writes everything to _eval/ so the results can
be reviewed by eye. Accuracy figures in the README come from that review.

Usage (from the project root):
    python tests/run_extraction_test.py
    python tests/run_extraction_test.py --count 30 --seed 42
"""
from __future__ import annotations
import argparse
import asyncio
import base64
import io
import json
import math
import random
import statistics
import sys
import time
import zipfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # so "app" is importable when run as a script

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.services.extractor import MODEL, extract_label_fields, _prepare_image

ZIP_PATH = ROOT / "Alc_Bottles_images.zip"
OUT_DIR = ROOT / "_eval"
PREVIEW_DIR = OUT_DIR / "previews"

FIELDS = [
    "brand_name",
    "class_type",
    "alcohol_content",
    "net_contents",
    "bottler_info",
    "country_of_origin",
    "government_warning",
]

# gpt-4o list prices (USD per 1M tokens). Only used for a rough cost estimate.
INPUT_PRICE = 2.50
OUTPUT_PRICE = 10.00

# Stop early if the estimated spend ever gets near this. A full 30-image run is
# only a couple of cents, so this is just a safety net.
MAX_SPEND_USD = 2.50


def estimate_cost(image: Image.Image, output_text: str) -> float:
    """Rough per-image cost for gpt-4o at 'high' detail."""
    tiles = math.ceil(image.width / 512) * math.ceil(image.height / 512)
    input_tokens = 85 + 170 * tiles + 300  # image tiles + prompt + user text
    output_tokens = max(1, len(output_text) // 4)
    return input_tokens / 1e6 * INPUT_PRICE + output_tokens / 1e6 * OUTPUT_PRICE


def pick_images(count: int, seed: int) -> list[str]:
    with zipfile.ZipFile(ZIP_PATH) as z:
        names = [n for n in z.namelist() if n.lower().endswith((".jpg", ".jpeg", ".png"))]
    rng = random.Random(seed)
    return rng.sample(names, min(count, len(names)))


async def run_one(name: str, raw: bytes) -> dict:
    source_b64 = base64.b64encode(raw).decode()

    # Save the exact (downscaled, re-oriented) image the model receives, so the
    # review looks at the same thing the model did.
    prepared = Image.open(io.BytesIO(base64.b64decode(_prepare_image(source_b64))))
    prepared.save(PREVIEW_DIR / name, "JPEG", quality=85)

    start = time.time()
    try:
        fields = await extract_label_fields(source_b64, "image/jpeg")
        error = None
    except Exception as exc:
        fields, error = {}, f"{type(exc).__name__}: {exc}"
    latency = round(time.time() - start, 2)

    cost = estimate_cost(prepared, json.dumps(fields)) if not error else 0.0
    return {"image": name, "latency_s": latency, "est_cost_usd": round(cost, 5),
            "error": error, "fields": fields}


async def main(count: int, seed: int) -> None:
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    names = pick_images(count, seed)
    print(f"Model: {MODEL}   Images: {len(names)}   Seed: {seed}\n")

    results: list[dict] = []
    spent = 0.0
    with zipfile.ZipFile(ZIP_PATH) as z:
        for i, name in enumerate(names, 1):
            result = await run_one(name, z.read(name))
            results.append(result)
            spent += result["est_cost_usd"]

            status = "ERROR" if result["error"] else "ok"
            print(f"[{i:2}/{len(names)}] {name}  {result['latency_s']:>5}s  {status}")
            if result["error"]:
                print(f"        {result['error']}")

            if spent > MAX_SPEND_USD:
                print(f"\nStopping early: estimated spend ${spent:.2f} hit the safety cap.")
                break

    write_outputs(results, seed)
    print_summary(results, spent)


def write_outputs(results: list[dict], seed: int) -> None:
    (OUT_DIR / "results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # A readable side-by-side of each preview image and what came back, so the
    # extractions can be checked by eye.
    lines = [f"# Extraction review (seed {seed})\n"]
    for r in results:
        lines.append(f"## {r['image']}  —  {r['latency_s']}s")
        lines.append(f"![label](previews/{r['image']})\n")
        if r["error"]:
            lines.append(f"**ERROR:** {r['error']}\n")
            continue
        for key in FIELDS:
            value = r["fields"].get(key)
            lines.append(f"- **{key}:** {value if value is not None else '_(none)_'}")
        lines.append("")
    (OUT_DIR / "review.md").write_text("\n".join(lines), encoding="utf-8")


def print_summary(results: list[dict], spent: float) -> None:
    ok = [r for r in results if not r["error"]]
    print("\n" + "=" * 60)
    print(f"Extracted {len(ok)}/{len(results)} images successfully")

    if ok:
        print("\nField coverage (how often a value was returned):")
        for key in FIELDS:
            filled = sum(1 for r in ok if r["fields"].get(key))
            print(f"  {key:<20} {filled:>2}/{len(ok)}  ({filled / len(ok):.0%})")

        warnings = [r["fields"].get("government_warning") or "" for r in ok]
        complete = sum(1 for w in warnings if "(1)" in w and "(2)" in w)
        print(f"\nGovernment warning with both (1) and (2) parts: "
              f"{complete}/{len(ok)} ({complete / len(ok):.0%})")

        latencies = [r["latency_s"] for r in ok]
        ordered = sorted(latencies)
        p95 = ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]
        under_5 = sum(1 for x in latencies if x <= 5.0)
        print("\nLatency (seconds):")
        print(f"  mean {statistics.mean(latencies):.2f}   median "
              f"{statistics.median(latencies):.2f}   p95 {p95:.2f}   max {max(latencies):.2f}")
        print(f"  within 5s target: {under_5}/{len(ok)} ({under_5 / len(ok):.0%})")

    print(f"\nEstimated cost: ${spent:.3f} total  (~${spent / max(1, len(results)):.4f}/image)")
    print(f"Outputs written to {OUT_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=30, help="number of images to sample")
    parser.add_argument("--seed", type=int, default=42, help="sampling seed for repeatability")
    args = parser.parse_args()
    asyncio.run(main(args.count, args.seed))
