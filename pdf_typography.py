"""Local, embedded book typography; subset before instancing variable fonts."""
import hashlib
import io
import json
import math
import os
import re
import shutil
import tempfile
from functools import lru_cache
from pathlib import Path

import pymupdf

FONT_CACHE_VERSION = 3
FONT_CACHE_LIMIT = 48
BUNDLED_FONT = Path(__file__).resolve().parent / "static" / "fonts" / "noto-serif-sc" / "NotoSerifSC-VF.ttf"
FONT_WEIGHTS = (400, 600)


def space_cjk_latin(text):
    """Display Latin terms next to Han text with one space; keep stored text intact.

    Only touching boundaries change. Existing whitespace, punctuation, numeric
    labels, URLs, email addresses and inline code retain their original spelling.
    """
    han = r"[\u3400-\u9fff\uf900-\ufaff\U00020000-\U000323af]"
    latin = r"[A-Za-z\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u024f]"
    term = rf"[0-9]*{latin}[A-Za-z0-9\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u024f]*(?:[-_][A-Za-z0-9]+)*"
    protected = re.compile(r"(`[^`\n]*`|https?://[^\s<>]+|www\.[^\s<>]+|[\w.+-]+@[\w.-]+)")
    parts = protected.split(text)
    for index in range(0, len(parts), 2):
        value = re.sub(rf"({han})(?={term})", r"\1 ", parts[index])
        parts[index] = re.sub(rf"({term})(?={han})", r"\1 ", value)
    return "".join(parts)


@lru_cache(maxsize=1)
def font_source():
    # A checked-in, licensed font makes the same document look the same on a
    # fresh installation. System fonts remain a recovery path for older copies.
    if BUNDLED_FONT.is_file():
        return str(BUNDLED_FONT), str(BUNDLED_FONT), "思源宋体（Noto Serif SC）"
    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for regular, bold, label in [
        (fonts / "NotoSerifSC-VF.ttf", fonts / "NotoSerifSC-VF.ttf", "思源宋体（Noto Serif SC）"),
        (fonts / "Deng.ttf", fonts / "Dengb.ttf", "等线"),
    ]:
        if regular.is_file() and bold.is_file():
            return str(regular), str(bold), label
    return None


@lru_cache(maxsize=8)
def _font_fingerprint(path, size, mtime_ns):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def font_signature():
    source = font_source()
    if source is None:
        return "builtin-serif"
    fonts = []
    for path, weight in zip(source[:2], FONT_WEIGHTS):
        stat = Path(path).stat()
        fonts.append({"sha256": _font_fingerprint(path, stat.st_size, stat.st_mtime_ns),
                      "weight": weight})
    return {"fonts": fonts, "oblique_degrees": 12, "derivative_version": FONT_CACHE_VERSION}


def _name_face(font, style):
    # Variable fonts can retain a typographic subfamily such as ExtraLight
    # after instancing. MuPDF prefers it over the legacy style name, so keep
    # every family/style record in agreement with the generated outlines.
    values = {1: "ParallelBook", 2: style, 4: "ParallelBook " + style,
              6: "ParallelBook-" + style.replace(" ", ""),
              16: "ParallelBook", 17: style, 21: "ParallelBook", 22: style}
    font['name'].names = [record for record in font['name'].names if record.nameID not in values]
    for identifier, value in values.items():
        font['name'].setName(value, identifier, 3, 1, 0x409)
        font['name'].setName(value, identifier, 1, 0, 0)


@lru_cache(maxsize=8)
def subset_fonts(characters, regular, bold):
    from fontTools import subset
    from fontTools.ttLib import TTFont
    from fontTools.varLib.instancer import instantiateVariableFont

    results = []
    for path, weight in zip((regular, bold), FONT_WEIGHTS):
        font = TTFont(path, fontNumber=0)
        options = subset.Options()
        options.recalc_timestamp = False
        # Contextual digit/dash ligatures in this font lose their original
        # Unicode mapping in MuPDF. Keep glyphs individually searchable.
        options.layout_features = []
        worker = subset.Subsetter(options=options)
        worker.populate(text=characters)
        worker.subset(font)
        if "fvar" in font:
            instantiateVariableFont(font, {"wght": weight}, inplace=True)
        # Give the embedded derivative its own family; the glyphs use real
        # regular/semibold masters rather than the variable font's thin default.
        _name_face(font, "Regular" if weight == 400 else "SemiBold")
        font["OS/2"].usWeightClass = weight
        font['OS/2'].fsSelection = (font['OS/2'].fsSelection & ~(1 | 32 | 64)) | (64 if weight == 400 else 32)
        font['head'].macStyle = (font['head'].macStyle & ~3) | (0 if weight == 400 else 1)
        output = io.BytesIO()
        font.save(output)
        font.close()
        results.append(output.getvalue())
    return tuple(results)


@lru_cache(maxsize=12)
def oblique_font(data):
    """Embed real slanted outlines when the CJK family has no italic master.

    MuPDF does not reliably synthesize italic for an embedded upright face.
    Preserve its family, weight, advances and Unicode map; shear outlines only.
    """
    from fontTools.ttLib import TTFont
    from fontTools.pens.recordingPen import DecomposingRecordingPen
    from fontTools.pens.transformPen import TransformPen
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    with TTFont(io.BytesIO(data)) as font:
        slant = math.tan(math.radians(12))
        glyphs = font.getGlyphSet()
        transformed = {}
        for name in font.getGlyphOrder():
            recording = DecomposingRecordingPen(glyphs)
            glyphs[name].draw(recording)
            pen = TTGlyphPen(None)
            recording.replay(TransformPen(pen, (1, 0, slant, 1, 0, 0)))
            transformed[name] = pen.glyph()
        font['glyf'].glyphs.update(transformed)
        for name, glyph in transformed.items():
            glyph.recalcBounds(font['glyf'])
            advance, _ = font['hmtx'][name]
            font['hmtx'][name] = (advance, getattr(glyph, 'xMin', 0))
        font['post'].italicAngle = -12
        font['head'].macStyle |= 2
        font['OS/2'].fsSelection = (font['OS/2'].fsSelection | 1) & ~64
        font['hhea'].caretSlopeRise = 1000
        font['hhea'].caretSlopeRun = round(slant * 1000)
        style = 'Italic' if font['OS/2'].usWeightClass == 400 else 'SemiBold Italic'
        _name_face(font, style)
        output = io.BytesIO()
        font.save(output)
        return output.getvalue()


def _font_cache_root():
    return Path(tempfile.gettempdir()) / "parallel-translation-font-cache"


def _read_font_cache(key):
    folder = _font_cache_root() / key
    try:
        data = (
            (folder / "regular.ttf").read_bytes(),
            (folder / "semibold.ttf").read_bytes(),
            (folder / "italic.ttf").read_bytes(),
            (folder / "semibold-italic.ttf").read_bytes(),
            json.loads((folder / "meta.json").read_text(encoding="utf-8"))["fallback"],
        )
        return data if all(data[:4]) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _write_font_cache(key, regular, semibold, italic, semibold_italic, fallback):
    root = _font_cache_root()
    folder = root / key
    try:
        folder.mkdir(parents=True, exist_ok=True)
        for name, data in (("regular.ttf", regular), ("semibold.ttf", semibold),
                           ("italic.ttf", italic), ("semibold-italic.ttf", semibold_italic)):
            temp = folder / (name + ".tmp")
            temp.write_bytes(data)
            temp.replace(folder / name)
        (folder / "meta.json").write_text(json.dumps({"fallback": fallback}), encoding="utf-8")
        entries = [entry for entry in root.iterdir() if entry.is_dir()]
        if len(entries) > FONT_CACHE_LIMIT:
            entries.sort(key=lambda entry: entry.stat().st_mtime_ns)
            for entry in entries[:-FONT_CACHE_LIMIT]:
                shutil.rmtree(entry, ignore_errors=True)
    except OSError:
        pass


def font_resources(text):
    source = font_source()
    if source is None:
        return {"css": "", "family": "serif", "archive": None, "label": "内置宋体回退"}
    # Include the compatibility forms used by pdf_layout and ordinary labels.
    import unicodedata
    characters = "".join(sorted(set(text + unicodedata.normalize("NFKC", text)
                                    + "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 .,:;()[]-")))
    key = hashlib.sha256(
        f"{FONT_CACHE_VERSION}|{font_signature()}|{characters}".encode("utf-8")).hexdigest()[:40]
    cached = _read_font_cache(key)
    try:
        if cached is not None:
            regular, semibold, italic, semibold_italic, fallback_characters = cached
        else:
            regular, semibold = subset_fonts(characters, source[0], source[1])
            from fontTools.ttLib import TTFont
            with TTFont(io.BytesIO(regular)) as embedded:
                supported = embedded.getBestCmap()
                fallback_characters = "".join(char for char in characters
                                              if not char.isspace() and ord(char) not in supported)
            italic = oblique_font(regular)
            semibold_italic = oblique_font(semibold)
            _write_font_cache(key, regular, semibold, italic, semibold_italic, fallback_characters)
    except (ImportError, OSError, ValueError, KeyError):
        return {"css": "", "family": "serif", "archive": None, "label": "内置宋体回退"}
    archive = pymupdf.Archive()
    archive.add((regular, "parallel-regular.ttf"))
    archive.add((semibold, "parallel-semibold.ttf"))
    archive.add((italic, "parallel-italic.ttf"))
    archive.add((semibold_italic, "parallel-semibold-italic.ttf"))
    css = ("@font-face{font-family:ParallelBook;src:url(parallel-regular.ttf);font-weight:400;}"
           "@font-face{font-family:ParallelBook;src:url(parallel-semibold.ttf);font-weight:600;}"
           "@font-face{font-family:ParallelBook;src:url(parallel-italic.ttf);font-weight:400;font-style:italic;}"
           "@font-face{font-family:ParallelBook;src:url(parallel-semibold-italic.ttf);font-weight:600;font-style:italic;}")
    return {"css": css, "family": "ParallelBook,serif", "archive": archive, "label": source[2],
            "fallback_characters": fallback_characters}
