"""Keep vector underscores attached to their original monospaced identifier.

Some publishers draw an underscore as a short rule between two text objects.
Extraction then exposes a synthetic space. These helpers return display-only
corrections and whole-glyph runs; callers must successfully place every run
before removing the owned rules from the source page.
"""
import re
from statistics import median

import pymupdf


_MONO = re.compile(r"mono|monl|courier|typewriter|cmtt", re.I)
_CHAR = re.compile(r"[A-Za-z0-9_-]")
_BOUNDARY = r"A-Za-z0-9_.:/+\-"
_MAPPING_REASON = "源等宽标识符的矢量下划线无法唯一对应译文，保留完整原文"


def _text(span):
    return span.get("text", "") or "".join(char.get("c", "") for char in span.get("chars", []))


def _owned(span, spans):
    box = pymupdf.Rect(span["bbox"])
    return any(span.get("font") == own.get("font")
               and abs(span.get("size", 0) - own.get("size", 0)) < .05
               and all(abs(a - b) < .05 for a, b in zip(box, own["bbox"]))
               for own in spans if _text(own).strip())


def _same_face(chars):
    first = chars[0]
    size = first["size"]
    return (size > 0 and all(char["font"] == first["font"]
            and abs(char["size"] - size) <= .02 * size
            and abs(char["origin"][1] - first["origin"][1]) <= .08 * size
            for char in chars))


def _mono_cell(chars):
    widths = [pymupdf.Rect(char["bbox"]).width for char in chars]
    cell = median(widths)
    if cell <= 0 or max(widths) - min(widths) > max(.08, cell * .04):
        return None
    # PDF font flags are sometimes wrong; a named fixed-width face or several
    # distinct glyphs with equal advances supplies independent font evidence.
    known = any(char.get("flags", 0) & 8 or _MONO.search(char["font"]) for char in chars)
    if not known and len({char["c"] for char in chars}) < 4:
        return None
    return cell


def _matching_rule(drawing, gap, chars, cell):
    if (drawing.get("type") != "s" or len(drawing.get("items", [])) != 1
            or drawing["items"][0][0] != "l"
            or drawing.get("dashes", "[] 0") not in ("[] 0", "[] 0.0")
            or drawing.get("stroke_opacity", 1) < .99):
        return False
    _, first, last = drawing["items"][0]
    first, last = pymupdf.Point(first), pymupdf.Point(last)
    size, baseline = chars[0]["size"], chars[0]["origin"][1]
    width = float(drawing.get("width", 0))
    x0, x1 = sorted((first.x, last.x))
    if (abs(first.y - last.y) > max(.05, size * .01)
            or not 0 < width <= max(.5, size * .1)
            or not .2 * cell <= x1 - x0 <= 1.1 * cell
            or not baseline - .1 * size <= first.y <= baseline + .25 * size
            or x0 < gap.x0 - .03 * size or x1 > gap.x1 + .03 * size
            or x1 - x0 < gap.width * .5):
        return False
    color = drawing.get("color")
    ink = chars[0].get("color", 0)
    expected = ((ink >> 16 & 255) / 255, (ink >> 8 & 255) / 255, (ink & 255) / 255)
    return color is not None and all(abs(a - b) < .02 for a, b in zip(color, expected))


def _line_runs(line, spans, drawings):
    if line.get("wmode", 0) or tuple(line.get("dir", (1, 0))) != (1, 0):
        return []
    chars = []
    for span in line.get("spans", []):
        own = _owned(span, spans)
        chars.extend({**char, "size": span["size"], "font": span["font"],
                      "flags": span.get("flags", 0), "color": span.get("color", 0),
                      "synthetic": char.get("synthetic", bool(span.get("char_flags", 0) & 512)),
                      "owned": own} for char in span.get("chars", []))
    joins = []
    for index, gap_char in enumerate(chars):
        if not gap_char.get("synthetic") or not gap_char.get("c", "").isspace():
            continue
        left, right = index - 1, index + 1
        while left >= 0 and chars[left]["owned"] and _CHAR.fullmatch(chars[left]["c"]):
            left -= 1
        while right < len(chars) and chars[right]["owned"] and _CHAR.fullmatch(chars[right]["c"]):
            right += 1
        first, end = left + 1, right
        if index - first < 2 or end - index - 1 < 2:
            continue
        letters = chars[first:index] + chars[index + 1:end]
        if not _same_face(letters):
            continue
        cell = _mono_cell(letters)
        gap = pymupdf.Rect(gap_char["bbox"])
        if cell is None or not .2 * cell <= gap.width <= 1.1 * cell:
            continue
        if (abs(pymupdf.Rect(chars[index - 1]["bbox"]).x1 - gap.x0) > .05
                or abs(pymupdf.Rect(chars[index + 1]["bbox"]).x0 - gap.x1) > .05):
            continue
        rules = [drawing for drawing in drawings if _matching_rule(drawing, gap, letters, cell)]
        if len(rules) == 1:
            joins.append(dict(first=first, end=end, gaps=[index], drawings=rules))
    groups = []
    for join in joins:
        if groups and join["first"] < groups[-1]["end"]:
            groups[-1]["end"] = max(groups[-1]["end"], join["end"])
            groups[-1]["gaps"] += join["gaps"]
            groups[-1]["drawings"] += join["drawings"]
        else:
            groups.append(join)
    result = []
    for group in groups:
        selected = chars[group["first"]:group["end"]]
        text = "".join("_" if index in group["gaps"] else chars[index]["c"]
                       for index in range(group["first"], group["end"]))
        box = pymupdf.Rect(selected[0]["bbox"])
        for char in selected[1:]:
            box |= pymupdf.Rect(char["bbox"])
        result.append(dict(text=text, normalized=text.replace("_", ""), rect=box,
                           chars=selected, primary=True, drawings=group["drawings"]))
    return result


def prepare_vector_identifiers(page, block, style, drawings, raw_native=None):
    """Return whole-identifier runs, owned rules and display-only text.

    `runs` use the inline-math asset contract. Pass only returned `drawings`
    when building those assets so no unrelated short rule is copied. If any
    run fails asset creation or layout, preserve the complete source block;
    returned strokes are not permission to erase it before that preflight.
    """
    translation = block.get("translation") or ""
    result = dict(translation=translation, runs=[], owned_strokes=[], drawings=[], identifiers=[])
    if not style or not drawings:
        return result
    raw = raw_native() if callable(raw_native) else raw_native
    if raw is None:
        raw = page.get_text("rawdict", flags=pymupdf.TEXTFLAGS_RAWDICT & ~pymupdf.TEXT_PRESERVE_IMAGES)
    native = raw.get("blocks", []) if isinstance(raw, dict) else raw
    runs = [run for item in native for line in item.get("lines", [])
            for run in _line_runs(line, style.get("spans", []), drawings)]
    replacements, by_name = [], {}
    for run in runs:
        by_name.setdefault(run["text"], []).append(run)
    for name, occurrences in by_name.items():
        # Repeated identifiers are common in prose. Equal source/translation
        # counts and the same glyph style give an unambiguous ordered mapping.
        faces = {tuple((char["c"], char["font"], round(char["size"], 2), char["color"])
                       for char in run["chars"] if char["c"].strip()) for run in occurrences}
        pattern = (rf"(?<![{_BOUNDARY}])" + r"(?:\s*_\s*|\s+)".join(
            re.escape(part) for part in name.split("_")) + rf"(?![{_BOUNDARY}])")
        matches = list(re.finditer(pattern, translation))
        if len(faces) != 1 or len(matches) != len(occurrences):
            return {**result, "reason": _MAPPING_REASON}
        for match in matches:
            if any(match.start() < end and match.end() > start for start, end, _ in replacements):
                return {**result, "reason": _MAPPING_REASON}
            replacements.append((match.start(), match.end(), name))
    for start, end, name in sorted(replacements, reverse=True):
        translation = translation[:start] + name + translation[end:]
    owned = [drawing for run in runs for drawing in run.pop("drawings")]
    return dict(translation=translation, runs=runs,
                owned_strokes=list(dict.fromkeys(tuple(drawing["rect"]) for drawing in owned)),
                drawings=owned, identifiers=[run["text"] for run in runs])
