"""
Parse text from numbered JPG images in source/, with multi-column detection.
Outputs a single Markdown file in reading order.

Uses Tesseract's own block/paragraph/line structure for layout analysis
rather than a custom histogram, which handles multi-column pages reliably.
"""

import sys
from collections import defaultdict
from pathlib import Path

try:
    import pytesseract
    from pytesseract import Output
    from PIL import Image
except ImportError as e:
    print("Missing dependency:", e, file=sys.stderr)
    print("Install with: pip install pytesseract Pillow", file=sys.stderr)
    sys.exit(1)

SOURCE_DIR = Path("source")
OUTPUT_FILE = Path("output.md")


def get_sorted_image_paths():
    paths = list(SOURCE_DIR.glob("*.jpg"))
    if not paths:
        return []

    def sort_key(p):
        try:
            return int(p.name.split(" - ")[0])
        except (ValueError, IndexError):
            return 0

    return sorted(paths, key=sort_key)


def check_tesseract():
    try:
        pytesseract.get_tesseract_version()
    except pytesseract.TesseractNotFoundError:
        print(
            "Tesseract is not installed or not on PATH. "
            "Install it (e.g. brew install tesseract on macOS).",
            file=sys.stderr,
        )
        sys.exit(1)


def extract_page_text(image_path):
    """
    OCR one image. Uses Tesseract's block/par/line/word structure to preserve
    reading order across columns. Blocks are sorted by a reading heuristic
    (column-first: left-to-right within similar vertical bands, then top-to-bottom).
    """
    img = Image.open(image_path).convert("RGB")
    img_width, _ = img.size
    data = pytesseract.image_to_data(img, output_type=Output.DICT)
    n = len(data["text"])

    # Group words by (block_num, par_num, line_num)
    # and track block-level bounding boxes for sorting blocks.
    block_bbox = {}          # block_num -> (min_left, min_top, max_right, max_bottom)
    lines = defaultdict(list)  # (block_num, par_num, line_num) -> [(word_num, left, text)]

    for i in range(n):
        text = (data["text"][i] or "").strip()
        if not text:
            continue
        blk = data["block_num"][i]
        par = data["par_num"][i]
        ln  = data["line_num"][i]
        wn  = data["word_num"][i]
        left = data["left"][i]
        top  = data["top"][i]
        w    = data["width"][i]
        h    = data["height"][i]

        lines[(blk, par, ln)].append((wn, left, text))

        if blk not in block_bbox:
            block_bbox[blk] = [left, top, left + w, top + h]
        else:
            bb = block_bbox[blk]
            bb[0] = min(bb[0], left)
            bb[1] = min(bb[1], top)
            bb[2] = max(bb[2], left + w)
            bb[3] = max(bb[3], top + h)

    if not lines:
        return ""

    # Sort blocks into reading order.
    # Heuristic: assign each block to a "column" based on whether its
    # horizontal center is in the left, middle, or right third of the page,
    # then sort by (column_index, top).
    def block_sort_key(blk_num):
        bb = block_bbox[blk_num]
        x_center = (bb[0] + bb[2]) / 2
        y_top = bb[1]
        col = int(x_center / (img_width / 3))
        return (col, y_top)

    sorted_blocks = sorted(block_bbox.keys(), key=block_sort_key)

    # Build ordered text: iterate blocks in reading order,
    # then paragraphs and lines within each block in natural order.
    page_parts = []
    for blk in sorted_blocks:
        block_lines = {k: v for k, v in lines.items() if k[0] == blk}
        if not block_lines:
            continue
        for key in sorted(block_lines.keys()):
            words = block_lines[key]
            words.sort(key=lambda w: (w[0], w[1]))  # word_num then left
            line_text = " ".join(w[2] for w in words)
            page_parts.append(line_text)
        page_parts.append("")  # blank line between blocks

    return "\n".join(page_parts).strip()


def main():
    check_tesseract()
    paths = get_sorted_image_paths()
    if not paths:
        print("No JPG files found in", SOURCE_DIR, file=sys.stderr)
        sys.exit(1)

    parts = []
    for i, path in enumerate(paths, start=1):
        print(f"  Processing page {i}: {path.name} ...")
        page_md = extract_page_text(path)
        if parts:
            parts.append("\n\n---\n\n## Page {}\n\n".format(i))
        else:
            parts.append("## Page 1\n\n")
        parts.append(page_md)

    OUTPUT_FILE.write_text("".join(parts), encoding="utf-8")
    print("Wrote", OUTPUT_FILE, f"({len(paths)} pages)")


if __name__ == "__main__":
    main()
