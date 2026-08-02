#!/usr/bin/env python3
# Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. Licensed under Apache-2.0 (see LICENSE).
"""Add a solid-color border around JPG/JPEG images.

Scans a directory for *.jpg / *.jpeg images that have not yet been
processed (their name does not end with the border suffix) and writes a
new copy with a border added around the original image.
"""

import argparse
import os
import sys

try:
    from PIL import Image, ImageColor
except ImportError:
    sys.exit(
        "Error: Pillow is required. Install it with:\n"
        "    python -m pip install Pillow"
    )

# Suffix (before the extension) that marks an already-processed image.
SUFFIX = " - with border"

# Extensions we treat as JPEG images (compared case-insensitively).
JPEG_EXTS = (".jpg", ".jpeg")


def is_jpeg(filename):
    return os.path.splitext(filename)[1].lower() in JPEG_EXTS


def already_processed(filename):
    root, _ = os.path.splitext(filename)
    return root.endswith(SUFFIX)


def output_name(filename):
    root, ext = os.path.splitext(filename)
    return root + SUFFIX + ext


def add_border(src_path, dst_path, border_x, border_y, color):
    with Image.open(src_path) as img:
        img = img.convert("RGB")
        new_size = (img.width + 2 * border_x, img.height + 2 * border_y)
        bordered = Image.new("RGB", new_size, color)
        bordered.paste(img, (border_x, border_y))
        bordered.save(dst_path, quality=95)


def parse_color(value):
    """Parse a color name or #RRGGBB / R,G,B string into an RGB tuple."""
    value = value.strip()
    if "," in value:
        parts = [p.strip() for p in value.split(",")]
        if len(parts) != 3:
            raise argparse.ArgumentTypeError(
                "R,G,B color must have exactly three components"
            )
        try:
            rgb = tuple(int(p) for p in parts)
        except ValueError:
            raise argparse.ArgumentTypeError("R,G,B components must be integers")
        if any(c < 0 or c > 255 for c in rgb):
            raise argparse.ArgumentTypeError("R,G,B components must be 0-255")
        return rgb
    try:
        return ImageColor.getrgb(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"unknown color: {value!r}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Add a solid-color border to JPG/JPEG images."
    )
    parser.add_argument(
        "--path",
        default=".",
        help="Directory to scan for images (default: current directory).",
    )
    parser.add_argument(
        "--size",
        type=int,
        default=100,
        help="Border size in pixels for both X and Y (default: 100).",
    )
    parser.add_argument(
        "--size-x",
        type=int,
        default=None,
        help="Border size in pixels for the left/right edges (overrides --size).",
    )
    parser.add_argument(
        "--size-y",
        type=int,
        default=None,
        help="Border size in pixels for the top/bottom edges (overrides --size).",
    )
    parser.add_argument(
        "--color",
        type=parse_color,
        default="white",
        help='Border color: name (e.g. "white"), "#RRGGBB", or "R,G,B" (default: white).',
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Reprocess and overwrite existing '"
        + SUFFIX.strip()
        + "' outputs instead of skipping them.",
    )
    args = parser.parse_args(argv)

    # --color may still be a string if the default was used untouched.
    color = args.color if isinstance(args.color, tuple) else parse_color(args.color)

    border_x = args.size_x if args.size_x is not None else args.size
    border_y = args.size_y if args.size_y is not None else args.size
    if border_x < 0 or border_y < 0:
        parser.error("border sizes must be non-negative")

    path = args.path
    if not os.path.isdir(path):
        parser.error(f"path is not a directory: {path}")

    files = sorted(os.listdir(path))
    processed = skipped = failed = 0

    for filename in files:
        src_path = os.path.join(path, filename)
        if not os.path.isfile(src_path):
            continue
        if not is_jpeg(filename):
            continue
        if already_processed(filename):
            continue

        dst_path = os.path.join(path, output_name(filename))
        if os.path.exists(dst_path) and not args.overwrite:
            print(f"Skipping (already processed): {filename}")
            skipped += 1
            continue

        try:
            add_border(src_path, dst_path, border_x, border_y, color)
        except Exception as exc:  # noqa: BLE001 - report and keep going
            print(f"Failed: {filename}: {exc}")
            failed += 1
            continue

        print(f"Processed: {filename} -> {os.path.basename(dst_path)}")
        processed += 1

    print(
        f"\nDone. Processed: {processed}, skipped: {skipped}, failed: {failed} "
        f"(border x={border_x}px, y={border_y}px, color={color})."
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
