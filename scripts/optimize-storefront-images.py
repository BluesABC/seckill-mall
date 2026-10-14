#!/usr/bin/env python3
"""Build web-ready WebP files from the preserved, unmodified source artwork."""

from pathlib import Path
import argparse
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/web/assets-source"
PUBLIC = ROOT / "src/web/public/assets"
ACTIVE = (
    "sports-hero-v1",
    "shoe-run-v1",
    "shoe-court-v1",
    "shoe-street-v1",
)


def optimize(check: bool) -> int:
    failures = []
    for stem in ACTIVE:
        source = SOURCE / f"{stem}.png"
        output = PUBLIC / f"{stem}.webp"
        if not source.is_file():
            failures.append(f"missing source: {source.relative_to(ROOT)}")
            continue
        if check:
            if not output.is_file():
                failures.append(f"missing optimized image: {output.relative_to(ROOT)}")
                continue
            with Image.open(output) as image:
                if image.format != "WEBP" or image.width == 0 or image.height == 0:
                    failures.append(f"invalid WebP image: {output.relative_to(ROOT)}")
            continue
        with Image.open(source) as image:
            image.convert("RGB").save(output, "WEBP", quality=82, method=6)
        print(f"{source.name}: {source.stat().st_size} -> {output.stat().st_size} bytes")
    if failures:
        print("\n".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="verify generated WebP assets")
    raise SystemExit(optimize(parser.parse_args().check))
