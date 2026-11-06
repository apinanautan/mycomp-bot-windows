"""Prepare the application PNG and multi-resolution Windows ICO from an approved image."""
from __future__ import annotations

import argparse
from pathlib import Path
from PIL import Image, ImageDraw


def prepare(source: Path, output_dir: Path) -> None:
    original = Image.open(source).convert("RGB")
    if original.width != original.height or original.width < 128:
        raise ValueError("Icon source must be square and at least 128 pixels")
    # Remove only the contiguous near-white exterior, leaving white robot
    # details untouched because they are separated by the orange background.
    flooded = original.copy()
    marker = (1, 2, 3)
    for corner in ((0, 0), (original.width - 1, 0), (0, original.height - 1), (original.width - 1, original.height - 1)):
        if all(component >= 225 for component in original.getpixel(corner)):
            ImageDraw.floodfill(flooded, corner, marker, thresh=42)
    image = original.convert("RGBA")
    pixels = image.load()
    mask = flooded.load()
    for y in range(image.height):
        for x in range(image.width):
            if mask[x, y] == marker:
                pixels[x, y] = (0, 0, 0, 0)
    output_dir.mkdir(parents=True, exist_ok=True)
    image.save(output_dir / "mycomp-bot.png")
    image.save(output_dir / "mycomp-bot.ico", format="ICO", sizes=[
        (16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
        (128, 128), (256, 256),
    ])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    prepare(args.source, args.destination)
