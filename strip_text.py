"""
Parse text from numbered JPG images in source/, with multi-column detection.
Outputs a single Markdown file in reading order.
"""

import glob
import sys
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
# Fraction of image width for histogram bins when detecting column gaps
BIN_FRACTION = 0.02
# Minimum gap width (as fraction of image width) to consider a column separator
MIN_GAP_FRACTION = 0.05
# Minimum fraction of image height a gap must span to count
MIN_GAP_HEIGHT_FRACTION = 0.3


def get_sorted_image_paths():
    """List source/*.jpg and return paths sorted by numeric prefix (N in 'N - id.jpg')."""
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
    """Ensure Tesseract is available; exit with clear message if not."""
    try:
        pytesseract.get_tesseract_version()
    except pytesseract.TesseractNotFoundError:
        print(
            "Tesseract is not installed or not on PATH. "
            "Install it (e.g. brew install tesseract on macOS).",
            file=sys.stderr,
        )
        sys.exit(1)


def get_word_boxes(image_path):
    """
    Run OCR and return list of (text, x_center, y_center, top, left, height).
    Only non-empty words with valid bboxes.
    """
    img = Image.open(image_path).convert("RGB")
    data = pytesseract.image_to_data(img, output_type=Output.DICT)
    words = []
    n = len(data["text"])
    for i in range(n):
        text = (data["text"][i] or "").strip()
        if not text:
            continue
        left = data["left"][i]
        top = data["top"][i]
        w = data["width"][i]
        h = data["height"][i]
        if w <= 0 or h <= 0:
            continue
        x_center = left + w / 2
        y_center = top + h / 2
        words.append((text, x_center, y_center, top, left, h))
    return words


def build_density_histogram(words, img_width, num_bins):
    """Build 1D histogram of text presence along x (count of word centers per bin)."""
    bins = [0.0] * num_bins
    bin_width = img_width / num_bins if num_bins else 1
    for _, x_center, _, _, _, _ in words:
        idx = min(int(x_center / bin_width), num_bins - 1)
        bins[idx] += 1
    return bins


def find_column_gaps(img_width, img_height, words):
    """
    Find vertical gaps that could separate columns.
    Returns sorted list of x positions (gap centers or boundaries).
    """
    if not words:
        return []
    num_bins = max(10, int(img_width * BIN_FRACTION))
    bins = build_density_histogram(words, img_width, num_bins)
    bin_width = img_width / num_bins
    min_gap_bins = max(1, int(MIN_GAP_FRACTION * img_width / bin_width))
    # Find runs of zero/low density (valleys)
    gap_starts = []
    i = 0
    while i < num_bins:
        if bins[i] <= 0:
            start = i
            while i < num_bins and bins[i] <= 0:
                i += 1
            if i - start >= min_gap_bins:
                gap_center_x = (start + (i - 1) / 2) * bin_width
                gap_starts.append(gap_center_x)
        else:
            i += 1
    return sorted(gap_starts)


def assign_columns(words, gap_x_positions):
    """
    Assign each word to a column index based on x_center and gap boundaries.
    gap_x_positions: sorted list of x values separating columns.
    Returns list of (column_index, top, left, text).
    """
    if not gap_x_positions:
        return [(0, top, left, text) for (text, _, _, top, left, _) in words]

    result = []
    for (text, x_center, _, top, left, _) in words:
        col = 0
        for gx in gap_x_positions:
            if x_center > gx:
                col += 1
            else:
                break
        result.append((col, top, left, text))
    return result


def ordered_lines_by_column(column_word_list):
    """
    Sort by (column_index, top, left) and group into lines (same column, similar top).
    Returns list of lines, each line is a list of words to join with space.
    """
    if not column_word_list:
        return []
    sorted_list = sorted(column_word_list, key=lambda x: (x[0], x[1], x[2]))
    lines = []
    current_line = []
    current_col = None
    current_top = None
    line_tolerance = 5  # pixels

    for col, top, left, text in sorted_list:
        if current_col is not None and (col != current_col or (current_top is not None and abs(top - current_top) > line_tolerance)):
            if current_line:
                lines.append(" ".join(current_line))
                current_line = []
        current_col = col
        current_top = top
        current_line.append(text)

    if current_line:
        lines.append(" ".join(current_line))
    return lines


def page_text_to_markdown(image_path):
    """
    OCR one image, detect columns, order text, return Markdown string for that page.
    """
    img = Image.open(image_path)
    img_width, img_height = img.size
    words = get_word_boxes(image_path)
    if not words:
        return ""
    gaps = find_column_gaps(img_width, img_height, words)
    column_word_list = assign_columns(words, gaps)
    lines = ordered_lines_by_column(column_word_list)
    return "\n\n".join(lines)


def main():
    check_tesseract()
    paths = get_sorted_image_paths()
    if not paths:
        print("No JPG files found in", SOURCE_DIR, file=sys.stderr)
        sys.exit(1)

    parts = []
    for i, path in enumerate(paths, start=1):
        page_md = page_text_to_markdown(path)
        if parts:
            parts.append("\n\n---\n\n## Page {}\n\n".format(i))
        else:
            parts.append("## Page 1\n\n")
        parts.append(page_md)

    OUTPUT_FILE.write_text("".join(parts), encoding="utf-8")
    print("Wrote", OUTPUT_FILE, "(", len(paths), "pages)")


if __name__ == "__main__":
    main()
