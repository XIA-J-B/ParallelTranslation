"""New extraction versions must not reinterpret or invalidate old citations."""
import hashlib
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf
from fastapi import HTTPException

import app as service
import reading_text
import pdf_unicode
from reading_text import CitationRequest, resolve_citation, text_layer
from pdf_selection import page_selection


class EncodingCitationCompatibilityTests(unittest.TestCase):
    def setUp(self):
        reading_text._cache.clear()

    def tearDown(self):
        reading_text._cache.clear()

    @staticmethod
    def pdf_bytes(rotation=0, phrase='Original words to quote.'):
        with pymupdf.open() as pdf:
            page = pdf.new_page(width=520, height=720)
            page.insert_text((55, 85), phrase, fontsize=12)
            page.insert_text((290, 135), 'A second column remains selectable.', fontsize=9)
            page.set_cropbox(pymupdf.Rect(15, 20, 505, 700))
            page.set_rotation(rotation)
            return pdf.tobytes()

    @staticmethod
    def request(layer, revision=None):
        run = next(run for run in layer['runs'] if 'words' in run['text'])
        begin = run['text'].index('words')
        return CitationRequest(page=1, view='translation' if revision else 'source',
            revision=revision, text_version=layer['version'],
            ranges=[dict(run_id=run['id'], start=begin, end=begin + len('words'))])

    def test_current_layer_exposes_exact_legacy_digest_and_old_quote_identity(self):
        for rotation in (0, 90, 180, 270):
            with self.subTest(rotation=rotation), tempfile.TemporaryDirectory() as directory, \
                    patch.object(service, 'DATA', Path(directory)):
                doc_id, _ = service.extract_document(self.pdf_bytes(rotation), 'layout.pdf')
                folder = Path(directory) / doc_id
                original_data = (folder / 'document.json').read_bytes()
                original_pdf = (folder / 'source.pdf').read_bytes()
                cache = folder / 'layout'
                cache.mkdir(exist_ok=True)
                revision = 'c' * 24
                (cache / (revision + '.pdf')).write_bytes(original_pdf)
                for selected_revision in (None, revision):
                    legacy = text_layer(service, doc_id, 1, selected_revision, version=1)
                    current = text_layer(service, doc_id, 1, selected_revision)
                    self.assertNotEqual(current['version'], legacy['version'])
                    self.assertEqual(current['legacy_version'], legacy['version'])
                    old_request = self.request(legacy, selected_revision)
                    # Freeze the old text layer as the pre-upgrade baseline.
                    with patch.object(reading_text, 'text_layer', return_value=legacy):
                        expected = resolve_citation(service, doc_id, old_request)
                    actual = resolve_citation(service, doc_id, old_request)
                    self.assertEqual(actual, expected)
                    self.assertEqual(actual['text'], 'words')
                    self.assertEqual(actual['source']['text_version'], legacy['version'])
                    fresh = resolve_citation(service, doc_id, self.request(current, selected_revision))
                    self.assertEqual(fresh['text'], 'words')
                self.assertEqual((folder / 'document.json').read_bytes(), original_data)
                self.assertEqual((folder / 'source.pdf').read_bytes(), original_pdf)
                self.assertEqual((cache / (revision + '.pdf')).read_bytes(), original_pdf)

    def test_forged_legacy_version_and_invalid_old_ranges_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(service, 'DATA', Path(directory)):
            doc_id, _ = service.extract_document(self.pdf_bytes(), 'generic.pdf')
            legacy = text_layer(service, doc_id, 1, version=1)
            request = self.request(legacy)
            forged = request.model_copy(update={'text_version': 'f' * 64})
            with self.assertRaises(HTTPException) as error:
                resolve_citation(service, doc_id, forged)
            self.assertEqual(error.exception.status_code, 409)
            broken = request.model_copy(deep=True)
            broken.ranges[0].end = 100000
            with self.assertRaises(HTTPException) as error:
                resolve_citation(service, doc_id, broken)
            self.assertEqual(error.exception.status_code, 422)

    def test_a_changed_pdf_cannot_reuse_its_prior_legacy_version(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(service, 'DATA', Path(directory)):
            doc_id, _ = service.extract_document(self.pdf_bytes(), 'generic.pdf')
            folder = Path(directory) / doc_id
            legacy = text_layer(service, doc_id, 1, version=1)
            request = self.request(legacy)
            before = hashlib.sha256((folder / 'source.pdf').read_bytes()).hexdigest()
            (folder / 'source.pdf').write_bytes(self.pdf_bytes(phrase='Changed words must not inherit a quote.'))
            self.assertNotEqual(hashlib.sha256((folder / 'source.pdf').read_bytes()).hexdigest(), before)
            with self.assertRaises(HTTPException) as error:
                resolve_citation(service, doc_id, request)
            self.assertEqual(error.exception.status_code, 409)

    def test_multi_codepoint_glyphs_and_supplementary_unicode_use_scalar_offsets(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(service, 'DATA', Path(directory)):
            doc_id, _ = service.extract_document(self.pdf_bytes(phrase='X Y Z'), 'unicode.pdf')
            folder = Path(directory) / doc_id
            original = (folder / 'source.pdf').read_bytes()
            native_get_text = pymupdf.Page.get_text

            def shaped_text(page, option='text', *args, **kwargs):
                data = native_get_text(page, option, *args, **kwargs)
                if option == 'rawdict':
                    data = copy.deepcopy(data)
                    chars = data['blocks'][0]['lines'][0]['spans'][0]['chars']
                    chars[0]['c'] = 'ffi'
                    chars[2]['c'] = '\U0001d45b'
                return data

            with patch.object(pymupdf.Page, 'get_text', shaped_text):
                layer = text_layer(service, doc_id, 1)
                run = next(run for run in layer['runs'] if run['text'].startswith('ffi'))
                self.assertEqual(run['text'], 'ffi \U0001d45b Z')
                self.assertEqual(len(run['boxes']), len(run['text']))
                self.assertEqual(run['boxes'][0], run['boxes'][1])
                self.assertEqual(run['boxes'][1], run['boxes'][2])
                glyphs = [glyph for row in layer['lines'] for glyph in row
                          if len(glyph) > 10 and glyph[9] == run['id']]
                self.assertEqual([(g[0], g[10]) for g in glyphs],
                                 [('ffi', 0), (' ', 3), ('\U0001d45b', 4), (' ', 5), ('Z', 6)])
                for start, end, expected in [(1, 3, 'fi'), (4, 5, '\U0001d45b')]:
                    request = CitationRequest(page=1, text_version=layer['version'],
                        ranges=[dict(run_id=run['id'], start=start, end=end)])
                    quote = resolve_citation(service, doc_id, request)
                    self.assertEqual(quote['text'], expected)
                    self.assertEqual(len(quote['source']['rects']), 1)
            self.assertEqual((folder / 'source.pdf').read_bytes(), original)

    def test_unknown_glyph_is_isolated_without_losing_readable_neighbours(self):
        self.assert_unknown_glyph('\x12')

    def test_real_embedded_math_recovery_keeps_old_tail_run_citations(self):
        from test_pdf_unicode import build_encoded_pdf
        for rotation in (0, 90, 180, 270):
            with self.subTest(rotation=rotation), tempfile.TemporaryDirectory() as directory, \
                    patch.object(service, 'DATA', Path(directory)):
                with pymupdf.open(stream=build_encoded_pdf(b'\x10X\x11', rotation=rotation), filetype='pdf') as pdf:
                    pdf[0].insert_text((20, 105), 'Tail words remain exact.', fontsize=10)
                    original = pdf.tobytes()
                doc_id, _ = service.extract_document(original, 'math.pdf')
                folder = Path(directory) / doc_id
                legacy = text_layer(service, doc_id, 1, version=1)
                current = text_layer(service, doc_id, 1)
                self.assertTrue(current['encoding_fixes'])
                self.assertFalse(current['encoding_issues'])
                self.assertFalse(current['warnings'])
                math = next(run for run in current['runs'] if run['text'] == '(\u2211)')
                self.assertNotEqual(legacy['runs'][0]['id'],
                    next(run for run in current['runs'] if 'Tail words' in run['text'])['id'])
                old_request = self.request(legacy)
                self.assertEqual(resolve_citation(service, doc_id, old_request)['text'], 'words')
                math_request = CitationRequest(page=1, text_version=current['version'],
                    ranges=[dict(run_id=math['id'], start=0, end=3)])
                self.assertEqual(resolve_citation(service, doc_id, math_request)['text'], '(\u2211)')
                with pymupdf.open(folder / 'source.pdf') as pdf:
                    plain = page_selection(pdf[0])
                self.assertEqual(''.join(g[0] for g in plain['lines'][0]), '(\u2211)')
                self.assertEqual((folder / 'source.pdf').read_bytes(), original)

    def test_painted_tab_newline_and_c1_controls_are_not_silently_copied(self):
        for damaged in ('\t', '\n', '\x85'):
            with self.subTest(damaged=repr(damaged)):
                self.assert_unknown_glyph(damaged)

    def assert_unknown_glyph(self, damaged):
        with tempfile.TemporaryDirectory() as directory, patch.object(service, 'DATA', Path(directory)):
            doc_id, _ = service.extract_document(self.pdf_bytes(phrase='AB?CD'), 'partial.pdf')
            folder = Path(directory) / doc_id
            original = (folder / 'source.pdf').read_bytes()
            native_get_text = pymupdf.Page.get_text

            def partly_unknown(page, option='text', *args, **kwargs):
                data = native_get_text(page, option, *args, **kwargs)
                if option == 'rawdict':
                    data = copy.deepcopy(data)
                    data['blocks'][0]['lines'][0]['spans'][0]['chars'][2]['c'] = damaged
                return data

            # Deliberately deny font recovery: this verifies the integration's
            # fail-closed path independently of the font decoder's own tests.
            decoder = lambda page, native: (
                native, {'fixes': [], 'unresolved': [{'reason': 'ambiguous embedded glyph'}]})
            with patch.object(pymupdf.Page, 'get_text', partly_unknown), \
                    patch.object(pdf_unicode, 'recover_page_text', decoder):
                layer = text_layer(service, doc_id, 1)
                self.assertIn('AB', [run['text'] for run in layer['runs']])
                self.assertIn('CD', [run['text'] for run in layer['runs']])
                self.assertTrue(layer['warnings'])
                first_line = layer['lines'][0]
                self.assertEqual(''.join(g[0] for g in first_line), 'AB\ufffdCD')
                self.assertEqual(len(first_line[2]), 9, 'Unknown glyph must have no citation run')
                with pymupdf.open(folder / 'source.pdf') as pdf:
                    plain = page_selection(pdf[0])
                self.assertEqual(''.join(g[0] for g in plain['lines'][0]), 'AB\ufffdCD')
                for run in layer['runs']:
                    if run['text'] not in {'AB', 'CD'}:
                        continue
                    request = CitationRequest(page=1, text_version=layer['version'],
                        ranges=[dict(run_id=run['id'], start=0, end=len(run['text']))])
                    self.assertEqual(resolve_citation(service, doc_id, request)['text'], run['text'])
                legacy = text_layer(service, doc_id, 1, version=1)
                old_tail = next(run for run in legacy['runs'] if 'column' in run['text'])
                new_tail = next(run for run in layer['runs'] if 'column' in run['text'])
                self.assertNotEqual(old_tail['id'], new_tail['id'])
                request = CitationRequest(page=1, text_version=legacy['version'],
                    ranges=[dict(run_id=old_tail['id'], start=0, end=len(old_tail['text']))])
                quote = resolve_citation(service, doc_id, request)
                self.assertEqual(quote['text'], old_tail['text'])
                self.assertEqual(quote['source']['text_version'], legacy['version'])
            self.assertEqual((folder / 'source.pdf').read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
