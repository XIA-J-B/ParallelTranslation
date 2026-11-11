"""Replace proven diagram labels without moving or painting over artwork.

All geometry is in the unrotated source page.  Independent labels are mapped
line by line; only a compact, aligned multi-line label may reflow as one unit.
The final glyphs are checked against the actual remaining page pixels, rather
than the (often very large) bounding rectangles of chart paths and font frames.
"""
import html
import math
import re
import unicodedata
from collections import Counter

import pymupdf


def normalized(value):
    return ''.join(unicodedata.normalize('NFKC', value or '').split())


def _text(line):
    return ''.join(span.get('text', '') for span in line.get('spans', ())).strip()


def _union(boxes):
    result = pymupdf.Rect(boxes[0])
    for box in boxes[1:]:
        result |= pymupdf.Rect(box)
    return result


def _lines(native, rect):
    result = []
    for block in native:
        for line in block.get('lines', ()):
            box = pymupdf.Rect(line['bbox'])
            if _text(line) and (rect + (-.03, -.03, .03, .03)).contains((box.tl + box.br) * .5):
                result.append(line)
    return result


def is_figure_label_candidate(page, block, rect, native, figures=(), drawings=()):
    """Recognize an axis title just outside the conservative artwork band.

    This deliberately does not admit arbitrary short prose near an image.
    Unit-bearing axes and count labels also occur between vertically stacked
    plots, where a caption-based band may stop at the neighbouring chart.
    """
    value = ' '.join((block.get('text') or '').split())
    if not (re.match(r'^#\s*\w', value) or
            re.search(r'\([A-Za-z°µμ%/²³0-9 .^−-]{1,16}\)\s*$', value)):
        return False
    if len(value) > 70 or len(value.split()) > 9 or re.search(r'[=;!?。；]', value):
        return False
    lines = _lines(native, rect)
    if not lines or len(lines) > 2:
        return False
    size = max((span.get('size', 0) for line in lines for span in line['spans']), default=0)
    art = [pymupdf.Rect(box) for box in figures]
    art += [pymupdf.Rect(item['rect']) for item in drawings
            if item.get('rect') is not None and pymupdf.Rect(item['rect']).width > size * 4
            and pymupdf.Rect(item['rect']).height > size * 2]
    for box in art:
        if (min(rect.x1, box.x1) - max(rect.x0, box.x0) > min(rect.width, box.width) * .5
                and max(rect.y0 - box.y1, box.y0 - rect.y1, 0) < size * 2):
            return True
    return False


def _frame(line):
    dx, dy = line.get('dir', (1, 0))
    angle = round(math.degrees(math.atan2(-dy, dx))) % 360
    if min(abs(angle - candidate) for candidate in (0, 90, 180, 270, 360)) > 1:
        return None
    angle = (round(angle / 90) * 90) % 360
    return {0: (1, 0), 90: (0, -1), 180: (-1, 0), 270: (0, 1)}[angle], angle


def _local_point(point, direction):
    dx, dy = direction
    x, y = point
    return pymupdf.Point(x * dx + y * dy, -x * dy + y * dx)


def _world_box(box, direction):
    dx, dy = direction
    points = [pymupdf.Point(p.x * dx - p.y * dy, p.x * dy + p.y * dx)
              for p in (box.tl, box.tr, box.bl, box.br)]
    return pymupdf.Rect(min(p.x for p in points), min(p.y for p in points),
                        max(p.x for p in points), max(p.y for p in points))


def _local_box(box, direction):
    points = [_local_point(p, direction) for p in (box.tl, box.tr, box.bl, box.br)]
    return pymupdf.Rect(min(p.x for p in points), min(p.y for p in points),
                        max(p.x for p in points), max(p.y for p in points))


def _redactions(lines):
    """Thin strips through each run, oriented along the original baseline."""
    boxes = []
    for line in lines:
        frame = _frame(line)
        if not frame:
            return []
        direction, _ = frame
        for span in line['spans']:
            if not span.get('text', '').strip():
                continue
            box = _local_box(pymupdf.Rect(span['bbox']), direction)
            center = (box.y0 + box.y1) * .5
            strip = pymupdf.Rect(box.x0 + min(.03, box.width * .05), center - .3,
                                 box.x1 - min(.03, box.width * .05), center + .3)
            boxes.append(_world_box(strip, direction))
    return boxes


def _cohesive(lines):
    """Several source lines belong to one label, never to separate nodes."""
    if not 2 <= len(lines) <= 4:
        return False
    frames = [_frame(line) for line in lines]
    if not all(frames) or any(frame != frames[0] for frame in frames):
        return False
    direction, _ = frames[0]
    boxes = [_local_box(pymupdf.Rect(line['bbox']), direction) for line in lines]
    sizes = [max(s['size'] for s in line['spans'] if s.get('text', '').strip()) for line in lines]
    if max(sizes) - min(sizes) > .1:
        return False
    size = max(sizes)
    centers = [(box.x0 + box.x1) * .5 for box in boxes]
    if max(centers) - min(centers) > size * .5:
        return False
    baselines = [_local_point(line['spans'][0]['origin'], direction).y for line in lines]
    return all(size * .65 < b - a < size * 1.65 for a, b in zip(baselines, baselines[1:]))


def _crop_bitmap(bitmap, region, scale):
    """Crop *pixels* after a complete render, never clip the PDF interpreter.

    Some PDF font/resources combinations omit text in a clipped render even
    though the full page paints correctly.  Safety checks must see the same
    marks as the reader, including source ticks and adjacent small labels.
    """
    area = (pymupdf.Rect(region) * pymupdf.Matrix(scale, scale)).irect & bitmap.irect
    cropped = pymupdf.Pixmap(pymupdf.csRGB, area, bool(bitmap.alpha))
    cropped.copy(bitmap, area)
    return cropped


def _full_bitmap(page, scale=4, alpha=False):
    return page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csRGB, alpha=alpha)


def _pixel_clear(background, overlay, region, scale=4, raster_label=None,
                 base_bitmap=None, ink_bitmap=None):
    """Check actual painted ink, allowing a uniform coloured panel background."""
    region = region & background.rect
    if region.is_empty:
        return False
    base = _crop_bitmap(base_bitmap or _full_bitmap(background, scale), region, scale)
    ink = _crop_bitmap(ink_bitmap or _full_bitmap(overlay, scale, True), region, scale)
    if (base.width, base.height) != (ink.width, ink.height):
        return False
    raw, rgba = base.samples, ink.samples
    if raster_label is not None:
        # Some producers place real PDF text over a photographic panel.  Keep
        # the new painted footprint inside the original label, and reject
        # strong local edges (raster curves, borders or adjacent lettering).
        # Smooth illumination/colour variation is not a chart obstruction.
        bounds = pymupdf.Rect(raster_label) + (-.3, -.3, .3, .3)
        for index in range(base.width * base.height):
            if rgba[index * 4 + 3] < 80:
                continue
            x, y = index % base.width, index // base.width
            if not bounds.contains(pymupdf.Point((base.x + x + .5) / scale,
                                                 (base.y + y + .5) / scale)):
                return False
            color = raw[index * 3:index * 3 + 3]
            for row, col in ((y, x - scale), (y, x + scale), (y - scale, x), (y + scale, x)):
                if 0 <= row < base.height and 0 <= col < base.width:
                    offset = (row * base.width + col) * 3
                    if max(abs(color[channel] - raw[offset + channel]) for channel in range(3)) > 75:
                        return False
        return True
    # The mode is a background colour, not a guessed white rectangle.  Keep
    # 8-bit colour values; PDF panel fills render exactly away from their edges.
    counts = Counter(zip(raw[0::3], raw[1::3], raw[2::3]))
    color, amount = counts.most_common(1)[0]
    if amount < base.width * base.height * .35:
        return False  # textured/raster artwork cannot be safely replaced here
    foreground = set()
    for index in range(base.width * base.height):
        offset = index * 3
        # Light chart grids and arrows are still artwork.  Only tiny raster
        # rounding differences from the uniform panel colour count as empty;
        # a high contrast threshold would silently discard pale grey strokes.
        if max(abs(raw[offset + channel] - color[channel]) for channel in range(3)) > 8:
            foreground.add(index)
    # A quarter-point clearance includes solid ink, thin plot strokes and
    # foreign text without treating font ascender padding as visible marks.
    width, height = base.width, base.height
    for index in range(width * height):
        if rgba[index * 4 + 3] < 80:
            continue
        x, y = index % width, index // width
        for row in range(max(0, y - 1), min(height, y + 2)):
            for col in range(max(0, x - 1), min(width, x + 2)):
                if row * width + col in foreground:
                    return False
    return True


def _painted_box(page, region, background=None, scale=4, bitmap=None, background_bitmap=None):
    """Measure visible glyph pixels, excluding font ascent/descent padding."""
    region = region & page.rect
    pix = _crop_bitmap(bitmap or _full_bitmap(page, scale, background is None), region, scale)
    data = pix.samples
    other = (_crop_bitmap(background_bitmap or _full_bitmap(background, scale), region, scale).samples
             if background is not None else None)
    left, top, right, bottom = pix.width, pix.height, -1, -1
    for index in range(pix.width * pix.height):
        painted = (data[index * 4 + 3] >= 32 if other is None else
                   max(abs(data[index * 3 + channel] - other[index * 3 + channel])
                       for channel in range(3)) >= 32)
        if painted:
            x, y = index % pix.width, index // pix.width
            left, top, right, bottom = min(left, x), min(top, y), max(right, x), max(bottom, y)
    if right < 0:
        return None
    return [(pix.x + left) / scale, (pix.y + top) / scale,
            (pix.x + right + 1) / scale, (pix.y + bottom + 1) / scale]


def _overlay_clear(previous, current, region, scale=4, old_bitmap=None, new_bitmap=None):
    """Transparent glyph masks also detect white lettering on dark panels."""
    old = _crop_bitmap(old_bitmap or _full_bitmap(previous, scale, True), region, scale)
    new = _crop_bitmap(new_bitmap or _full_bitmap(current, scale, True), region, scale)
    if (old.width, old.height) != (new.width, new.height):
        return False
    first, second = old.samples, new.samples
    for index in range(new.width * new.height):
        if second[index * 4 + 3] < 80:
            continue
        x, y = index % new.width, index // new.width
        for row in range(max(0, y - 1), min(new.height, y + 2)):
            for col in range(max(0, x - 1), min(new.width, x + 2)):
                if first[(row * new.width + col) * 4 + 3] >= 80:
                    return False
    return True


def prepare_figure_label(overlays, page, block, rect, native, typography, *, links=(),
                         occupied=()):
    """Return ``(overlay, owned_style, reason)``; never mutate the source page.

    A successful unchanged label returns ``(None, None, '')``.  The caller can
    count it as reviewed original glyphs instead of an unresolved translation.
    Changed groups commit atomically; their custom redaction strips must be
    used by the caller, including for vertical labels.
    """
    failure = '图内标签无法可靠逐项对应或在原位保持字号，保留该组完整原文'
    if normalized(block.get('text')) == normalized(block.get('translation')):
        return None, None, ''
    lines = _lines(native, rect)
    if not lines or normalized(''.join(_text(line) for line in lines)) != normalized(block.get('text')):
        return None, None, failure + '（源文字与标签锚点不一致）'
    if any(_frame(line) is None for line in lines):
        return None, None, failure + '（非直角旋转标签）'
    translated = [part.strip() for part in block['translation'].splitlines() if part.strip()]
    if len(translated) == len(lines):
        groups = [([line], value) for line, value in zip(lines, translated)
                  if normalized(_text(line)) != normalized(value)]
    elif len(translated) == 1 and _cohesive(lines):
        groups = [(lines, translated[0])]
    else:
        return None, None, failure + '（独立标签与译文数量不匹配）'
    owned_lines = [line for group, _ in groups for line in group]
    spans = [span for line in owned_lines for span in line['spans'] if span.get('text', '').strip()]
    if any(span.get('flags', 0) & 1 or re.search(r'math|symbol|cmmi|cmsy|cmex', span.get('font', ''), re.I)
           for span in spans):
        return None, None, failure + '（改变数学或上下标标签需要逐字对应）'
    erase = _redactions(owned_lines)
    if any((box & pymupdf.Rect(link['rect'])).get_area() > .1 for box in erase for link in links):
        return None, None, failure + '（标签内链接需保留）'
    if not erase:
        return None, None, failure
    # One source-page copy per changed label group, cropped only when raster
    # checking.  No graphics are removed and no opaque white fill is painted.
    with pymupdf.open() as background, pymupdf.open() as candidates:
        background.insert_pdf(page.parent, from_page=page.number, to_page=page.number)
        clean = background[0]
        clean.set_rotation(0)
        expected = Counter(normalized(page.get_text()))
        expected.subtract(Counter(normalized(''.join(span['text'] for span in spans))))
        for box in erase:
            clean.add_redact_annot(box, fill=False, cross_out=False)
        clean.apply_redactions(images=0, graphics=0, text=0)
        if +expected != Counter(normalized(clean.get_text())):
            return None, None, failure + '（擦除会影响相邻文字）'
        source_bitmap = _full_bitmap(page)
        clean_bitmap = _full_bitmap(clean)
        occupied_bitmaps = {}
        candidates.new_page(width=page.rect.width, height=page.rect.height)
        structure = []
        for group, value in groups:
            combined_bitmap = _full_bitmap(candidates[0], alpha=True)
            direction, angle = _frame(group[0])
            source = _union([line['bbox'] for line in group])
            box = _local_box(source, direction)
            source_spans = [span for line in group for span in line['spans'] if span.get('text', '').strip()]
            size = max(span['size'] for span in source_spans)
            if max(span['size'] for span in source_spans) - min(span['size'] for span in source_spans) > .15:
                return None, None, failure + '（同一标签含无法可靠重建的字号层级）'
            bold = sum(len(s['text']) for s in source_spans if s.get('flags', 0) & 16) > sum(len(s['text']) for s in source_spans) * .75
            italic = all(s.get('flags', 0) & 2 for s in source_spans)
            baseline = _local_point(source_spans[0]['origin'], direction).y
            css = typography['css'] + (f'*{{margin:0;padding:0}}body{{font-family:{typography["family"]};'
                  f'font-size:{size}pt;line-height:1.1;text-align:center;'
                  f'font-weight:{600 if bold else 400};font-style:{"italic" if italic else "normal"};'
                  f'color:#{source_spans[0]["color"]:06x}' + '}')
            found = None
            compact = value.translate(str.maketrans({'、': ',', '，': ',', '：': ':', '；': ';',
                                                     '（': '(', '）': ')'}))
            compact = re.sub(r'…{2,}', '…', compact)
            variants = list(dict.fromkeys((value, compact)))
            raster_label = source if any((pymupdf.Rect(item['bbox']) & source).get_area() >= source.get_area() * .95
                                          for item in page.get_image_info()) else None
            for value, grow in [(variant, grow) for variant in variants for grow in (0, .5, 1, 1.5, 2)]:
                width = box.width + size * grow * 2
                with pymupdf.open() as scratch:
                    probe = scratch.new_page(width=max(300, width + 40), height=max(200, box.height + size * 6))
                    fit = pymupdf.Rect(10, 10, 10 + width, 10 + box.height + size * 2)
                    spare, _ = probe.insert_htmlbox(fit, html.escape(value), css=css,
                                                    archive=typography['archive'], scale_low=1)
                    output = [line for item in probe.get_text('dict')['blocks'] if item['type'] == 0 for line in item['lines']]
                    if (spare < 0 or not output or len(output) > len(group)
                            or normalized(probe.get_text()) != normalized(value)):
                        continue
                    actual = _union([line['bbox'] for line in output])
                    first_baseline = output[0]['spans'][0]['origin'][1]
                    local = actual + ((box.x0 + box.x1 - actual.x0 - actual.x1) * .5,
                                      baseline - first_baseline,
                                      (box.x0 + box.x1 - actual.x0 - actual.x1) * .5,
                                      baseline - first_baseline)
                    destination = _world_box(local, direction)
                    if not page.rect.contains(destination):
                        continue
                    trial = candidates.new_page(width=page.rect.width, height=page.rect.height)
                    trial.show_pdf_page(destination, scratch, 0, clip=actual, rotate=angle)
                    region = (destination + (-1.5, -1.5, 1.5, 1.5)) & page.rect
                    trial_bitmap = _full_bitmap(trial, alpha=True)
                    clear = _pixel_clear(clean, trial, region, raster_label=raster_label,
                                         base_bitmap=clean_bitmap, ink_bitmap=trial_bitmap)
                    clear = clear and _overlay_clear(candidates[0], trial, region,
                                                      old_bitmap=combined_bitmap, new_bitmap=trial_bitmap)
                    if clear:
                        for prior in occupied:
                            if 'overlay' not in prior or not prior.get('structure'):
                                continue
                            if (pymupdf.Rect(prior['rect']) & region).get_area() > 0:
                                if prior['overlay'] not in occupied_bitmaps:
                                    occupied_bitmaps[prior['overlay']] = _full_bitmap(overlays[prior['overlay']], alpha=True)
                                if prior.get('rect') != prior.get('clip') or not _overlay_clear(
                                        overlays[prior['overlay']], trial, region,
                                        old_bitmap=occupied_bitmaps[prior['overlay']], new_bitmap=trial_bitmap):
                                    clear = False
                                    break
                    if clear:
                        # Freeze a standalone copy before the next Story call
                        # can invalidate MuPDF's document graft map.
                        found = True
                        painted = _painted_box(trial, destination + (-.5, -.5, .5, .5), bitmap=trial_bitmap)
                        source_painted = _painted_box(page, source, clean, bitmap=source_bitmap,
                                                      background_bitmap=clean_bitmap)
                        with pymupdf.open(stream=candidates.tobytes(), filetype='pdf') as frozen:
                            candidates[0].show_pdf_page(page.rect, frozen, len(frozen) - 1)
                        structure.append({'kind': 'figure_label', 'source': list(source),
                                          'rect': list(destination), 'text': value,
                                          'painted_rect': painted or list(destination),
                                          'source_painted_rect': source_painted or list(source),
                                          'source_size': size, 'output_size': size})
                        candidates.delete_page(len(candidates) - 1)
                        break
                    candidates.delete_page(len(candidates) - 1)
            if found is None:
                return None, None, failure + '（原字号下会碰到相邻文字或图形墨迹）'
        if not structure:
            return None, None, ''
        index = len(overlays)
        out = overlays.new_page(width=page.rect.width, height=page.rect.height)
        with pymupdf.open(stream=candidates.tobytes(), filetype='pdf') as frozen:
            out.show_pdf_page(page.rect, frozen, 0)
        region = _union([part['rect'] for part in structure])
        style = {'spans': spans, 'lines': owned_lines,
                 'size': max(s['size'] for s in spans), 'bold': False}
        result = {'overlay': index, 'rect': list(region), 'clip': list(region), 'scale': 1,
                  'anchored': True, 'structure': structure,
                  'redaction_boxes': [list(box) for box in erase]}
        return result, style, ''
