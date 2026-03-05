"""
Extract text from scanned magazine page images using a hybrid approach:
1. Tesseract OCR for accurate word-level text
2. Claude vision for layout understanding (titles, columns, pull quotes, captions)

Sends both the image and raw OCR text to Claude, which uses the image to
understand the visual structure and the OCR text as the word-accurate source.
"""

import base64
import os
import sys
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

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

EXTRACTION_PROMPT = """\
You are extracting text from a scanned magazine page. I am providing:
1. The actual page image so you can see the visual layout.
2. Raw OCR text from Tesseract, which has accurate words but wrong reading \
order and no structural understanding.

Your job is to combine both: use the IMAGE to understand the layout and \
structure, and use the OCR TEXT as the authoritative source for the actual \
words (since your vision may misread small print). Fix obvious OCR spelling \
errors using context.

Rules:
1. **Reading order**: Read columns left-to-right, top-to-bottom. If there \
are 3 columns, output the left column fully, then middle, then right. \
Within each column, go top-to-bottom.
2. **Title/subtitle**: If the page has a large title or subtitle at the top, \
put it first as a Markdown heading (# or ##). The subtitle should be in italics.
3. **Pull quotes**: Large decorative quotes displayed prominently on the page \
that REPEAT text already in the body—output these ONCE as a blockquote \
(> ...) placed after the paragraph they appear near. Do not duplicate the text.
4. **Photo captions**: Italic captions below photos—put at the end as: \
> *Caption: "text here"*
5. **Photo credits**: E.g. "PHOTOGRAPHY BY ..."—put at the end as: \
*Photo credit: ...*
6. **Interview format**: Format dialogue as:\
\n   **PLAYBOY:** Question text\
\n   **MAXWELL:** Answer text\
\n   Use bold for ALL speaker labels (PLAYBOY, MAXWELL, GUARD, OFFICER, \
EDITOR, etc.). Keep stage directions in [square brackets] as-is, in italics.
7. **Page numbers**: Omit entirely.
8. **Margin text**: Ignore "PLAYBOY" running vertically along the page margin.
9. **Hyphenation**: Rejoin words split across lines (e.g. "news-paper" → \
"newspaper"), but keep real hyphens (e.g. "well-stocked").
10. **Spelling**: Fix OCR errors (e.g. "wnotent"→"violent", "fuzure"→"figure", \
"lave"→"love") but preserve the author's original wording. Do not rephrase.
11. Output ONLY the Markdown text. No commentary, no preamble.

Here is the raw OCR text for reference:

---
{ocr_text}
---"""


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


def tesseract_extract(image_path: Path) -> str:
    """
    Run Tesseract with block-aware ordering: use block_num structure,
    sort blocks into columns (left third, middle, right), then emit
    lines in reading order. Returns raw text.
    """
    img = Image.open(image_path).convert("RGB")
    img_width, _ = img.size
    data = pytesseract.image_to_data(img, output_type=Output.DICT)
    n = len(data["text"])

    block_bbox = {}
    lines = defaultdict(list)

    for i in range(n):
        text = (data["text"][i] or "").strip()
        if not text:
            continue
        blk = data["block_num"][i]
        par = data["par_num"][i]
        ln = data["line_num"][i]
        wn = data["word_num"][i]
        left = data["left"][i]
        top = data["top"][i]
        w = data["width"][i]
        h = data["height"][i]

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

    def block_sort_key(blk_num):
        bb = block_bbox[blk_num]
        x_center = (bb[0] + bb[2]) / 2
        y_top = bb[1]
        col = int(x_center / (img_width / 3))
        return (col, y_top)

    sorted_blocks = sorted(block_bbox.keys(), key=block_sort_key)

    page_parts = []
    for blk in sorted_blocks:
        block_lines = {k: v for k, v in lines.items() if k[0] == blk}
        if not block_lines:
            continue
        for key in sorted(block_lines.keys()):
            words = block_lines[key]
            words.sort(key=lambda w: (w[0], w[1]))
            line_text = " ".join(w[2] for w in words)
            page_parts.append(line_text)
        page_parts.append("")

    return "\n".join(page_parts).strip()


def image_to_base64(path: Path) -> str:
    return base64.standard_b64encode(path.read_bytes()).decode("utf-8")


def extract_page(client, image_path: Path, ocr_text: str) -> str:
    b64 = image_to_base64(image_path)
    prompt = EXTRACTION_PROMPT.replace("{ocr_text}", ocr_text)
    resp = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=8192,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    )
    return resp.content[0].text.strip()


def main():
    import anthropic

    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("ANTHROPIC_API_KEY not set in .env", file=sys.stderr)
        sys.exit(1)

    check_tesseract()
    client = anthropic.Anthropic(api_key=key)

    paths = get_sorted_image_paths()
    if not paths:
        print("No JPG files found in", SOURCE_DIR, file=sys.stderr)
        sys.exit(1)

    parts = []
    for i, path in enumerate(paths, start=1):
        print(f"  [{i}/{len(paths)}] Tesseract OCR: {path.name} ...")
        ocr_text = tesseract_extract(path)
        print(f"  [{i}/{len(paths)}] Claude layout + cleanup ...")
        page_md = extract_page(client, path, ocr_text)
        if parts:
            parts.append("\n\n---\n\n")
        parts.append(f"## Page {i}\n\n")
        parts.append(page_md)

    OUTPUT_FILE.write_text("\n".join(parts), encoding="utf-8")
    print(f"\nWrote {OUTPUT_FILE} ({len(paths)} pages)")


if __name__ == "__main__":
    main()
