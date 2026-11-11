"""Reconstruct complete numbered bibliography entries before translating them."""
import copy
from collections import Counter
import html
import re
import statistics
import unicodedata

import pymupdf
from pdf_typography import space_cjk_latin
from pdf_flow import visible_drawings

SCHEMA = 1
HEADING = re.compile(r"REFERENCES|BIBLIOGRAPHY|参考文献", re.I)
REFERENCE_MARK = re.compile(
    r"(?m)^\s*(?:\[\s*\d{1,4}\s*\]|\(?\s*\d{1,4}\s*\)?[.)])\s+")


def clean_text(value):
    value = re.sub(r"(?<=\w)-\s*\n\s*(?=[a-z])", "", value)
    for accent, combining in (("¨", "\u0308"), ("´", "\u0301"), ("`", "\u0300")):
        value = re.sub(re.escape(accent) + r"([A-Za-z])", lambda m: unicodedata.normalize("NFC", m[1] + combining), value)
    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(r"(https?://\S+/)\s+(?=[A-Za-z0-9])", r"\1", value)
    return re.sub(r"(?<=\d)([–-])\s+(?=\d)", r"\1", value)


def split_reference(text):
    match = re.search(r'[“"]([^”"]+)[”"]', text)
    if not match:
        return None
    prefix, suffix = text[:match.start(1)], text[match.end(1):]
    number = re.match(r"\s*\[(\d+)\]", text)
    authors = re.sub(r'^\s*\[\d+\]\s*', '', prefix).rstrip(' ,“"')
    return {"prefix": prefix, "title": match[1].rstrip(" ,;"), "suffix": suffix,
            "authors": authors, "publication": suffix.lstrip('”" ,'), "number": int(number[1]) if number else None}


def translation_source(block):
    reference = block.get("reference")
    return reference["title"] if reference else block["text"]


_URL_TEXT = re.compile(r"https?://[^\s<>\"'，。；：！？）】」』《【〕]+")
_URL_TRAILING = ".,;:!?)]}'\"。、；，！？）：」』）"


def _url_ranges(content):
    """Literal http(s) URLs in an entry, as (start, end, uri, ordinal) ranges."""
    ranges = []
    for match in _URL_TEXT.finditer(content):
        value = match[0].rstrip(_URL_TRAILING)
        if len(value) < 9:
            continue
        start = match.start()
        ordinal, position = 0, content.find(value)
        while 0 <= position < start:
            ordinal += 1
            position = content.find(value, position + 1)
        ranges.append((start, start + len(value), value, ordinal))
    return ranges


def _entry_inner(content, regions, ranges):
    """Escape entry text once, layering meta/title spans and link anchors."""
    cuts = {0, len(content)}
    for start, end, _, _ in ranges:
        cuts.update((start, end))
    # Region boundaries are cuts too: without them the whole entry is one
    # piece and the title never receives its own font/size.
    for begin, finish, _ in regions:
        cuts.update((max(0, begin), min(len(content), finish)))
    ordered = sorted(cuts)
    pieces = []
    for start, end in zip(ordered, ordered[1:]):
        if end <= start:
            continue
        piece = html.escape(content[start:end])
        region = next((name for begin, finish, name in regions if begin <= start and end <= finish), None)
        if region:
            piece = f'<span class="{region}">{piece}</span>'
        link = next((item for item in ranges if item[0] <= start and end <= item[1]), None)
        if link:
            piece = f'<a href="{html.escape(link[2], quote=True)}">{piece}</a>'
        pieces.append(piece)
    return "".join(pieces)


def _reference_style_key(value):
    return "".join(unicodedata.normalize("NFKC", value).split())


def _source_reference_styles(rows):
    """Normalize source characters and carry their exact bold/italic flags.

    This mirrors clean_text's dehyphenation and accent repair. Mapping is only
    accepted when the resulting entire entry equals the canonical source; no
    fuzzy matching of repeated names, short words or years is used.
    """
    chars, styles = [], []
    for row in rows:
        for fragment in sorted(row["fragments"], key=lambda item: item["rect"].x0):
            for span in fragment.get("spans", ()):
                face = span.get("font", "")
                style = (bool(span.get("flags", 0) & 16) or bool(re.search(r"bold|semibold", face, re.I)),
                         bool(span.get("flags", 0) & 2) or bool(re.search(r"italic|oblique|ital$", face, re.I)))
                chars.extend(span["text"])
                styles.extend([style] * len(span["text"]))
        chars.append("\n")
        styles.append((False, False))
    text = "".join(chars)
    remove = set()
    for match in re.finditer(r"(?<=\w)-\s*\n\s*(?=[a-z])", text):
        remove.update(range(match.start(), match.end()))
    cleaned, carried = [], []
    index = 0
    accents = {"¨": "\u0308", "´": "\u0301", "`": "\u0300"}
    while index < len(chars):
        if index in remove or chars[index].isspace():
            index += 1
            continue
        char, style = chars[index], styles[index]
        if char in accents and index + 1 < len(chars) and re.fullmatch(r"[A-Za-z]", chars[index + 1]):
            char = unicodedata.normalize("NFC", chars[index + 1] + accents[char])
            style = styles[index + 1]
            index += 1
        normalized = unicodedata.normalize("NFKC", char)
        cleaned.extend(normalized)
        carried.extend([style] * len(normalized))
        index += 1
    return "".join(cleaned), carried


def _styled_metadata_regions(display, regions, reference, source, rows):
    """Apply source emphasis only to unchanged authors/publication metadata."""
    source_key, source_styles = _source_reference_styles(rows)
    if source_key != _reference_style_key(source):
        return regions, False
    names = [None] * len(display)
    for start, end, name in regions:
        names[start:end] = [name] * (end - start)
    for field in ("authors", "publication"):
        value = reference.get(field, "")
        key = _reference_style_key(value)
        if not key:
            continue
        # The source parser already establishes author/publication boundaries;
        # require an exact full-field match, not a guess based on font names.
        source_start = source_key.find(key) if field == "authors" else source_key.rfind(key)
        output_start = display.find(value) if field == "authors" else display.rfind(value)
        if source_start < 0 or output_start < 0:
            return regions, False
        offset = source_start
        for index, char in enumerate(value):
            if char.isspace():
                continue
            normalized = unicodedata.normalize("NFKC", char)
            flags = source_styles[offset:offset + len(normalized)]
            if len(flags) != len(normalized):
                return regions, False
            # Compatibility ligatures share a style. A mixed style inside one
            # output codepoint is ambiguous and must not change the whole run.
            if len(set(flags)) != 1:
                return regions, False
            bold, italic = flags[0]
            names[output_start + index] = "meta" + (" source-bold" if bold else "") + (" source-italic" if italic else "")
            offset += len(normalized)
    # Retain emphasis on internal spaces too, so letter/word spacing uses the
    # same face as the surrounding words of an italic venue or bold volume.
    for index, char in enumerate(display):
        if char.isspace() and names[index] == "meta" and index > 0:
            right = next((names[j] for j in range(index + 1, len(display)) if not display[j].isspace()), None)
            if names[index - 1] == right:
                names[index] = right
    result = []
    for index, name in enumerate(names):
        if name is None:
            continue
        if result and result[-1][1] == index and result[-1][2] == name:
            result[-1] = (result[-1][0], index + 1, name)
        else:
            result.append((index, index + 1, name))
    return result, True


def _normalized_entry_rows(block, native):
    """Source rows for a normalized entry, including a column continuation."""
    result = []
    seen = set()
    for part in block.get("source_parts", ()):
        box = pymupdf.Rect(part["rect"])
        fragments = []
        for item in native:
            for line in item.get("lines", ()):
                rect = pymupdf.Rect(line["bbox"])
                if id(line) not in seen and box.contains((rect.tl + rect.br) * .5):
                    seen.add(id(line))
                    fragments.append({"rect": rect, "spans": line["spans"]})
        if fragments:
            result.append({"fragments": fragments})
    return result


def format_translation(block, title):
    reference = block.get("reference")
    if not reference:
        return title.strip()
    title = title.strip().strip('“”"')
    if (not title or "\n" in title or re.search(r"\[\d+\]", title)
            or reference["authors"] in title or reference["publication"] in title
            or len(title) > max(240, len(reference["title"]) * 5)):
        raise ValueError("参考文献仅接受本条论文标题的译文，不接受相邻条目或作者出版信息")
    separator = "。" if re.search(r"[\u3400-\u9fff]", title) else ". "
    return f"[{reference['number']}] {reference['authors']}. {title.rstrip('。. ')}{separator}{reference['publication']}"


def _visual_lines(page, native=None):
    if native is None:
        native = page.get_text("dict", flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES)["blocks"]
    lines = []
    for block in native:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            text = "".join(s["text"] for s in line["spans"]).strip()
            if text:
                lines.append({"text": text, "rect": pymupdf.Rect(line["bbox"]),
                              "spans": line["spans"]})
    return lines


def _rows(lines):
    rows = []
    for line in sorted(lines, key=lambda item: (item["rect"].y0, item["rect"].x0)):
        match = next((row for row in reversed(rows[-3:]) if abs(row["rect"].y0 - line["rect"].y0) < 1.6), None)
        if match:
            match["fragments"].append(line)
            match["rect"] |= line["rect"]
        else:
            rows.append({"rect": pymupdf.Rect(line["rect"]), "fragments": [line]})
    for row in rows:
        row["text"] = " ".join(fragment["text"] for fragment in sorted(row["fragments"], key=lambda item: item["rect"].x0))
    return rows


def discover(pdf):
    """Fail closed for multi-page bibliographies; never merge half an entry."""
    for page_index, page in enumerate(pdf):
        lines = _visual_lines(page)
        heading = next((line for line in lines if HEADING.fullmatch(line["text"].strip())), None)
        if heading is None:
            continue
        bounds = page.rect * page.derotation_matrix
        mid = bounds.width / 2
        double = (any(line["rect"].width > bounds.width * .2 and line["rect"].x1 <= mid + 6 for line in lines)
                  and any(line["rect"].width > bounds.width * .2 and line["rect"].x0 >= mid - 6 for line in lines))
        if double:
            start_column = int((heading["rect"].x0 + heading["rect"].x1) / 2 >= mid)
            columns = [[line for line in lines if int((line["rect"].x0 + line["rect"].x1) / 2 >= mid) == column]
                       for column in range(start_column, 2)]
        else:
            columns = [lines]
        entries, regions, current = [], [], None
        for column_index, column in enumerate(columns):
            selected = [line for line in column if (column_index > 0 or line["rect"].y0 >= heading["rect"].y1 - .5)]
            selected = [line for line in selected if not re.fullmatch(r"\d+", line["text"]) or line["rect"].y0 < bounds.height - 30]
            rows = _rows(selected)
            if not rows:
                continue
            region = pymupdf.Rect(rows[0]["rect"])
            for row in rows:
                region |= row["rect"]
                marker = re.match(r"^\s*\[(\d{1,4})\]\s*(.*)", row["text"])
                if marker:
                    current = {"number": int(marker[1]), "rows": [], "parts": []}
                    entries.append(current)
                if current is None:
                    return None
                current["rows"].append(row["text"])
                part = {"page": page_index + 1, "column": column_index, "rect": list(row["rect"])}
                current["parts"].append(part)
            regions.append({"column": column_index, "rect": list(region)})
        if len(entries) < 2 or [entry["number"] for entry in entries] != list(range(1, len(entries) + 1)):
            return None
        # A missing closing title/terminal year usually means a continuation on
        # the next page. Preserve that section instead of silently truncating it.
        if page_index != len(pdf) - 1:
            return None
        for entry in entries:
            entry["text"] = clean_text("\n".join(entry.pop("rows")))
            entry["reference"] = split_reference(entry["text"])
            if entry["reference"] is None:
                return None
        return {"page": page_index + 1, "heading_rect": list(heading["rect"]), "regions": regions, "entries": entries}
    return None


def fallback_reference_regions(page):
    """Column areas of a bibliography that cannot be rebuilt into full entries.

    A multi-page bibliography, an unquoted book title or a non-contiguous
    numbering makes `discover` fail closed. Translating those line fragments
    one by one mixes languages inside one entry and lets expanded translations
    overlap the lines that had to stay original. Return the columns below the
    reference heading instead, so the caller can keep that whole region intact.
    """
    if page.rotation:
        return []
    lines = _visual_lines(page)
    heading = next((line for line in lines if HEADING.fullmatch(line["text"].strip())), None)
    if heading is None:
        return []
    bounds = page.rect * page.derotation_matrix
    mid = bounds.width / 2
    double = (any(line["rect"].width > bounds.width * .2 and line["rect"].x1 <= mid + 6 for line in lines)
              and any(line["rect"].width > bounds.width * .2 and line["rect"].x0 >= mid - 6 for line in lines))
    if not double:
        return [pymupdf.Rect(bounds.x0, heading["rect"].y1, bounds.x1, bounds.y1)]
    start_column = int((heading["rect"].x0 + heading["rect"].x1) / 2 >= mid)
    regions = []
    for column in range(start_column, 2):
        x0 = bounds.x0 if column == 0 else mid
        x1 = mid if column == 0 else bounds.x1
        y0 = heading["rect"].y1 if column == start_column else bounds.y0
        regions.append(pymupdf.Rect(x0, y0, x1, bounds.y1))
    return regions


def reference_fallback_pages(pdf):
    """Map page indexes to the column areas of a non-rebuildable bibliography.

    A bibliography can start on one page and run over several pages; only the
    first page carries the heading. Once that heading is found, following pages
    with several numbered entries in the reference columns are part of the same
    unrebuildable section. Returning every affected page keeps the fallback
    consistent instead of protecting only the heading page.
    """
    pages = list(pdf)
    result = {}
    for index, page in enumerate(pages):
        if page.rotation:
            continue
        lines = _visual_lines(page)
        heading = next((line for line in lines if HEADING.fullmatch(line["text"].strip())), None)
        if heading is None:
            continue
        bounds = page.rect * page.derotation_matrix
        mid = bounds.width / 2
        double = (any(line["rect"].width > bounds.width * .2 and line["rect"].x1 <= mid + 6 for line in lines)
                  and any(line["rect"].width > bounds.width * .2 and line["rect"].x0 >= mid - 6 for line in lines))
        columns = [(bounds.x0, mid), (mid, bounds.x1)] if double else [(bounds.x0, bounds.x1)]
        start_column = int((heading["rect"].x0 + heading["rect"].x1) / 2 >= mid) if double else 0
        regions = []
        for column in range(start_column, len(columns)):
            x0, x1 = columns[column]
            y0 = heading["rect"].y1 if column == start_column else bounds.y0
            regions.append(pymupdf.Rect(x0, y0, x1, bounds.y1))
        result[index] = regions
        for next_index in range(index + 1, len(pages)):
            following = pages[next_index]
            if following.rotation:
                break
            following_lines = _visual_lines(following)
            following_bounds = following.rect * following.derotation_matrix
            following_mid = following_bounds.width / 2
            following_double = (
                any(line["rect"].width > following_bounds.width * .2
                    and line["rect"].x1 <= following_mid + 6 for line in following_lines)
                and any(line["rect"].width > following_bounds.width * .2
                        and line["rect"].x0 >= following_mid - 6 for line in following_lines))
            following_columns = ([(following_bounds.x0, following_mid),
                                  (following_mid, following_bounds.x1)] if following_double
                                 else [(following_bounds.x0, following_bounds.x1)])
            markers = [line for line in following_lines
                       if REFERENCE_MARK.match(line["text"])
                       and any(x0 - 2 <= (line["rect"].x0 + line["rect"].x1) / 2 <= x1 + 2
                               for x0, x1 in following_columns)]
            if len(markers) < 2:
                break
            if any(re.fullmatch(r"(?:APPENDIX|SUPPLEMENTARY|ACKNOWLEDG(?:E?MENTS?)?).*",
                                line["text"].strip(), re.I) for line in following_lines):
                break
            result[next_index] = [pymupdf.Rect(x0, following_bounds.y0, x1, following_bounds.y1)
                                  for x0, x1 in following_columns]
    return result


def normalize_document(document, pdf, *, force=False):
    if document.get("reference_schema") == SCHEMA:
        return False
    discovered = discover(pdf)
    if discovered is None:
        return False
    saved_page = document["pages"][discovered["page"] - 1]
    page = pdf[discovered["page"] - 1]
    heading_rect = pymupdf.Rect(discovered["heading_rect"])
    regions = [pymupdf.Rect(region["rect"]) + (-2, -.5, 2, .5) for region in discovered["regions"]]
    retained, legacy, heading_id = [], [], None
    for block in saved_page["blocks"]:
        box = pymupdf.Rect(block["bbox"][0] * page.rect.width, block["bbox"][1] * page.rect.height,
                           block["bbox"][2] * page.rect.width, block["bbox"][3] * page.rect.height) * page.derotation_matrix
        center = (box.tl + box.br) * .5
        if heading_rect.contains(center):
            block = {**block, "kind": "reference_heading"}
            heading_id = block["id"]
            retained.append(block)
        elif any(region.contains(center) for region in regions):
            legacy.append(copy.deepcopy(block))
        else:
            retained.append(block)
    if not legacy or not heading_id:
        return False
    # Existing fragment translations cannot safely be matched to complete
    # titles. Only an explicit reviewed migration may replace them with blanks.
    if not force and any(block.get("translation") for block in legacy):
        return False
    for entry in discovered["entries"]:
        first_column = entry["parts"][0]["column"]
        boxes = [pymupdf.Rect(part["rect"]) for part in entry["parts"] if part["column"] == first_column]
        rect = pymupdf.Rect(boxes[0])
        for box in boxes[1:]:
            rect |= box
        displayed = rect * page.rotation_matrix
        bounds = page.rect
        retained.append({"id": f"p{discovered['page']}-ref{entry['number']}", "kind": "reference", "reference_number": entry["number"],
                         "text": entry["text"], "reference": entry["reference"], "source_parts": entry["parts"],
                         "bbox": [displayed.x0 / bounds.width, displayed.y0 / bounds.height, displayed.x1 / bounds.width, displayed.y1 / bounds.height],
                         "translation": "", "target": "", "edited": False})
    saved_page["blocks"] = retained
    saved_page["reference_layout"] = {key: value for key, value in discovered.items() if key != "entries"}
    saved_page["reference_layout"]["heading_id"] = heading_id
    document["reference_legacy"] = {"page": discovered["page"], "blocks": legacy}
    document["reference_schema"] = SCHEMA
    document["total_blocks"] = sum(len(page["blocks"]) for page in document["pages"])
    return True

def prepare_bibliography(page, saved_page, native, overlays, prepared, source_rects, typography, target,
                         anchor_rects=None):
    """Preflight complete entries with hanging labels; never shrink each fragment."""
    layout = saved_page.get("reference_layout")
    if not layout:
        return None
    entries = sorted((block for block in saved_page["blocks"] if block.get("kind") == "reference"), key=lambda block: block["reference_number"])
    heading = next(block for block in saved_page["blocks"] if block["id"] == layout["heading_id"])
    heading_source = pymupdf.Rect(layout["heading_rect"])
    regions = [pymupdf.Rect(region["rect"]) for region in layout["regions"]]
    first = regions[0]
    left = min(first.x0, heading_source.x0)
    right = max(first.x1, heading_source.x1)
    # Reclaim the whitespace after the translated conclusion, without moving
    # references over figures or prose that still occupies the column.
    preceding = [result["rect"][3] for block, _, result in prepared
                 if source_rects[block["id"]].y1 <= heading_source.y0
                 and source_rects[block["id"]].x0 >= left - 10
                 and source_rects[block["id"]].x1 <= right + 10]
    heading_top = min(heading_source.y0, max(preceding, default=heading_source.y0 - 12) + 12)
    bottom = min(page.rect.height - 36, max(region.y1 for region in regions) + 9)
    columns = [pymupdf.Rect(left, heading_top + 19, right, bottom)]
    columns += [pymupdf.Rect(region.x0, region.y0, region.x1, bottom) for region in regions[1:]]
    start = len(overlays)
    normalize = lambda value: Counter(c for c in unicodedata.normalize("NFKC", value) if not c.isspace() and c != "\u00ad")
    source_sizes = Counter(round(span["size"], 3) for item in native for line in item["lines"] for span in line["spans"]
                           if any(region.contains((pymupdf.Rect(span["bbox"]).tl + pymupdf.Rect(span["bbox"]).br) * .5)
                                  for region in regions)
                           for char in span["text"] if not char.isspace())
    nominal_size = source_sizes.most_common(1)[0][0] if source_sizes else 8.0
    heading_sizes = [span["size"] for item in native for line in item["lines"] for span in line["spans"]
                     if heading_source.contains((pymupdf.Rect(span["bbox"]).tl + pymupdf.Rect(span["bbox"]).br) * .5)]
    heading_size = max(heading_sizes, default=nominal_size)
    for size in (nominal_size,):
        while len(overlays) > start:
            overlays.delete_page(-1)
        results, column, top, failed = [], 0, columns[0].y0, False
        for block in entries:
            text = block["translation"] if block.get("target") == target and block.get("translation") else block["text"]
            # Hang continuation lines under the authors, not under the number.
            content = re.sub(r"^\s*\[\d+\]\s*", "", text)
            reference = block.get("reference", {})
            author_prefix = reference.get("authors", "") + ". "
            publication = reference.get("publication", "")
            if content.startswith(author_prefix) and publication and content.endswith(publication):
                title = space_cjk_latin(content[len(author_prefix):-len(publication)])
                display = author_prefix + title + publication
                span_regions = [(0, len(author_prefix), "meta"),
                                (len(author_prefix), len(author_prefix) + len(title), "title"),
                                (len(author_prefix) + len(title), len(display), "meta")]
            else:
                display = content
                span_regions = []
            source_rows = _normalized_entry_rows(block, native)
            if span_regions and source_rows:
                span_regions, preserved_styles = _styled_metadata_regions(
                    display, span_regions, reference, block["text"], source_rows)
                if not preserved_styles:
                    failed = True
                    break
            ranges = _url_ranges(display)
            inner = _entry_inner(display, span_regions, ranges)
            anchors = [{"text": value, "kind": "uri", "uri": value, "ordinal": ordinal}
                       for _, _, value, ordinal in ranges]
            markup = f'<div class="entry">[{block["reference_number"]}] {inner}</div>'
            meta_size = size
            css = typography["css"] + (f"*{{margin:0;padding:0}}body{{font-family:serif;font-size:{meta_size}pt;"
                                        "line-height:1.24;text-align:left;font-weight:400}"
                                        "a:link,a:visited,a:hover{color:inherit;text-decoration:none}"
                                        ".entry{margin-left:14pt;text-indent:-14pt}"
                                        f".title{{font-family:{typography['family']};font-size:{size}pt}}"
                                        ".source-italic{font-style:italic}.source-bold{font-weight:600}")
            placed = None
            while column < len(columns):
                box = pymupdf.Rect(columns[column].x0, top, columns[column].x1, columns[column].y1)
                if box.height < size * 1.3:
                    column += 1
                    if column < len(columns):
                        top = columns[column].y0
                    continue
                scratch = overlays.new_page(width=page.rect.width, height=page.rect.height)
                spare, scale = scratch.insert_htmlbox(box, markup, css=css, archive=typography["archive"], scale_low=1)
                ink = [item for item in scratch.get_text("blocks") if item[6] == 0 and item[4].strip()]
                if spare >= 0 and ink and not (normalize(text) - normalize(scratch.get_text(clip=box))):
                    crop = pymupdf.Rect(box)
                    crop.y1 = min(box.y1, max(item[3] for item in ink) + 1)
                    placed = {"overlay": len(overlays) - 1, "rect": list(crop), "clip": list(crop), "scale": 1}
                    if anchors and anchor_rects is not None:
                        links = anchor_rects(scratch, anchors)
                        if links:
                            placed["links"] = links
                    top = crop.y1 + 3
                    break
                overlays.delete_page(-1)
                column += 1
                if column < len(columns):
                    top = columns[column].y0
            if placed is None:
                failed = True
                break
            results.append((block, {"spans": [], "size": size, "lines": []}, placed))
        if failed:
            continue
        # The first entry owns the original bibliography's text for redaction;
        # the remaining entries only paint their new preflighted overlays.
        owned = [span for item in native for line in item["lines"] for span in line["spans"]
                 if any((region + (-2, -.5, 2, .5)).contains((pymupdf.Rect(span["bbox"]).tl + pymupdf.Rect(span["bbox"]).br) * .5)
                        for region in regions + [heading_source])]
        results[0][1]["spans"] = owned
        scratch = overlays.new_page(width=page.rect.width, height=page.rect.height)
        heading_box = pymupdf.Rect(left, heading_top, right, heading_top + 17)
        text = heading.get("translation") if heading.get("target") == target else "References"
        text = text or "参考文献"
        css = typography["css"] + f"body{{margin:0;font-family:{typography['family']};font-size:{heading_size}pt;font-weight:600;text-align:center}}"
        spare, _ = scratch.insert_htmlbox(heading_box, html.escape(text), css=css, archive=typography["archive"], scale_low=1)
        if spare < 0:
            continue
        results.append((heading, {"spans": [], "size": heading_size, "lines": []},
                        {"overlay": len(overlays) - 1, "rect": list(heading_box), "clip": list(heading_box), "scale": 1}))
        return results, {"entries": len(entries), "font_size": size, "metadata_font_size": meta_size, "line_height": 1.24}
    while len(overlays) > start:
        overlays.delete_page(-1)
    return None


def _legacy_join(parts):
    """Join extraction fragments without inserting spaces inside Chinese words."""
    value = "\n".join(parts)
    value = re.sub(r"(?<=[\u3400-\u9fff])\s*\n\s*(?=[\u3400-\u9fff])", "", value)
    return clean_text(value)


def _reference_with_italic_title(text, rows):
    quoted = split_reference(text)
    if quoted:
        return quoted
    # An unquoted book/chapter title has a separate italic run in common
    # bibliography styles. Require exactly one run after the authors, instead
    # of guessing where an unstyled title or a publisher begins.
    runs, active = [], []
    for row in rows:
        for fragment in sorted(row["fragments"], key=lambda item: item["rect"].x0):
            for span in fragment.get("spans", ()):
                if not span["text"].strip():
                    if active:
                        active.append(span["text"])
                    continue
                italic = bool(span.get("flags", 0) & 2) or bool(re.search(r"italic|oblique|ital$", span.get("font", ""), re.I))
                if italic:
                    active.append(span["text"])
                elif active:
                    runs.append(clean_text("".join(active)))
                    active = []
        if active:
            active.append("\n")
    if active:
        runs.append(clean_text("".join(active)))
    if len(runs) != 1 or len(runs[0]) < 5:
        return None
    title = runs[0].strip(" .,")
    start = text.find(title)
    if start < 0 or text.find(title, start + 1) >= 0:
        return None
    prefix, suffix = text[:start], text[start + len(title):]
    number = re.match(r"\s*\[(\d+)\]", prefix)
    authors = re.sub(r"^\s*\[\d+\]\s*", "", prefix).rstrip(" ,")
    publication = suffix.lstrip(" .,;")
    if not number or not authors or not publication or not re.search(r"\b(?:18|19|20)\d\d\b", publication):
        return None
    return {"prefix": prefix, "title": title, "suffix": suffix, "authors": authors,
            "publication": publication, "number": int(number[1]), "italic_title": True}


def _legacy_title(translation, reference):
    """Read the translated title, while obtaining all citation data from source."""
    if not reference.get("italic_title"):
        start = re.search('[“"]', translation)
        if not start:
            return None
        # Broken extraction fragments can independently emit an opening quote.
        # Closing curly quotes still delimit the entire complete title.
        end = translation.find("”", start.end())
        if end < 0:
            end = translation.find('"', start.end())
        if end < 0:
            return None
        title = translation[start.end():end]
        if not re.search('[“”"]', reference["title"]):
            title = title.replace("“", "")
    else:
        # Author spellings and publisher names are usually retained even in
        # old full-entry translations. Their exact tokens provide two anchors;
        # if either changed, do not infer the title from punctuation alone.
        last_author = reference["authors"].rsplit(",", 1)[-1]
        last_author = re.sub(r"^\s*(?:and\s+)?", "", last_author).strip()
        last_name = last_author.split()[-1]
        author = re.search(re.escape(last_name) + r"[，,。.]?\s*", translation)
        publisher = re.match(r"[A-Za-z][A-Za-z’'&-]*(?:\s+[A-Za-z][A-Za-z’'&-]*)?", reference["publication"])
        if not author or not publisher:
            return None
        end = translation.find(publisher[0], author.end())
        if end < 0:
            return None
        title = translation[author.end():end].strip(" ，,。.;；")
    title = title.strip(" ，,。.;；")
    if not title or re.search(r"\[\s*\d+\s*\]", title):
        return None
    return title


def reconstruct_legacy_bibliography(page, saved_page, target, native=None):
    """Build a temporary bibliography plan without changing saved block IDs.

    It is deliberately independent of ``normalize_document``: existing manual
    fragment translations are read and validated, never migrated or discarded.
    A page containing an incomplete entry or unmatched numbering fails closed.
    """
    if saved_page.get("reference_layout"):
        return None
    lines = _visual_lines(page, native)
    heading = next((line for line in lines if HEADING.fullmatch(line["text"].strip())), None)
    if heading is None:
        return None
    bounds = page.rect * page.derotation_matrix
    mid = (bounds.x0 + bounds.x1) / 2
    left_prose = any(line["rect"].width > bounds.width * .2 and line["rect"].x1 <= mid + 6 for line in lines)
    right_prose = any(line["rect"].width > bounds.width * .2 and line["rect"].x0 >= mid - 6 for line in lines)
    # A column containing short bibliography entries need not have a line
    # longer than 20% of the page. Repeated reference markers are stronger
    # evidence than line length in that case.
    right_markers = sum(bool(REFERENCE_MARK.match(line["text"])) and line["rect"].x0 >= mid for line in lines)
    double = left_prose and (right_prose or right_markers >= 2)
    start_column = int(heading["rect"].x0 >= mid) if double else 0
    column_ids = list(range(start_column, 2)) if double else [0]
    entries, regions, current = [], [], None
    for position, column in enumerate(column_ids):
        selected = [line for line in lines if (not double or int((line["rect"].x0 + line["rect"].x1) / 2 >= mid) == column)
                    and (position > 0 or line["rect"].y0 >= heading["rect"].y1 - .5)
                    and not (re.fullmatch(r"\d+", line["text"]) and line["rect"].y0 >= bounds.y1 - 30)]
        rows = _rows(selected)
        if not rows:
            continue
        region = pymupdf.Rect(rows[0]["rect"])
        for row in rows:
            marker = re.match(r"^\s*\[(\d{1,4})\]\s*", row["text"])
            if marker:
                current = {"number": int(marker[1]), "rows": [], "column": position}
                entries.append(current)
            if current is None:
                return None
            current["rows"].append(row)
            region |= row["rect"]
        regions.append(region)
    if len(entries) < 2 or [e["number"] for e in entries] != list(range(1, len(entries) + 1)):
        return None
    # A complete source entry must have a delimited title and publication/year.
    # This also rejects bibliographies that carry an unfinished entry onward.
    for entry in entries:
        entry["source"] = clean_text("\n".join(row["text"] for row in entry["rows"]))
        entry["reference"] = _reference_with_italic_title(entry["source"], entry["rows"])
        ref = entry["reference"]
        if not ref or not re.search(r"\b(?:18|19|20)\d\d\b", ref["publication"]):
            return None
    def source_box(block):
        a, b, c, d = block["bbox"]
        return pymupdf.Rect(a * page.rect.width, b * page.rect.height,
                            c * page.rect.width, d * page.rect.height) * page.derotation_matrix
    candidates, heading_block = [], None
    for block in saved_page["blocks"]:
        box = source_box(block)
        center = (box.tl + box.br) * .5
        if heading["rect"].contains(center):
            heading_block = block
        elif any((region + (-2, -.5, 2, .5)).contains(center) for region in regions):
            candidates.append((block, box))
    if not candidates or heading_block is None:
        return None
    def order(item):
        box = item[1]
        column = next((i for i, region in enumerate(regions) if region.x0 - 2 <= box.x0 <= region.x1), len(regions))
        return column, box.y0, box.x0
    candidates.sort(key=order)
    if any(not block.get("translation") or block.get("target") != target for block, _ in candidates):
        return None
    source_stream = _legacy_join([block["text"] for block, _ in candidates])
    translated_stream = _legacy_join([block["translation"] for block, _ in candidates])
    source_markers = re.findall(r"\[\s*(\d{1,4})\s*\]", source_stream)
    translated_markers = list(re.finditer(r"\[\s*(\d{1,4})\s*\]", translated_stream))
    expected = [str(entry["number"]) for entry in entries]
    if source_markers != expected or [mark[1] for mark in translated_markers] != expected:
        return None
    for index, entry in enumerate(entries):
        start = translated_markers[index].start()
        end = translated_markers[index + 1].start() if index + 1 < len(entries) else len(translated_stream)
        title = _legacy_title(translated_stream[start:end], entry["reference"])
        if title is None:
            return None
        title = re.sub(r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])", "", title)
        entry["title"] = title
        ref = entry["reference"]
        entry["separator"] = "。" if re.search(r"[\u3400-\u9fff]", title) else ". "
        entry["text"] = f'[{entry["number"]}] {ref["authors"]}. {title}{entry["separator"]}{ref["publication"]}'
        entry["members"] = [block["id"] for block, box in candidates
                            if any(box.intersects(row["rect"]) and (box & row["rect"]).height > min(box.height, row["rect"].height) * .6
                                   for row in entry["rows"])]
        if not entry["members"]:
            return None
        spans = [span for row in entry["rows"] for fragment in row["fragments"] for span in fragment.get("spans", ())]
        entry["spans"] = spans
        sizes = [round(span["size"], 3) for span in spans for char in span["text"] if not char.isspace()]
        if not sizes:
            return None
        entry["size"] = Counter(sizes).most_common(1)[0][0]
    sizes = [entry["size"] for entry in entries]
    baseline_steps = [b["rect"].y0 - a["rect"].y0 for entry in entries for a, b in zip(entry["rows"], entry["rows"][1:])
                      if 0 < b["rect"].y0 - a["rect"].y0 < entry["size"] * 2]
    nominal = statistics.median(sizes)
    leading = statistics.median(baseline_steps) / nominal if baseline_steps else 1.2
    return {"entries": entries, "regions": regions, "heading": heading_block, "heading_source": heading,
            "consumed_ids": [heading_block["id"], *[block["id"] for block, _ in candidates]],
            "source_size": nominal, "line_height": min(1.4, max(1.08, leading)), "bounds": list(bounds)}


def prepare_legacy_bibliography(page, saved_page, native, overlays, prepared, source_rects, typography, target,
                                *, plan, anchor_rects=None, source_links=()):
    """Typeset complete legacy entries at source size; commit only a full fit."""
    if not plan:
        return None
    start = len(overlays)
    entries, regions = plan["entries"], plan["regions"]
    heading = plan["heading"]
    heading_text = heading.get("translation") if heading.get("target") == target else heading["text"]
    heading_entry = {"number": 0, "rows": [{"rect": plan["heading_source"]["rect"]}],
                     "reference": {"title": heading["text"]}, "title": heading_text}
    link_owners = _reference_link_owners([heading_entry, *entries], source_links)
    if link_owners is None:
        plan["failure_reason"] = "参考文献的原始链接跨越多个条目，无法安全重建点击位置，已保留完整原文"
        return None
    source_chars = None
    if any(link_owners.values()):
        if anchor_rects is None:
            plan["failure_reason"] = "参考文献含原始链接，但无法验证译文锚点，已保留完整原文"
            return None
        source_chars = [char for block in page.get_text("rawdict", flags=pymupdf.TEXTFLAGS_RAWDICT & ~pymupdf.TEXT_PRESERVE_IMAGES)["blocks"]
                        for line in block.get("lines", ()) for span in line["spans"] for char in span.get("chars", ())]
    bounds = pymupdf.Rect(plan["bounds"])
    # Preserve bibliography column ownership and the original heading position.
    # A translated bibliography may need a few more lines. Use the empty tail
    # of its own column, stopping before any following text/graphic and leaving
    # at least two source ems as a page margin. Pagination and artwork stay put.
    minimum_margin = max(18, plan["source_size"] * 2)
    columns = [pymupdf.Rect(region.x0, region.y0, region.x1, max(region.y1, bounds.y1 - minimum_margin)) for region in regions]
    own = {id(span) for entry in entries for span in entry["spans"]}
    heading_source = plan["heading_source"]
    owned_rows = [row["rect"] for entry in entries for row in entry["rows"]]
    for column, region in zip(columns, regions):
        obstacles = [pymupdf.Rect(span["bbox"]) for block in native for line in block["lines"] for span in line["spans"]
                     if id(span) not in own and span["text"].strip()
                     and not heading_source["rect"].contains((pymupdf.Rect(span["bbox"]).tl + pymupdf.Rect(span["bbox"]).br) * .5)]
        obstacles = [box for box in obstacles if not any((row + (-.1, -.1, .1, .1)).contains(box) for row in owned_rows)]
        obstacles += [pymupdf.Rect(image["bbox"]) for image in page.get_image_info()]
        obstacles += [pymupdf.Rect(drawing["rect"]) for drawing in visible_drawings(page)
                      if drawing["rect"].get_area() > 1]
        for box in obstacles:
            if min(column.x1, box.x1) > max(column.x0, box.x0) and box.y0 >= region.y1:
                column.y1 = min(column.y1, box.y0 - 2)
        if any((column & box).get_area() > 1 for box in obstacles):
            # ``plan`` can be built with a separate native extraction. In that
            # case span identities differ; compare geometry to the owned rows.
            if any((column & box).get_area() > 1 and not any((row + (-.1, -.1, .1, .1)).contains(box) for row in owned_rows)
                   for box in obstacles):
                return None
    normalize = lambda value: Counter(c for c in unicodedata.normalize("NFKC", value) if not c.isspace() and c != "\u00ad")
    results, column_index, top, new_sources = [], 0, columns[0].y0, {}
    for entry in entries:
        size, ref = entry["size"], entry["reference"]
        prefix = f'[{entry["number"]}] {ref["authors"]}. '
        title = space_cjk_latin(entry["title"]) + entry["separator"]
        display = prefix + title + ref["publication"]
        title_end = len(prefix) + len(title)
        spans = [(0, len(prefix), "meta"), (len(prefix), title_end, "title"), (title_end, len(display), "meta")]
        spans, preserved_styles = _styled_metadata_regions(display, spans, ref, entry["source"], entry["rows"])
        if not preserved_styles:
            plan["failure_reason"] = "参考文献作者或出版字段的原字形样式无法完整对应，已保留完整原文"
            while len(overlays) > start: overlays.delete_page(-1)
            return None
        ranges = _url_ranges(display)
        inner = _entry_inner(display, spans, ranges)
        indent = max(12, size * (1.8 if entry["number"] < 10 else 2.3))
        markup = f'<div class="entry">{inner}</div>'
        css = typography["css"] + (f'*{{margin:0;padding:0}}body{{margin:0;padding:0;font-family:{typography["family"]};font-size:{size}pt;'
                f'line-height:{plan["line_height"]};font-weight:400;text-align:left}}'
                f'.entry{{margin-left:{indent}pt;text-indent:-{indent}pt}}'
                '.meta{font-family:serif}.source-italic{font-style:italic}.source-bold{font-weight:600}'
                'a:link,a:visited,a:hover{color:inherit;text-decoration:none}')
        if ref.get("italic_title"):
            css += '.title{font-style:italic}'
        placed = None
        while column_index < len(columns):
            column = columns[column_index]
            box = pymupdf.Rect(column.x0, top, column.x1, column.y1)
            if box.height <= size:
                column_index += 1
                if column_index < len(columns): top = columns[column_index].y0
                continue
            scratch = overlays.new_page(width=page.rect.width, height=page.rect.height)
            spare, _ = scratch.insert_htmlbox(box, markup, css=css, archive=typography["archive"], scale_low=1)
            ink = [item for item in scratch.get_text("blocks") if item[6] == 0 and item[4].strip()]
            if spare >= 0 and ink and not (normalize(entry["text"]) - normalize(scratch.get_text(clip=box))):
                crop = pymupdf.Rect(box.x0, box.y0, box.x1, min(box.y1, max(item[3] for item in ink) + .1))
                placed = {"overlay": len(overlays) - 1, "rect": list(crop), "clip": list(crop), "scale": 1,
                          "font_reason": "complete-reference-source-size", "reference_number": entry["number"]}
                anchors = [{"text": value, "kind": "uri", "uri": value, "ordinal": ordinal}
                           for _, _, value, ordinal in ranges]
                mapped = _reference_link_anchors(entry, display, link_owners[entry["number"]], source_chars or ())
                if mapped is None:
                    plan["failure_reason"] = "参考文献的多个原始链接无法与独立译文锚点可靠对应，已保留完整原文"
                    while len(overlays) > start: overlays.delete_page(-1)
                    return None
                # Source annotations own existing URL anchors; automatic URL
                # detection must not add a second annotation over the same text.
                anchors = [item for item in anchors if not any(item["kind"] == link["kind"]
                           and item.get("uri") == link.get("uri") and _reference_key(item["text"]) == _reference_key(link["text"])
                           for link in mapped)] + mapped
                if anchors and anchor_rects is not None:
                    resolved = anchor_rects(scratch, anchors)
                    if len(resolved) != len(anchors):
                        plan["failure_reason"] = "参考文献原始链接在译文中无法精确定位，已保留完整原文"
                        while len(overlays) > start: overlays.delete_page(-1)
                        return None
                    for link, anchor in zip(resolved, anchors):
                        if anchor.get("source_aliases"):
                            link["source_aliases"] = anchor["source_aliases"]
                    # Distinct targets must not compete for the same clickable
                    # text, even if both source links covered title fragments.
                    if any(_reference_link_identity(a) != _reference_link_identity(b)
                           and any((pymupdf.Rect(x) & pymupdf.Rect(y)).get_area() > .1 for x in a["rects"] for y in b["rects"])
                           for i, a in enumerate(resolved) for b in resolved[i + 1:]):
                        plan["failure_reason"] = "参考文献不同原始链接的译文点击区域重叠，已保留完整原文"
                        while len(overlays) > start: overlays.delete_page(-1)
                        return None
                    placed["links"] = resolved
                # The next entry follows the layout engine's baseline advance,
                # not the font's extraction bbox. CJK font bboxes include the
                # full em square, which is larger than actual ink and would
                # otherwise add a spurious gap after every bibliography item.
                top = box.y1 - spare
                break
            overlays.delete_page(-1)
            column_index += 1
            if column_index < len(columns): top = columns[column_index].y0
        if placed is None:
            while len(overlays) > start: overlays.delete_page(-1)
            return None
        block = {"id": f'{entry["members"][0]}::reference:{entry["number"]}', "_members": entry["members"],
                 "_reference_entry": True, "_fixed_structure": True, "kind": "reference",
                 "text": entry["source"], "translation": entry["text"], "target": target}
        source = pymupdf.Rect(entry["rows"][0]["rect"])
        for row in entry["rows"][1:]: source |= row["rect"]
        new_sources[block["id"]] = source
        placed["structure"] = [{"kind": "reference_entry", "source": list(source), "rect": placed["rect"],
                                 "text": entry["text"], "source_size": size, "output_size": size}]
        results.append((block, {"spans": entry["spans"], "size": size, "lines": [], "bold": False, "italic": False}, placed))
    # A heading is independent of the source entries' paragraph spacing.
    heading = plan["heading"]
    spans = heading_source.get("spans", ())
    size = max((span["size"] for span in spans), default=plan["source_size"] * 1.25)
    box = heading_source["rect"]
    scratch = overlays.new_page(width=page.rect.width, height=page.rect.height)
    title = heading.get("translation") if heading.get("target") == target else heading["text"]
    css = typography["css"] + f'body{{margin:0;font-family:{typography["family"]};font-size:{size}pt;text-align:center;line-height:1}}'
    # Expand into the safe reference column width, not into adjacent prose.
    heading_box = pymupdf.Rect(regions[0].x0, box.y0, regions[0].x1, regions[0].y0 - .3)
    spare, _ = scratch.insert_htmlbox(heading_box, html.escape(title), css=css, archive=typography["archive"], scale_low=1)
    if spare < 0:
        while len(overlays) > start: overlays.delete_page(-1)
        return None
    heading_links = _reference_link_anchors(heading_entry, title, link_owners[0], source_chars or ())
    if heading_links is None or len({_reference_link_identity(link) for link in heading_links}) > 1:
        plan["failure_reason"] = "参考文献标题的多个原始链接无法安全重建，已保留完整原文"
        while len(overlays) > start: overlays.delete_page(-1)
        return None
    resolved_heading_links = anchor_rects(scratch, heading_links) if heading_links else []
    if len(resolved_heading_links) != len(heading_links):
        plan["failure_reason"] = "参考文献标题的原始链接在译文中无法精确定位，已保留完整原文"
        while len(overlays) > start: overlays.delete_page(-1)
        return None
    for link, anchor in zip(resolved_heading_links, heading_links):
        link["source_aliases"] = anchor["source_aliases"]
    results.append(({**heading, "_reference_entry": True, "_fixed_structure": True},
                    {"spans": list(spans), "size": size, "lines": [], "bold": False, "italic": False},
                    {"overlay": len(overlays) - 1, "rect": list(heading_box), "clip": list(heading_box), "scale": 1,
                     "font_reason": "reference-heading-source-size", "links": resolved_heading_links,
                     "structure": [{"kind": "reference_heading",
                     "source": list(box), "rect": list(heading_box), "text": title, "source_size": size, "output_size": size}]}))
    details = {"entries": len(entries), "font_size": plan["source_size"], "line_height": plan["line_height"],
               "legacy_ids_preserved": True, "metadata_styles_preserved": True, "consumed_ids": plan["consumed_ids"],
               "entry_details": [{"number": entry["number"], "source": entry["source"], "text": entry["text"],
                                  "title": entry["title"], "blocks": entry["members"]} for entry in entries]}
    source_rects.update(new_sources)
    return results, details


def _reference_key(value):
    return "".join(unicodedata.normalize("NFKC", value).split()).strip(' ,.;:，。；：“”"')


def _reference_link_identity(link):
    return link["kind"], link.get("uri"), link.get("page"), tuple(link.get("to") or ())


def _reference_link_owners(entries, links):
    owners = {entry["number"]: [] for entry in entries}
    for link in links:
        box = pymupdf.Rect(link["rect"])
        if box.get_area() <= 0:
            continue
        scores = sorted([(sum((box & row["rect"]).get_area() for row in entry["rows"]), entry["number"])
                         for entry in entries], reverse=True)
        if not scores or scores[0][0] <= .1:
            continue
        if scores[0][0] < box.get_area() * .5:
            return None
        if len(scores) > 1 and scores[1][0] > box.get_area() * .3:
            return None
        owners[scores[0][1]].append(link)
    return owners


def _reference_link_anchors(entry, display, links, chars):
    result = []
    display_key = _reference_key(display)
    title_key = _reference_key(entry["reference"]["title"])
    for link in links:
        box = pymupdf.Rect(link["rect"])
        selected = [char for char in chars if box.contains((pymupdf.Rect(char["bbox"]).tl + pymupdf.Rect(char["bbox"]).br) * .5)]
        selected.sort(key=lambda char: (round(char["origin"][1], 1), char["origin"][0]))
        key = _reference_key("".join(char["c"] for char in selected))
        if not key:
            return None
        if len(key) >= 3 and key in title_key:
            text = entry["title"]
        elif len(key) >= 3 and display_key.count(key) == 1:
            text = key
        else:
            return None
        candidate = {**link, "text": text, "source": link["rect"], "source_aliases": [link["rect"]], "ordinal": 0}
        identical = next((item for item in result if _reference_link_identity(item) == _reference_link_identity(candidate)
                          and _reference_key(item["text"]) == _reference_key(text)), None)
        if identical:
            identical["source_aliases"].append(link["rect"])
        else:
            result.append(candidate)
    return result
