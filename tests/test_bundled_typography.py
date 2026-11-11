"""The shipped Chinese face must be reproducible and retain searchable glyphs."""
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fontTools.ttLib import TTFont

import pdf_typography as typography


class BundledTypographyTests(unittest.TestCase):
    def test_pinned_font_and_license_match_their_manifest(self):
        folder = typography.BUNDLED_FONT.parent
        manifest = json.loads((folder / 'UPSTREAM.json').read_text(encoding='utf-8'))
        for name, item in manifest['files'].items():
            data = (folder / name).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), item['sha256'])
        self.assertIn('SIL OPEN FONT LICENSE', (folder / 'OFL.txt').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as absent_system:
            with patch.dict('os.environ', WINDIR=absent_system):
                self.assertEqual(Path(typography.font_source.__wrapped__()[0]), typography.BUNDLED_FONT)

    def test_regular_semibold_and_oblique_keep_chinese_and_latin_metrics(self):
        text = '论文翻译一致性Ab12'
        source = str(typography.BUNDLED_FONT)
        regular, semibold = typography.subset_fonts(text, source, source)
        for data, weight in ((regular, 400), (semibold, 600)):
            with TTFont(io.BytesIO(data)) as upright, TTFont(io.BytesIO(typography.oblique_font(data))) as italic:
                self.assertEqual(upright['OS/2'].usWeightClass, weight)
                self.assertEqual(italic['OS/2'].usWeightClass, weight)
                self.assertEqual(bool(upright['OS/2'].fsSelection & 32), weight == 600)
                self.assertEqual(bool(upright['head'].macStyle & 1), weight == 600)
                self.assertEqual(upright['name'].getDebugName(17), 'Regular' if weight == 400 else 'SemiBold')
                self.assertEqual(italic['name'].getDebugName(17), 'Italic' if weight == 400 else 'SemiBold Italic')
                self.assertNotIn('fvar', upright)
                for char in text:
                    glyph = upright.getBestCmap()[ord(char)]
                    self.assertEqual(italic.getBestCmap()[ord(char)], glyph)
                    self.assertEqual(upright['hmtx'][glyph][0], italic['hmtx'][glyph][0])

    def test_font_identity_is_content_based_and_includes_weights(self):
        with tempfile.TemporaryDirectory() as folder:
            first = Path(folder) / 'first.ttf'
            second = Path(folder) / 'second.ttf'
            data = typography.BUNDLED_FONT.read_bytes()
            first.write_bytes(data)
            second.write_bytes(data)
            with patch.object(typography, 'font_source', return_value=(str(first), str(first), 'font')):
                signature = typography.font_signature()
            with patch.object(typography, 'font_source', return_value=(str(second), str(second), 'font')):
                self.assertEqual(signature, typography.font_signature())
            self.assertEqual([entry['weight'] for entry in signature['fonts']], [400, 600])
            self.assertEqual(signature['derivative_version'], typography.FONT_CACHE_VERSION)


if __name__ == '__main__':
    unittest.main()
