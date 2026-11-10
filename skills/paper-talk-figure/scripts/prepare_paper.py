"""Prepare a traceable PDF index and optional page renders; never rewrite the PDF."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

EXTRACTION_VERSION = 1


def parse_pages(value: str, page_count: int) -> list[int]:
    if not value.strip():
        return []
    pages = set()
    for part in value.split(","):
        endpoints = part.strip().split("-")
        if len(endpoints) == 1:
            first = last = int(endpoints[0])
        elif len(endpoints) == 2:
            first, last = map(int, endpoints)
        else:
            raise ValueError("Use page numbers/ranges such as 1,3-5.")
        if not 1 <= first <= last <= page_count:
            raise ValueError(f"Page range must be within 1..{page_count}.")
        pages.update(range(first, last + 1))
    return sorted(pages)


def prepare(source: Path, output: Path, render_pages: str = "", scale: float = 1.5) -> dict:
    import pymupdf

    source = source.resolve(strict=True)
    output = output.resolve()
    if not math.isfinite(scale) or not 0.25 <= scale <= 4:
        raise ValueError("Render scale must be finite and within 0.25..4.")
    source_bytes = source.read_bytes()
    with pymupdf.open(stream=source_bytes, filetype="pdf") as pdf:
        if pdf.needs_pass:
            raise ValueError("Encrypted PDF: supply an unlocked copy.")
        requested = parse_pages(render_pages, len(pdf))
        targets = [output / "paper-source.json", output / "paper-source.txt"]
        targets += [output / "source-pages" / f"page-{n:03d}.png" for n in requested]
        if any(path.exists() for path in targets):
            raise FileExistsError("Extraction output already exists; use a new output directory.")

        result = {
            "extraction_version": EXTRACTION_VERSION,
            "source_path": str(source),
            "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "page_count": len(pdf),
            "reading_order": "raw PDF extraction order; inspect page geometry before interpreting",
            "formula_recognition": "not performed",
            "pages": [],
        }
        text_parts = ["PDF source index. Block order is NOT a verified reading order.\n"]
        for number, page in enumerate(pdf, start=1):
            bounds = page.rect
            blocks = []
            page_warnings = []
            for item in page.get_text("blocks", sort=False):
                if item[6] != 0 or not item[4].strip():
                    continue
                source_rect = pymupdf.Rect(item[:4])
                display_rect = source_rect * page.rotation_matrix
                bbox = list(display_rect)
                normalized = [bbox[0] / bounds.width, bbox[1] / bounds.height,
                              bbox[2] / bounds.width, bbox[3] / bounds.height]
                if any(v < -0.001 or v > 1.001 for v in normalized):
                    page_warnings.append("Text extends outside displayed page; preserved without clipping.")
                block_id = f"p{number}-b{len(blocks) + 1}"
                blocks.append({"id": block_id, "text": item[4],
                               "bbox_unrotated": list(source_rect),
                               "bbox_display": bbox,
                               "bbox_display_normalized": normalized})
                text_parts.append(f"\n[{block_id}] PDF page {number}\n{item[4]}")
            if not blocks:
                page_warnings.append("No extractable text: inspect page image; OCR may be required.")
                text_parts.append(f"\n[PDF page {number}] NO EXTRACTABLE TEXT\n")
            result["pages"].append({"number": number, "rotation": page.rotation,
                                    "width": bounds.width, "height": bounds.height,
                                    "blocks": blocks,
                                    "warnings": sorted(set(page_warnings))})

        output.mkdir(parents=True, exist_ok=True)
        # Exclusive creation protects previous work even if another run starts concurrently.
        with (output / "paper-source.json").open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        with (output / "paper-source.txt").open("x", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(text_parts))
        if requested:
            (output / "source-pages").mkdir(exist_ok=True)
            for number in requested:
                pdf[number - 1].get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).save(
                    str(output / "source-pages" / f"page-{number:03d}.png"))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--render-pages", default="", help="1-based physical pages, e.g. 1,3-5")
    parser.add_argument("--scale", type=float, default=1.5)
    args = parser.parse_args()
    try:
        result = prepare(args.source, args.out, args.render_pages, args.scale)
    except (OSError, ValueError, RuntimeError, ImportError) as exc:
        parser.exit(1, f"PDF preparation failed: {exc}\n")
    warning_pages = sum(bool(page["warnings"]) for page in result["pages"])
    print(json.dumps({"pages": result["page_count"],
                      "blocks": sum(len(page["blocks"]) for page in result["pages"]),
                      "pages_with_warnings": warning_pages,
                      "output": str(args.out.resolve())}, ensure_ascii=False))


if __name__ == "__main__":
    main()
