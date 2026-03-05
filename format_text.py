"""
Optional post-processing for output.md: strip duplicate blank lines,
ensure consistent heading levels, and write output_formatted.md.

With the hybrid Tesseract+Claude pipeline in parse_text.py, the output
is already well-formatted, so this script is a light cleanup pass.
"""

import re
import sys
from pathlib import Path

INPUT_FILE = Path("output.md")
OUTPUT_FILE = Path("output_formatted.md")


def clean(text: str) -> str:
    # Collapse 3+ consecutive blank lines to 2
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    # Ensure --- page breaks have exactly one blank line on each side
    text = re.sub(r"\n*---\n*", "\n\n---\n\n", text)
    # Strip trailing whitespace on each line
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return text.strip() + "\n"


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

    text = input_path.read_text(encoding="utf-8")
    cleaned = clean(text)
    output_path.write_text(cleaned, encoding="utf-8")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
