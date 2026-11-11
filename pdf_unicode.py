"""Recover searchable Unicode from embedded glyph identities, without editing PDFs.

PDFs may paint correct glyphs while omitting a ToUnicode map. In that case
character codes (including C0 controls or an ASCII X used for a summation) are
not text. Recovery requires an exact positioned text-trace glyph and an
unambiguous embedded-font glyph name or Unicode cmap. Unknowns stay unknown.
"""
import copy
import hashlib
import io
import re
import threading
import unicodedata
from collections import OrderedDict, defaultdict

from fontTools import agl
from fontTools.cffLib import CFFFontSet
from fontTools.misc import psLib
from fontTools.ttLib import TTFont


_FONT_CACHE = OrderedDict()
_FONT_LOCK = threading.RLock()
_FONT_CACHE_LIMIT = 32
_PROGRAM_LIMIT = 32 * 1024 * 1024
_SUBSET = re.compile(r"^[A-Z]{6}\+")
_MATH_VARIANT = re.compile(r"(?:Bigg|bigg|Big|big|display|text)$")
# Adobe legacy names describe pieces of extensible delimiters. Use their
# standardized Unicode components rather than legacy private-use values.
_COMPONENTS = {
    'parenlefttp': '\u239b', 'parenleftex': '\u239c', 'parenleftbt': '\u239d',
    'parenrighttp': '\u239e', 'parenrightex': '\u239f', 'parenrightbt': '\u23a0',
    'bracketlefttp': '\u23a1', 'bracketleftex': '\u23a2', 'bracketleftbt': '\u23a3',
    'bracketrighttp': '\u23a4', 'bracketrightex': '\u23a5', 'bracketrightbt': '\u23a6',
    'bracelefttp': '\u23a7', 'braceleftmid': '\u23a8', 'braceleftbt': '\u23a9',
    'braceex': '\u23aa', 'bracerighttp': '\u23ab', 'bracerightmid': '\u23ac',
    'bracerightbt': '\u23ad', 'integralex': '\u23ae',
}


def invalid_text(value):
    """A painted C0/C1 control is not a usable character in a PDF text span."""
    return not value or any(c == '\ufffd' or unicodedata.category(c) in {'Cc', 'Cs', 'Co'} for c in value)


def _safe_unicode(value):
    return bool(value) and not invalid_text(value) and not any(unicodedata.category(c) == 'Co' for c in value)


def glyph_unicode(name):
    """Interpret conventional glyph names; never infer a symbol from a font name."""
    if not isinstance(name, str) or name in {'.notdef', '.null', 'nonmarkingreturn'}:
        return None, False
    # Stylistic suffixes do not change the semantic glyph, as specified by AGL.
    name = name.split('.', 1)[0]
    if name in _COMPONENTS:
        return _COMPONENTS[name], True
    value = agl.toUnicode(name)
    if _safe_unicode(value):
        return value, False
    match = _MATH_VARIANT.search(name)
    if match:
        base = name[:match.start()]
        value = agl.toUnicode(base)
        # Size variants are safe only for named mathematical operators and
        # delimiters, never arbitrary suffix-bearing text glyphs.
        if (_safe_unicode(value) and len(value) == 1
                and (unicodedata.category(value) == 'Sm' or value in '()[]{}|')):
            return value, True
    return None, False


def _font_program(data, extension):
    """Read embedded font data only; parsing failure is a conservative fallback."""
    if not data or len(data) > _PROGRAM_LIMIT:
        return None
    key = (hashlib.sha256(data).digest(), extension)
    with _FONT_LOCK:
        if key in _FONT_CACHE:
            _FONT_CACHE.move_to_end(key)
            return _FONT_CACHE[key]
    try:
        cmap, names = {}, set()
        if extension in {'pfa', 'pfb'}:
            # extract_font's Type1 programs can omit the PFA eexec trailer.
            # suckfont reads the bounded program directly, without executing a
            # system PostScript interpreter or accessing external files.
            parsed = psLib.suckfont(data, 'ascii')
            names.add(str(parsed.get('FontName', '')))
            names.update(str(parsed.get('FontInfo', {}).get(field, '')) for field in ('FullName', 'FamilyName'))
            order = list(parsed['CharStrings'])
            if '.notdef' in order and order[0] != '.notdef':
                index = order.index('.notdef')
                order[0], order[index] = order[index], order[0]
        elif extension == 'cff':
            cff = CFFFontSet()
            cff.decompile(io.BytesIO(data), None)
            if len(cff.fontNames) != 1:
                return None
            order = list(cff[cff.fontNames[0]].charset)
            names.add(str(cff.fontNames[0]))
        else:
            with TTFont(io.BytesIO(data), lazy=False) as font:
                order = font.getGlyphOrder()
                if 'name' in font:
                    for record in font['name'].names:
                        if record.nameID in {1, 4, 6, 16}:
                            try:
                                names.add(record.toUnicode())
                            except (UnicodeError, LookupError):
                                pass
                reverse = defaultdict(set)
                for table in font['cmap'].tables if 'cmap' in font else ():
                    if table.isUnicode():
                        for codepoint, glyph in table.cmap.items():
                            value = chr(codepoint)
                            if _safe_unicode(value):
                                reverse[glyph].add(value)
                cmap = {name: next(iter(values)) for name, values in reverse.items() if len(values) == 1}
        result = (tuple(order), cmap, tuple(sorted(names - {''})))
    except Exception:
        result = None
    with _FONT_LOCK:
        _FONT_CACHE[key] = result
        _FONT_CACHE.move_to_end(key)
        while len(_FONT_CACHE) > _FONT_CACHE_LIMIT:
            _FONT_CACHE.popitem(last=False)
    return result


def _font_name(name):
    return _SUBSET.sub('', name or '').replace(' ', '')


def _page_fonts(page, wanted):
    fonts = defaultdict(list)
    resources = []
    for item in page.get_fonts(full=True):
        xref, extension, _, base, *_ = item
        if not xref:
            continue
        try:
            explicit = page.parent.xref_get_key(xref, 'ToUnicode')[0] != 'null'
            resource = (xref, extension, explicit)
            fonts[_font_name(base)].append(resource)
            resources.append(resource)
        except (RuntimeError, ValueError, TypeError):
            continue
    # PDF /BaseFont and a renderer's font name can differ legitimately. Use
    # names stored in the embedded font itself, never heuristic suffix removal.
    missing = set(wanted) - set(fonts)
    if missing:
        for resource in resources:
            try:
                extracted = page.parent.extract_font(resource[0])
                program = _font_program(extracted[3], extracted[1] or resource[1])
                if program:
                    for name in {_font_name(name) for name in program[2]} & missing:
                        if resource not in fonts[name]:
                            fonts[name].append(resource)
            except (RuntimeError, ValueError, TypeError):
                continue
    return fonts


def _trace_characters(page):
    indexed = defaultdict(list)
    for span in page.get_texttrace():
        if span.get('type') == 3 or span.get('opacity', 1) <= 0:
            continue
        for _, glyph_id, origin, _ in span['chars']:
            name = _font_name(span['font'])
            key = (name, round(origin[0], 2), round(origin[1], 2))
            indexed[key].append((glyph_id, span['size'], tuple(span['dir'])))
    return indexed


def _positioned_glyph(index, font, span, line, char):
    x, y = char.get('origin', (float('inf'), float('inf')))
    matches = set()
    # Two neighbouring quantization buckets allow sub-centipoint arithmetic
    # changes through nested PDF forms while retaining a strict position match.
    for dx in (-.01, 0, .01):
        for dy in (-.01, 0, .01):
            for gid, size, direction in index.get((font, round(x + dx, 2), round(y + dy, 2)), ()):
                if (abs(size - span.get('size', 0)) <= max(.03, size * .005)
                        and all(abs(a-b) <= .005 for a,b in zip(direction, line.get('dir', (1,0))))):
                    matches.add(gid)
    return next(iter(matches)) if len(matches) == 1 else None


def recover_page_text(page, native=None):
    """Return ``(rawdict copy, diagnostics)`` with original glyph geometry.

    Callers must share this returned object between visible selection and
    citation extraction so span identity and character offsets agree.
    """
    if native is None:
        import pymupdf
        native = page.get_text('rawdict', flags=pymupdf.TEXTFLAGS_RAWDICT & ~pymupdf.TEXT_PRESERVE_IMAGES)
    repaired = copy.deepcopy(native)
    diagnostics = {'fixes': [], 'unresolved': []}
    wanted = {_font_name(span.get('font', '')) for block in repaired['blocks']
              for line in block.get('lines', ()) for span in line.get('spans', ())}
    fonts, trace = _page_fonts(page, wanted), None
    programs = {}
    for block in repaired['blocks']:
        for line in block.get('lines', ()):
            for span in line.get('spans', ()):
                font = _font_name(span.get('font', ''))
                resources = fonts.get(font, ())
                # Parse each positioned font resource once. Its actual embedded
                # glyph names distinguish a math size variant from an ordinary
                # CJK/Latin character without a font-family-name heuristic.
                for char in span.get('chars', ()):
                    before = char.get('c', '')
                    candidates = []
                    gid = None
                    if resources:
                        if trace is None:
                            trace = _trace_characters(page)
                        gid = _positioned_glyph(trace, font, span, line, char)
                    if gid is not None:
                        for xref, extension, explicit in resources:
                            if xref not in programs:
                                try:
                                    extracted = page.parent.extract_font(xref)
                                    programs[xref] = _font_program(extracted[3], extracted[1] or extension)
                                except (RuntimeError, ValueError, TypeError):
                                    programs[xref] = None
                            program = programs[xref]
                            if program is None or not 0 <= gid < len(program[0]):
                                candidates.append(None)
                                continue
                            name = program[0][gid]
                            value, math_variant = glyph_unicode(name)
                            method = 'embedded-glyph-name'
                            if value is None:
                                value = program[1].get(name)
                                method = 'embedded-unicode-cmap'
                            # A valid explicit Unicode mapping remains the
                            # authority except for semantically named math
                            # size variants, which encode the actual operator.
                            if not invalid_text(before) and explicit and not math_variant:
                                value = before
                            candidates.append((value, name, method) if value else None)
                    values = {item[0] for item in candidates if item is not None}
                    certain = candidates and None not in candidates and len(values) == 1
                    after = next(iter(values)) if certain else None
                    if after and after != before:
                        # Keep equivalent already valid ligature/style forms;
                        # this is repair, not a wholesale text normalization.
                        if not invalid_text(before) and unicodedata.normalize('NFKC', before) == unicodedata.normalize('NFKC', after):
                            continue
                        char['c'] = after
                        item = candidates[0]
                        diagnostics['fixes'].append(dict(page=page.number+1, bbox=list(char['bbox']),
                            before=before, after=after, font=span.get('font'), glyph_id=gid,
                            glyph_name=item[1], method=item[2]))
                    elif invalid_text(before):
                        diagnostics['unresolved'].append(dict(page=page.number+1, bbox=list(char['bbox']),
                            before=before, after=None, font=span.get('font'), glyph_id=gid,
                            glyph_name=None, method='unresolved-glyph-identity'))
    return repaired, diagnostics
