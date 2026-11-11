"""Translate independently positioned table cells without rebuilding the artwork.

Saved extraction blocks are retained as the public identity.  A block is only
accepted if all its translated lines map unambiguously to native lines or to
vertically stacked header cells.  Unchanged cells, including numbers, formula
glyphs, product names and raised notes, remain on the source PDF.
"""
import html
import hashlib
import re
import unicodedata
from collections import Counter

import pymupdf


def _normalized(text):
    return "".join(unicodedata.normalize("NFKC", text or "").split())


def _line_text(line):
    return "".join(span["text"] for span in line["spans"]).strip()


def _union(boxes):
    result = pymupdf.Rect(boxes[0])
    for box in boxes[1:]:
        result |= pymupdf.Rect(box)
    return result


def _cell(lines):
    spans = [s for line in lines for s in line["spans"] if s["text"].strip()]
    size_counts = Counter()
    for span in spans:
        size_counts[round(span["size"], 3)] += len(span["text"].strip())
    size = size_counts.most_common(1)[0][0]
    return {"lines": lines, "spans": spans, "rect": _union([l["bbox"] for l in lines]),
            "source": " ".join(_line_text(line) for line in lines), "size": size}


def _native_lines(native, rect):
    """Do not take a neighbour just because padded font boxes intersect."""
    return [line for block in native for line in block["lines"]
            if rect.contains((pymupdf.Rect(line["bbox"]).tl + pymupdf.Rect(line["bbox"]).br) * .5)
            and (pymupdf.Rect(line["bbox"]) & rect).get_area()
            >= pymupdf.Rect(line["bbox"]).get_area() * .8]


def table_note_region(rect, native, table_boxes):
    """Associate raised-marker notes just below a table with its safe width.

    Font frames can start above a bottom rule because an empty space inherits
    a high baseline. Real marker/body baselines and neighbouring table geometry
    identify these notes; ordinary paragraphs and captions are never included.
    """
    lines = _native_lines(native, rect)
    if not 1 <= len(lines) <= 4:
        return None
    sizes = []
    for line in lines:
        spans = [s for s in line["spans"] if s["text"].strip()]
        if len(spans) < 2 or not re.fullmatch(r"[†‡§¶∥*a-z0-9]+", spans[0]["text"].strip()):
            return None
        size = max(s["size"] for s in spans[1:])
        if not (spans[0]["size"] <= size * .9
                and spans[0]["origin"][1] < max(s["origin"][1] for s in spans[1:]) - .5):
            return None
        sizes.append(size)
    size = max(sizes)
    for table in table_boxes:
        if (0 <= rect.y0 - table.y1 <= size * 2.5 and rect.height <= size * 4
                and table.x0 - size <= rect.x0 and rect.x1 <= table.x1 + size):
            table_sizes = [s["size"] for line in _native_lines(native, table)
                           for s in line["spans"] if s["text"].strip()]
            if not table_sizes or size > max(table_sizes) * 1.1:
                continue
            return pymupdf.Rect(table.x0, table.y0, table.x1, max(table.y1, rect.y1))
    return None


def cell_mapping(lines, source, translation):
    """Return verified native cell / translated text pairs, or a reason.

    PDF extractors often list the first line of every header before the second
    line.  In that case separate cells are recovered from their shared centre
    axes and disjoint x intervals, never from a vocabulary or column count.
    """
    if not lines or _normalized("".join(_line_text(l) for l in lines)) != _normalized(source):
        return None, "保存文字与原生表格行不能完整对应"
    if any(abs(l.get("dir", (1, 0))[0] - 1) > .01 or abs(l.get("dir", (1, 0))[1]) > .01
           for l in lines):
        return None, "单元格文字方向无法安全重排"
    translated = [line.strip() for line in translation.splitlines() if line.strip()]
    if len(lines) == len(translated):
        return [(dict(_cell([line]), translation=value), "native-line")
                for line, value in zip(lines, translated)], ""
    groups = []
    for line in sorted(lines, key=lambda line: (line["bbox"][0] + line["bbox"][2], line["bbox"][1])):
        rect = pymupdf.Rect(line["bbox"])
        size = max(span["size"] for span in line["spans"])
        centre = (rect.x0 + rect.x1) / 2
        matching = [group for group in groups
                    if abs(centre - group["centre"]) <= max(1.2, size * .22)]
        if len(matching) > 1:
            return None, "多行表头的列轴不唯一"
        if matching:
            matching[0]["lines"].append(line)
        else:
            groups.append({"centre": centre, "lines": [line]})
    if len(groups) != len(translated) or not any(len(g["lines"]) > 1 for g in groups):
        return None, "译文行数与可识别的单元格数量不一致"
    cells = []
    for group in sorted(groups, key=lambda group: group["centre"]):
        ordered = sorted(group["lines"], key=lambda line: line["bbox"][1])
        for previous, current in zip(ordered, ordered[1:]):
            size = max(s["size"] for s in current["spans"])
            baseline_gap = current["spans"][0]["origin"][1] - previous["spans"][0]["origin"][1]
            if not .55 * size <= baseline_gap <= 1.65 * size:
                return None, "跨数据行的同列文字不能合并为表头"
        cells.append(_cell(ordered))
    if any(first["rect"].x1 >= second["rect"].x0 - .1 for first, second in zip(cells, cells[1:])):
        return None, "多行表头单元格的水平区域相交"
    if max(cell["rect"].y0 for cell in cells) > min(cell["rect"].y1 for cell in cells):
        return None, "多行表头不在同一行带"
    return [(dict(cell, translation=value), "stacked-header") for cell, value in zip(cells, translated)], ""


def _ink_boxes(page):
    return [pymupdf.Rect(coords) for kind, coords, *_ in page.get_bboxlog()
            if kind in {"fill-text", "stroke-text"}]


def _painted_bounds(page, box):
    """Measure painted alpha, avoiding bboxlog's padding around close rows."""
    scale = 6
    pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), clip=box, alpha=True)
    alpha = memoryview(pix.samples)[pix.n - 1::pix.n]
    occupied = [index for index, value in enumerate(alpha) if value]
    if not occupied:
        return None
    xs = [index % pix.width for index in occupied]
    ys = [index // pix.width for index in occupied]
    # One sample of padding covers differences in fractional placement.
    return pymupdf.Rect((pix.x + min(xs) - 1) / scale, (pix.y + min(ys) - 1) / scale,
                        (pix.x + max(xs) + 2) / scale, (pix.y + max(ys) + 2) / scale)


def _fixed_text(native, owned, operations, trace):
    fixed = []
    for block in native:
        for line in block["lines"]:
            spans = [s for s in line["spans"] if s["text"].strip() and id(s) not in owned]
            if not spans:
                continue
            box = _union([s["bbox"] for s in spans])
            measured = [ink for ink in operations if (box + (-1, -1, 1, 1)).contains(ink)
                        and (box & ink).get_area() > ink.get_area() * .5]
            # Native font frames may overlap a neighbouring baseline even
            # though its glyphs do not. Prefer the actual painted operation.
            fixed.extend(ink + (.35, .35, -.35, -.35) for ink in measured)
            if not measured:
                for span in spans:
                    frame = pymupdf.Rect(span["bbox"])
                    chars = [pymupdf.Rect(char[3]) for char in trace
                             if frame.x0 - .05 <= char[2][0] < frame.x1 - .05
                             and frame.y0 <= char[2][1] <= frame.y1]
                    fixed.extend(chars or [frame])
    return fixed


def _safe_bounds(cell, lines, region, drawings):
    box, size = cell["rect"], cell["size"]
    own = {id(line) for line in cell["lines"]}
    left, right = region.x0 - size, region.x1 + size
    for line in lines:
        if id(line) in own:
            continue
        other = pymupdf.Rect(line["bbox"])
        if min(other.y1, box.y1) - max(other.y0, box.y0) <= size * .2:
            continue
        if other.x1 <= box.x0 + .1:
            left = max(left, (other.x1 + box.x0) / 2)
        elif other.x0 >= box.x1 - .1:
            right = min(right, (other.x0 + box.x1) / 2)
    for drawing in drawings:
        edge = pymupdf.Rect(drawing["rect"])
        if edge.width < .8 and edge.y0 < box.y1 and edge.y1 > box.y0:
            if edge.x0 <= box.x0:
                left = max(left, edge.x0 + .5)
            elif edge.x0 >= box.x1:
                right = min(right, edge.x0 - .5)
    return left + .2, right - .2


def _translated_payload(cell):
    """Keep a matching raised note glyph and its exact original baseline."""
    spans = list(cell["spans"])
    value = cell["translation"]
    retained = []
    if len(cell["lines"]) != 1:
        return value, spans, retained
    while spans and (spans[0].get("flags", 0) & 1 or spans[0]["size"] < cell["size"] * .85):
        text = spans[0]["text"].strip()
        if not re.fullmatch(r"[†‡§¶∥*a-z0-9]+", text) or not value.startswith(text):
            break
        retained.append(spans.pop(0))
        value = value[len(text):].lstrip()
    # A translated connecting word between a note mark and an unchanged name
    # can use its own small gap. Retain that complete trailing span rather
    # than redrawing a longer Latin product name in the Chinese font.
    if len(spans) == 2 and value.endswith(spans[-1]["text"].strip()):
        retained.append(spans.pop())
        value = value[:-len(retained[-1]["text"].strip())].rstrip()
    return value, spans, retained


def _source_latin_face(page, spans, archive, cache):
    """Use the source's embedded Latin face for unchanged names and numbers."""
    counts = Counter()
    for span in spans:
        counts[span["font"]] += sum(char.isascii() and char.isalnum() for char in span["text"])
    if not counts or not counts.most_common(1)[0][1]:
        return None
    name = counts.most_common(1)[0][0]
    if name in cache:
        return cache[name]
    cache[name] = None
    for item in page.get_fonts(full=True):
        if item[3].split("+", 1)[-1] != name.split("+", 1)[-1]:
            continue
        try:
            _, extension, _, data = page.parent.extract_font(item[0])
            if not data or extension == "n/a":
                continue
            font = pymupdf.Font(fontbuffer=data)
            identity = hashlib.sha256(data).hexdigest()[:12]
            family, filename = "TableLatin" + identity, "table-" + identity + "." + extension
            archive.add((data, filename))
            cache[name] = (family, font, f"@font-face{{font-family:{family};src:url({filename})}}")
            break
        except (RuntimeError, ValueError):
            continue
    return cache[name]


def _text_markup(text, face):
    if face is None:
        return html.escape(text)
    family, font, _ = face
    pieces = []
    # Some embedded Type 1 subsets map the hyphen glyph back to U+00AD.
    # Let the bundled face print ASCII '-' so search/copy keeps its identity.
    for chunk in re.split(r"([\x20-\x2c\x2e-\x7e]+)", text):
        escaped = html.escape(chunk)
        if (chunk and re.fullmatch(r"[\x20-\x2c\x2e-\x7e]+", chunk)
                and all(char.isspace() or font.has_glyph(ord(char)) for char in chunk)):
            escaped = f'<span style="font-family:{family};font-weight:400;font-style:normal">{escaped}</span>'
        pieces.append(escaped)
    return "".join(pieces)


def _balanced_markup(text, face):
    """Avoid a lone CJK character on the last line of a narrow table header."""
    widths = [1 if unicodedata.east_asian_width(char) in {"W", "F"} else .5 for char in text]
    total = sum(widths)
    candidates = []
    for index in range(1, len(text)):
        a, b = text[index - 1], text[index]
        if a.isascii() and a.isalnum() and b.isascii() and b.isalnum():
            continue
        if b in ",.;:!?、，。；：！？)]）】" or a in "([（【":
            continue
        candidates.append((abs(total - 2 * sum(widths[:index])), index))
    if not candidates:
        return _text_markup(text, face)
    index = min(candidates)[1]
    return _text_markup(text[:index].rstrip(), face) + "<br>" + _text_markup(text[index:].lstrip(), face)


def prepare_table_overlays(page, blocks, rects, native, table_boxes, overlays, typography, target,
                           *, links=(), drawings=()):
    """Return (prepared, handled_ids, issues, details), without changing the page.

    The caller owns source redaction and overlay placement. Every failed block
    is untouched. Accepted blocks may contain unchanged cells; those cells are
    counted as handled but have no redaction or replacement glyphs.
    """
    prepared, handled, issues, details = [], set(), [], []
    all_lines = [line for item in native for line in item["lines"]]
    source_operations = _ink_boxes(page)
    archive = pymupdf.Archive()
    if typography["archive"] is not None:
        archive.add(typography["archive"])
    font_cache = {}
    trace = [char for span in page.get_texttrace() if span.get("type") != 3
             for char in span["chars"] if not chr(char[0]).isspace()]
    for block in blocks:
        block_rect = rects[block["id"]]
        region = next((box for box in table_boxes
                       if (block_rect & box).get_area() >= block_rect.get_area() * .5), None)
        if region is None:
            region = table_note_region(block_rect, native, table_boxes)
        if region is None:
            continue
        reason = ""
        if not block.get("translation") or block.get("target") != target:
            continue
        lines = _native_lines(native, block_rect)
        mapped, reason = cell_mapping(lines, block["text"], block["translation"])
        if reason:
            issues.append({"block_id": block["id"], "kind": "table", "message": reason})
            continue
        changed = [(cell, mode) for cell, mode in mapped
                   if _normalized(cell["source"]) != _normalized(cell["translation"])]
        if not changed:
            handled.add(block["id"])
            details.append({"blocks": block.get("_members", [block["id"]]), "cells": len(mapped),
                            "translated_cells": 0, "source_glyph_cells": len(mapped), "complete": True})
            continue
        all_owned, payloads = set(), []
        for cell, mode in changed:
            value, spans, retained = _translated_payload(cell)
            if re.findall(r"\d+(?:[.,]\d+)*", cell["source"]) != re.findall(r"\d+(?:[.,]\d+)*", cell["translation"]):
                reason = "单元格译文改变了数字，保留完整原文"
                break
            if any((cell["rect"] & pymupdf.Rect(link["rect"])).get_area() > .1 for link in links):
                reason = "含链接的改译单元格无法安全重建锚点"
                break
            if any(re.search(r"(?:cmmi|cmsy|cmex|math|symbol)", span["font"], re.I) for span in spans):
                reason = "改译单元格含数学字体，无法可靠保持数学字形"
                break
            if not spans:
                reason = "改译单元格没有可替换正文"
                break
            all_owned.update(id(span) for span in spans)
            payloads.append((cell, mode, value, spans, retained))
        if reason:
            issues.append({"block_id": block["id"], "kind": "table", "message": reason})
            continue
        fixed = _fixed_text(native, all_owned, source_operations, trace)
        occupied = []
        start = len(overlays)
        composite = overlays.new_page(width=page.rect.width, height=page.rect.height)
        composite_index = len(overlays) - 1
        changed_spans, cell_details = [], []
        overlay_region = None
        for cell, mode, value, spans, retained in payloads:
            box, size = cell["rect"], cell["size"]
            left, right = _safe_bounds(cell, all_lines, region, drawings)
            centre = (box.x0 + box.x1) / 2
            width = max(0, min(centre - left, right - centre) * 2)
            alignment = "center"
            if retained:
                # A retained note marker fixes the text's left edge, rather
                # than allowing a recentered translation to cover the marker.
                body = _union([span["bbox"] for span in spans])
                prefixes = [s["bbox"][2] for s in retained if s["bbox"][2] <= body.x0 + .1]
                suffixes = [s["bbox"][0] for s in retained if s["bbox"][0] >= body.x1 - .1]
                if suffixes:
                    centre = (body.x0 + body.x1) / 2
                    left = max(left, max(prefixes, default=left) + .4)
                    right = min(right, min(suffixes) - .4)
                    width = max(0, min(centre - left, right - centre) * 2)
                else:
                    left = max(left, body.x0, max(prefixes, default=left) + .4)
                    centre, width = (left + right) / 2, max(0, right - left)
                    alignment = "left"
            weight = sum(len(s["text"]) for s in spans if s.get("flags", 0) & 16)
            bold = weight > sum(len(s["text"]) for s in spans) * .75
            italic = all(s.get("flags", 0) & 2 for s in spans)
            face = _source_latin_face(page, spans, archive, font_cache)
            css = typography["css"] + (face[2] if face else "") + (f"*{{margin:0;padding:0}}body{{font-family:{typography['family']};"
                  f"font-size:{size}pt;line-height:1.05;text-align:{alignment};font-weight:{600 if bold else 400};"
                  f"font-style:{'italic' if italic else 'normal'};color:#{spans[0]['color']:06x}}}")
            with pymupdf.open() as scratch:
                rendered = scratch.new_page(width=page.rect.width, height=page.rect.height)
                fit = pymupdf.Rect(centre - width / 2, 10, centre + width / 2, 10 + size * 8)
                if width <= 1:
                    reason = "单元格没有安全水平空间"
                    break
                spare, scale = rendered.insert_htmlbox(fit, _text_markup(value, face), css=css,
                                                       archive=archive, scale_low=1)
                output = [line for b in rendered.get_text("dict")["blocks"] if b["type"] == 0 for line in b["lines"]]
                if (len(cell["lines"]) > 1 and len(output) == 2
                        and len(_normalized(_line_text(output[-1]))) < len(_normalized(value)) * .28):
                    rendered = scratch.new_page(width=page.rect.width, height=page.rect.height)
                    spare, scale = rendered.insert_htmlbox(fit, _balanced_markup(value, face), css=css,
                                                           archive=archive, scale_low=1)
                    output = [line for b in rendered.get_text("dict")["blocks"] if b["type"] == 0 for line in b["lines"]]
                    mode += "-balanced-wrap"
                if spare < 0 or _normalized(rendered.get_text()) != _normalized(value) or not output:
                    reason = "单元格译文无法以原字号完整排印"
                    break
                source_baselines = [max(s["origin"][1] for s in line["spans"]
                                        if s["text"].strip()) for line in cell["lines"]]
                output_baselines = [max(s["origin"][1] for s in line["spans"]) for line in output]
                shift = (min(source_baselines) + max(source_baselines)
                         - min(output_baselines) - max(output_baselines)) / 2
                actual = _union([line["bbox"] for line in output])
                ink = _painted_bounds(rendered, actual + (-1, -1, 1, 1))
                if ink is None:
                    reason = "单元格没有可见译文字形"
                    break
                painted = ink + (0, shift, 0, shift)
                if not page.rect.contains(painted) or any((painted & other).get_area() > .1 for other in fixed + occupied):
                    reason = "单元格译文在原字号下会接触相邻文字"
                    break
                if any((painted & (pymupdf.Rect(d["rect"]) + (-.25, -.25, .25, .25))).get_area() > .05
                       and not pymupdf.Rect(d["rect"]).contains(box) for d in drawings):
                    reason = "单元格译文在原字号下会接触表格边线"
                    break
                clip = actual + (-.2, -.2, .2, .2)
                destination = clip + (0, shift, 0, shift)
                composite.show_pdf_page(destination, scratch, rendered.number, clip=clip)
                overlay_region = destination if overlay_region is None else overlay_region | destination
                occupied.append(painted)
                changed_spans.extend(spans)
                cell_details.append({"source": cell["source"], "translation": cell["translation"],
                                     "source_rect": list(box), "output_rect": list(destination),
                                     "painted_rect": list(painted),
                                     "source_size": size, "output_size": size,
                                     "reason": mode, "retained_source_spans": [
                                         {"text": s["text"], "rect": list(s["bbox"]), "size": s["size"]}
                                         for s in retained]})
        if reason:
            while len(overlays) > start:
                overlays.delete_page(-1)
            issues.append({"block_id": block["id"], "kind": "table", "message": reason,
                           "cell_source": cell["source"]})
            continue
        style = {"spans": changed_spans, "lines": lines,
                 "size": max(cell["size"] for cell, _ in changed), "bold": False}
        structure = []
        translated_index = 0
        for cell, mode in mapped:
            unchanged = _normalized(cell["source"]) == _normalized(cell["translation"])
            layout = None if unchanged else cell_details[translated_index]
            translated_index += not unchanged
            structure.append({"kind": "table_cell", "source": list(cell["rect"]),
                              "rect": list(cell["rect"]) if unchanged else layout["output_rect"],
                              "painted_rect": list(cell["rect"]) if unchanged else layout["painted_rect"],
                              "source_text": cell["source"], "text": cell["translation"],
                              "source_size": cell["size"], "output_size": cell["size"],
                              "status": "source_glyphs" if unchanged else "translated", "reason": mode,
                              "retained_source_spans": [] if unchanged else layout["retained_source_spans"]})
        result = {"overlay": composite_index, "rect": list(overlay_region), "clip": list(overlay_region),
                  "scale": 1, "anchored": True, "font_reason": "table-source-size", "structure": structure}
        prepared.append(({**block, "_fixed_structure": True}, style, result))
        handled.add(block["id"])
        details.append({"blocks": block.get("_members", [block["id"]]), "cells": len(mapped),
                        "translated_cells": len(changed), "source_glyph_cells": len(mapped) - len(changed),
                        "complete": True, "cell_layouts": cell_details})
    return prepared, handled, issues, details
