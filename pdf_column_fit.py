"""Recover source-size prose inside bounded column segments.

Only a segment with an unresolved body is considered. Figures and unknown ink
stay fixed; known code panels and complete formulas can travel as source crops.
The planner commits the whole segment or leaves every existing result intact.
"""
import re

import pymupdf

from pdf_flow import caption, column_lanes, lane_options, overlap, text_ink_bounds


MIN_GAP_FACTOR = .88
MIN_INK_GAP = 2.0
_MONO = re.compile(r"mono|nimbusmon|courier|cour|consol|menlo|cmtt|typewriter|code", re.I)
_COMMAND = re.compile(r"^\s*(?:\$\s+|>>>\s+|(?:python[\d.]*|pip[\d.]*|conda|npm|node|bash|sh|cd)\s+)")


def _span_text(spans):
    return "".join(span.get("text", "") for span in spans)


def _owned_spans(spans, box):
    return [span for span in spans
            if box.contains((pymupdf.Rect(span["bbox"]).tl + pymupdf.Rect(span["bbox"]).br) * .5)]


def _code_units(page, overlays, working, native, drawings, source_rects, prepared, glyph_bounds):
    """Copy unchanged monospaced command panels with their complete gray fill."""
    spans = [span for item in native for line in item["lines"] for span in line["spans"]
             if span.get("text", "").strip()]
    occupied = {key for block, _, _ in prepared for key in block.get("_members", [block["id"]])}
    occupied_spans = {id(span) for _, style, _ in prepared for span in style["spans"]}
    plates = []
    for drawing in drawings:
        fill = drawing.get("fill")
        items = drawing.get("items", ())
        if (drawing.get("type") != "f" or not fill or max(fill) - min(fill) > .03
                or not .75 <= min(fill) < 1 or not items
                or any(item[0] != "re" for item in items)):
            continue
        box = pymupdf.Rect(drawing["rect"])
        if box.width >= 50 and 2 <= box.height <= 35:
            plates.append(box)
    groups = []
    for plate in sorted(plates, key=lambda box: (box.x0, box.y0)):
        group = next((group for group in groups
                      if abs(group[0].x0 - plate.x0) < 1 and abs(group[0].x1 - plate.x1) < 1
                      and abs(group[-1].y1 - plate.y0) < 1), None)
        if group is None:
            groups.append([plate])
        else:
            group.append(plate)
    protected = [pymupdf.Rect(link["from"]) for link in page.get_links()]
    protected += [pymupdf.Rect(annot.rect) for annot in page.annots() or ()]
    images = [pymupdf.Rect(image["bbox"]) for image in page.get_image_info()]
    units, snapshot = [], None
    for plates in groups:
        panel = pymupdf.Rect(plates[0])
        for plate in plates[1:]:
            panel |= plate
        members = [block for block in working if block["id"] not in occupied
                   and block.get("translation", "").strip() == block.get("text", "").strip()
                   and block["id"] in source_rects
                   and overlap(source_rects[block["id"]], panel) >= source_rects[block["id"]].get_area() * .5]
        if not members:
            continue
        members.sort(key=lambda block: (source_rects[block["id"]].y0, source_rects[block["id"]].x0))
        if not _COMMAND.match(members[0]["text"]):
            continue
        region = pymupdf.Rect(panel)
        for member in members:
            region |= source_rects[member["id"]]
        owned = _owned_spans(spans, region)
        if any(id(span) in occupied_spans for span in owned):
            continue  # A translated comment or label already owns this ink.
        count = sum(len(span["text"].strip()) for span in owned)
        mono = sum(len(span["text"].strip()) for span in owned
                   if _MONO.search(span.get("font", "")) or span.get("flags", 0) & 8)
        if not count or mono < count * .95:
            continue
        ink = glyph_bounds(owned)
        if ink is None:
            continue
        ink = pymupdf.Rect(ink) | panel
        crop = (ink + (-.2, -.2, .2, .2)) & page.rect
        owned_ids = {id(span) for span in owned}
        if (any(overlap(crop, box) > .1 for box in protected + images)
                or any(overlap(crop, pymupdf.Rect(span["bbox"])) > .1
                       for span in spans if id(span) not in owned_ids)):
            continue
        carried = [tuple(plate) for plate in plates]
        if any(overlap(crop, pymupdf.Rect(drawing["rect"]) + (-.2, -.2, .2, .2)) > .1
               and tuple(drawing["rect"]) not in carried for drawing in drawings):
            continue
        if snapshot is None:
            snapshot = len(overlays)
            overlays.insert_pdf(page.parent, from_page=page.number, to_page=page.number, links=False, annots=False)
        block = {**members[0], "text": "\n".join(member["text"] for member in members),
                 "_members": [key for member in members for key in member.get("_members", [member["id"]])],
                 "_code_unit": True}
        size = max(span["size"] for span in owned)
        style = {"spans": owned, "lines": [], "size": size, "ink_bounds": list(ink)}
        result = {"overlay": snapshot, "rect": list(crop), "clip": list(crop), "scale": 1,
                  "original": True, "carried_graphics": carried,
                  "ink_insets": [ink.y0 - crop.y0, crop.y1 - ink.y1]}
        units.append((block, style, result))
    return units


def _visible_bounds(overlays, result):
    clip = pymupdf.Rect(result["clip"])
    insets = result.get("ink_insets")
    if insets is not None:
        return pymupdf.Rect(clip.x0, clip.y0 + insets[0], clip.x1, clip.y1 - insets[1])
    page = overlays[result["overlay"]]
    ink = text_ink_bounds(page.get_bboxlog(), clip)
    for image in page.get_image_info():
        box = pymupdf.Rect(image["bbox"])
        if overlap(box, clip) > .1:
            ink = box if ink is None else ink | box
    return ink


def _smallest_body(overlays, page, item, source, typography, render, maximum):
    block, style, old = item
    low, high = 1.0, min(maximum, page.rect.height - source.y0 - .5)
    best = None
    # Restrict each trial to its offered height. The usual local expansion
    # would otherwise hide how much column space the paragraph actually needs.
    for step in range(10):
        height = high if step == 0 else (low + high) / 2
        box = pymupdf.Rect(source.x0, source.y0, source.x1, source.y0 + height)
        barrier = pymupdf.Rect(box.x0, box.y1 + .1, box.x1, box.y1 + 5)
        mark = len(overlays)
        result = render(overlays, page, block, box, dict(style), [barrier],
                        {**typography, "compact_fallback": True}, horizontal_obstacles=[], allow_shrink=False)
        ink = _visible_bounds(overlays, result) if result else None
        if (result is None or ink is None or result.get("scale", 1) < .999
                or result["rect"][3] - result["rect"][1] > height + .05
                or result["rect"][0] < source.x0 - .5 or result["rect"][2] > source.x1 + .5):
            while len(overlays) > mark:
                overlays.delete_page(-1)
            if step == 0:
                return None
            low = height
        else:
            for field in ("inline_math_runs", "carried_graphics", "formula_cluster_rects", "identifier_strokes", "whole_links"):
                if field in old:
                    result[field] = old[field]
            # A tight visible crop avoids font metric padding consuming the
            # real inter-paragraph gap; bboxlog already includes antialiasing.
            result["clip"] = [source.x0, ink.y0 - .2, source.x1, ink.y1 + .2]
            result["rect"] = list(result["clip"])
            result["ink_insets"] = [.2, .2]
            result.pop("_fill_render", None)
            result.update(scale=1, font_reason="column-source-size")
            best = result, ink.height
            high = height
        if high - low < .2:
            break
    return best


def recover_source_columns(page, overlays, prepared, working, native, drawings, source_rects, typography,
                           *, render, body_candidate, glyph_bounds):
    """Mutate only fully validated segments; return flow and newly moved code."""
    if not any(body_candidate(block, style) and (result.get("pending") or result.get("scale", 1) < .999)
               for block, style, result in prepared):
        return [], []
    start = len(overlays)
    codes = _code_units(page, overlays, working, native, drawings, source_rects, prepared, glyph_bounds)
    def movable_body(item):
        block, style, result = item
        return (body_candidate(block, style) or
                (style.get("_mixed_heading") and any(part.get("kind") == "body"
                                                     for part in result.get("structure", ()))))

    candidates = [item for item in prepared
                  if not item[0].get("_fixed_structure") and not caption(item[0])
                  and (movable_body(item) or item[0].get("_formula"))] + codes
    candidate_ids = {id(item[0]) for item in candidates}
    owned = {id(span) for _, style, _ in candidates for span in style["spans"]}
    carried = {tuple(box) for _, _, result in candidates for box in result.get("carried_graphics", ())}
    fixed = [pymupdf.Rect(span["bbox"]) for item in native for line in item["lines"]
             for span in line["spans"] if span.get("text", "").strip() and id(span) not in owned]
    fixed += [pymupdf.Rect(drawing["rect"]) + (-.2, -.2, .2, .2) for drawing in drawings
              if tuple(drawing["rect"]) not in carried]
    fixed += [pymupdf.Rect(image["bbox"]) for image in page.get_image_info()]
    fixed += [pymupdf.Rect(result["rect"]) for block, _, result in prepared if id(block) not in candidate_ids]
    body_texts = {block["text"] for block, style, _ in prepared if body_candidate(block, style)}
    lanes = column_lanes(prepared, source_rects, page.rect.width, lambda text: text in body_texts)
    local_rects = {**source_rects, **{block["id"]: pymupdf.Rect(result["clip"]) for block, _, result in codes}}
    grouped = {}
    for item in candidates:
        block, style, result = item
        box = local_rects[block["id"]]
        choices = lane_options(box, lanes, allowance=8)
        if not choices:
            continue
        lane = min(choices, key=lambda choice: choice[1])[0]
        ink = glyph_bounds(style["spans"])
        if ink is None:
            continue
        ink = pymupdf.Rect(ink)
        for carried_box in result.get("carried_graphics", ()):
            ink |= pymupdf.Rect(carried_box)
        if any(overlap(ink, obstacle) > .1 for obstacle in fixed):
            continue
        grouped.setdefault(lane, []).append((item, ink))
    adjustments, added = [], []
    for lane, items in grouped.items():
        items.sort(key=lambda item: item[1].y0)
        segments, segment = [], []
        for item in items:
            if segment:
                prior = segment[-1]
                gap = item[1].y0 - prior[1].y1
                between = pymupdf.Rect(lanes[lane][0], prior[1].y1, lanes[lane][1], item[1].y0)
                if (gap < -.1 or gap > max(24, item[0][1]["size"] * 3)
                        or any(overlap(between, obstacle) > .1 for obstacle in fixed)):
                    segments.append(segment)
                    segment = []
            segment.append(item)
        if segment:
            segments.append(segment)
        for segment in segments:
            if (len(segment) < 2 or not any(item[2].get("pending") or item[2].get("scale", 1) < .999
                                           for item, _ in segment)):
                continue
            segment_ids = {id(item[0]) for item, _ in segment}
            segment_fixed = fixed + [pymupdf.Rect(local_rects[item[0]["id"]]) for item in candidates
                                     if id(item[0]) not in segment_ids]
            mark = len(overlays)
            staged = []
            top, bottom = segment[0][1].y0, segment[-1][1].y1
            for item, ink in segment:
                block, style, old = item
                if old.get("original"):
                    clip = pymupdf.Rect(old["clip"])
                    tight = (ink + (-.2, -.2, .2, .2)) & clip
                    result = {**old, "clip": list(tight), "rect": list(tight),
                              "ink_insets": [ink.y0 - tight.y0, tight.y1 - ink.y1]}
                    fit = result, ink.height
                else:
                    fit = _smallest_body(overlays, page, item, local_rects[block["id"]], typography,
                                         render, bottom - top)
                if fit is None:
                    break
                staged.append((item, ink, *fit))
            if len(staged) != len(segment):
                while len(overlays) > mark:
                    overlays.delete_page(-1)
                continue
            gaps = [staged[index][1].y0 - staged[index - 1][1].y1 for index in range(1, len(staged))]
            height = sum(item[3] for item in staged)
            total = lambda factor: height + sum(max(MIN_INK_GAP, gap * factor) for gap in gaps)
            if top + total(MIN_GAP_FACTOR) > bottom + .01:
                while len(overlays) > mark:
                    overlays.delete_page(-1)
                continue
            factor = 1.0
            if top + total(1) > bottom:
                low, high = MIN_GAP_FACTOR, 1.0
                for _ in range(20):
                    middle = (low + high) / 2
                    if top + total(middle) <= bottom - .1:
                        low = middle
                    else:
                        high = middle
                factor = low
            cursor, placed = top, []
            for index, (item, ink, result, height) in enumerate(staged):
                if index:
                    cursor += max(MIN_INK_GAP, gaps[index - 1] * factor)
                clip = pymupdf.Rect(result["clip"])
                offset = cursor - (clip.y0 + result["ink_insets"][0])
                result["rect"] = list(clip + (0, offset, 0, offset))
                visible = pymupdf.Rect(clip.x0, cursor, clip.x1, cursor + height)
                if any(overlap(visible, obstacle) > .1 for obstacle in segment_fixed):
                    break
                placed.append((item, ink, result, height))
                cursor += height
            if len(placed) != len(staged):
                while len(overlays) > mark:
                    overlays.delete_page(-1)
                continue
            for index, (item, ink, result, height) in enumerate(placed):
                block, style, old = item
                block["_fixed_structure"] = True
                block["_column_recovered"] = True
                style["ink_bounds"] = list(ink)
                old.clear()
                old.update(result)
                if block.get("_code_unit"):
                    prepared.append(item)
                    added.append(item)
                    source_rects[block["id"]] = pymupdf.Rect(result["clip"])
                if index:
                    prior = placed[index - 1][0]
                    adjustments.append({"blocks": block.get("_members", [block["id"]]),
                        "previous": prior[0].get("_members", [prior[0]["id"]]),
                        "previous_bottom": prior[2]["rect"][3],
                        "source_gap": local_rects[block["id"]].y0 - local_rects[prior[0]["id"]].y1,
                        "gap": result["rect"][1] - prior[2]["rect"][3],
                        "source_ink_gap": gaps[index - 1], "gap_factor": factor,
                        "ink_padding": prior[2]["ink_insets"][1] + result["ink_insets"][0],
                        "actual_ink_gap": max(MIN_INK_GAP, gaps[index - 1] * factor),
                        "spacing_reason": "bounded-column-source-size", "shift": result["rect"][1] - local_rects[block["id"]].y0})
    if not adjustments:
        while len(overlays) > start:
            overlays.delete_page(-1)
    return adjustments, added
