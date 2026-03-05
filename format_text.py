"""
Read OCR markdown (output.md), fix spelling errors via Anthropic API,
then organise into proper paragraphs and formatting. Writes output_formatted.md.
"""

import os
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

INPUT_FILE = Path("output.md")
OUTPUT_FILE = Path("output_formatted.md")

MIN_PARAGRAPH_CHARS = 40
ALL_CAPS_HEADING_MAX_LENGTH = 60
MAX_MERGE_LINE_LENGTH = 15


# ---------------------------------------------------------------------------
# Anthropic API spelling correction
# ---------------------------------------------------------------------------

def get_anthropic_client():
    import anthropic
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("ANTHROPIC_API_KEY not set in .env", file=sys.stderr)
        sys.exit(1)
    return anthropic.Anthropic(api_key=key)


CLEANUP_PROMPT = """\
You are an OCR post-processor. The following text was extracted from a scanned \
magazine page via Tesseract OCR and contains many misspellings, garbled words, \
and artifacts.

Your job:
1. Fix obvious OCR misspellings (e.g. "yachl" → "yacht", "lave" → "love", \
"fuzure" → "figure", "wnotent" → "violent", "enard" → "guard").
2. Rejoin words that were hyphen-split across lines (e.g. "equip-\\nment" → \
"equipment"), but keep real hyphens (e.g. "well-stocked").
3. Fix misread characters (e.g. "@" that should be "a", "|" that should be "I").
4. Do NOT rewrite, rephrase, summarise, or add anything. Keep the author's \
original wording, sentence structure, and punctuation as close as possible.
5. Preserve paragraph breaks (blank lines) and the general structure.
6. If unsure about a word, leave it as-is rather than guessing wrong.

Return ONLY the corrected text, nothing else. No commentary, no preamble."""


def fix_spelling_with_api(client, page_text: str, page_num: int) -> str:
    """Send one page to Claude to fix OCR errors. Returns corrected text."""
    if not page_text.strip():
        return page_text
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=4096,
            messages=[
                {"role": "user", "content": f"{CLEANUP_PROMPT}\n\n---\n\n{page_text}"}
            ],
        )
        return resp.content[0].text.strip()
    except Exception as e:
        print(f"  Warning: API call failed for page {page_num}: {e}", file=sys.stderr)
        return page_text


# ---------------------------------------------------------------------------
# Page loading
# ---------------------------------------------------------------------------

def load_pages(path: Path) -> list[tuple[int, str]]:
    text = path.read_text(encoding="utf-8")
    pages = []
    pattern = re.compile(r"(?:^|\n)## Page (\d+)\s*\n+", re.IGNORECASE | re.MULTILINE)
    parts = pattern.split(text)
    if len(parts) == 1 and not pattern.search(text):
        if text.strip():
            pages.append((1, text.strip()))
        return pages
    i = 1
    while i < len(parts):
        try:
            page_num = int(parts[i])
        except ValueError:
            i += 1
            continue
        content = parts[i + 1].strip() if i + 1 < len(parts) else ""
        content = re.sub(r"\s*---\s*$", "", content)
        pages.append((page_num, content))
        i += 2
    return pages


# ---------------------------------------------------------------------------
# Local formatting helpers
# ---------------------------------------------------------------------------

def normalize_line(line: str) -> str:
    return " ".join(line.split()).strip()


def is_likely_heading(line: str) -> bool:
    if len(line) > ALL_CAPS_HEADING_MAX_LENGTH or len(line) < 2:
        return False
    letters = [c for c in line if c.isalpha()]
    if not letters:
        return False
    caps = sum(1 for c in letters if c.isupper())
    return caps >= 0.8 * len(letters)


def is_sentence_end(s: str) -> bool:
    s = s.rstrip()
    if not s:
        return False
    return s[-1] in ".!?)»\"'"


def merge_short_lines(lines: list[str]) -> list[str]:
    if not lines:
        return []
    result = []
    buffer = []
    for line in lines:
        line = normalize_line(line)
        if not line:
            if buffer:
                result.append(" ".join(buffer))
                buffer = []
            continue
        if len(line) <= MAX_MERGE_LINE_LENGTH and not is_sentence_end(line):
            buffer.append(line)
        else:
            if buffer:
                buffer.append(line)
                result.append(" ".join(buffer))
                buffer = []
            else:
                result.append(line)
    if buffer:
        result.append(" ".join(buffer))
    return result


def reflow_into_paragraphs(lines: list[str]) -> list[str]:
    if not lines:
        return []
    paragraphs = []
    current = []
    for line in lines:
        line = normalize_line(line)
        if not line:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        if current and is_sentence_end(current[-1]) and len(line) >= MIN_PARAGRAPH_CHARS:
            paragraphs.append(" ".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        paragraphs.append(" ".join(current))
    return paragraphs


def format_page_content(raw: str) -> str:
    lines = [normalize_line(ln) for ln in raw.splitlines() if normalize_line(ln)]
    lines = merge_short_lines(lines)
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if is_likely_heading(line):
            out.append("### " + line)
            out.append("")
            i += 1
            continue
        run = []
        while i < len(lines) and not is_likely_heading(lines[i]):
            run.append(lines[i])
            i += 1
        for para in reflow_into_paragraphs(run):
            if para:
                out.append(para)
                out.append("")
    return "\n".join(out).strip()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    input_path = INPUT_FILE
    output_path = OUTPUT_FILE
    if len(sys.argv) >= 2:
        input_path = Path(sys.argv[1])
    if len(sys.argv) >= 3:
        output_path = Path(sys.argv[2])
    if not input_path.exists():
        print("Input file not found:", input_path, file=sys.stderr)
        sys.exit(1)

    pages = load_pages(input_path)
    if not pages:
        print("No pages found in", input_path, file=sys.stderr)
        sys.exit(1)

    client = get_anthropic_client()

    parts = []
    for page_num, content in pages:
        print(f"  Fixing page {page_num} ({len(content)} chars) ...")
        fixed = fix_spelling_with_api(client, content, page_num)
        formatted = format_page_content(fixed)
        if parts:
            parts.append("\n\n---\n\n")
        parts.append(f"## Page {page_num}\n\n")
        parts.append(formatted)

    output_path.write_text("\n".join(parts), encoding="utf-8")
    print("Wrote", output_path, f"({len(pages)} pages)")


if __name__ == "__main__":
    main()
