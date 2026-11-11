"""Saved fragment references must remain complete, identifiable and source-sized."""
import copy
import re
import tempfile
import unittest
from pathlib import Path

import pymupdf

from pdf_references import (reconstruct_legacy_bibliography, prepare_legacy_bibliography,
                            normalize_document, prepare_bibliography, format_translation)
from pdf_typography import font_resources
from pdf_layout import build_layout


TARGET = '简体中文'


def fixture(size=8, rotation=0, columns=1, width=480, height=640, quoted_book=False, reference_url='', styled_publication=False):
    pdf = pymupdf.open()
    page = pdf.new_page(width=width, height=height)
    x = width * .53 if columns == 2 else 42
    page.insert_text((x + 30, 50), 'REFERENCES', fontsize=size + 2)
    step = size * 1.35
    y = 80
    rows = []
    def row(text, *, italic_tail=None):
        nonlocal y
        if italic_tail is None:
            page.insert_text((x, y), text, fontsize=size, fontname='tiro')
        else:
            normal, italic, suffix = italic_tail
            page.insert_text((x, y), normal, fontsize=size, fontname='tiro')
            advance = pymupdf.get_text_length(normal, fontname='tiro', fontsize=size)
            page.insert_text((x + advance, y), italic, fontsize=size, fontname='tiit')
            advance += pymupdf.get_text_length(italic, fontname='tiit', fontsize=size)
            if suffix:
                page.insert_text((x + advance, y), suffix, fontsize=size, fontname='tiro')
        rows.append(y)
        y += step
    def styled_row(parts):
        nonlocal y
        advance = 0
        for text, font in parts:
            page.insert_text((x + advance, y), text, fontsize=size, fontname=font)
            advance += pymupdf.get_text_length(text, fontname=font, fontsize=size)
        rows.append(y)
        y += step
    row('[1] A. Author, "A research title')
    if styled_publication:
        styled_row([('continued," ', 'tiro'), ('Inter-', 'tiit')])
        styled_row([('national Journal of Research', 'tiit'), (', vol. ', 'tiro'),
                    ('12', 'tibo'), (', 2020, pp. 1-9.', 'tiro')])
    else:
        row('continued," Journal, 2020.' + (' ' + reference_url if reference_url else ''))
    if quoted_book:
        row('[2] B. Author, "A complete book')
        row('title," Publisher, 2021, pp. 1-9.')
    else:
        row('', italic_tail=('[2] B. Author, ', 'A complete book', ''))
        row('', italic_tail=('', 'title', '. Publisher, 2021, pp. 1-9.'))
    row('[3] C. Author, "Final title," Venue, 2022.')
    if columns == 2:
        page.insert_textbox((40, 55, width * .48, 240), 'Other column prose stays here. ' * 10,
                            fontsize=size)
        page.draw_rect((40, 300, width * .45, 350), fill=(.2, .6, .9), color=(0, 0, 0))
    page.set_rotation(rotation)
    native = [b for b in page.get_text('dict')['blocks'] if b['type'] == 0]
    ref_lines = [line for b in native for line in b['lines'] if line['bbox'][0] >= x - .1]
    heading_lines = [line for line in ref_lines if 'REFERENCES' in ''.join(s['text'] for s in line['spans'])]
    source_rows = []
    for baseline in rows:
        matching = [line for line in ref_lines if any(abs(s['origin'][1] - baseline) < .1 for s in line['spans'])]
        box = pymupdf.Rect(matching[0]['bbox'])
        for line in matching[1:]: box |= pymupdf.Rect(line['bbox'])
        text = ''.join(''.join(s['text'] for s in line['spans']) for line in sorted(matching, key=lambda l: l['bbox'][0]))
        source_rows.append((text, box))
    split = 4 if styled_publication else 3
    groups = [source_rows[:1], source_rows[1:split], source_rows[split:]]
    translations = ['[1] A. Author，“研究',
                    '标题”，期刊，2020。[2] B. Author，完整书籍',
                    '标题。Publisher，2021，第1-9页。[3] C. Author，“最后题名”，会议，2022。']
    blocks = []
    def block(key, text, box, translation):
        box = box * page.rotation_matrix
        return {'id': key, 'text': text, 'translation': translation, 'target': TARGET,
                'edited': True, 'bbox': [box.x0 / page.rect.width, box.y0 / page.rect.height,
                                        box.x1 / page.rect.width, box.y1 / page.rect.height]}
    blocks.append(block('heading', 'REFERENCES', pymupdf.Rect(heading_lines[0]['bbox']), '参考文献'))
    for i, (group, translation) in enumerate(zip(groups, translations)):
        box = pymupdf.Rect(group[0][1])
        for _, part in group[1:]: box |= part
        blocks.append(block(f'fragment-{i}', '\n'.join(text for text, _ in group), box, translation))
    return pdf, {'number': 1, 'blocks': blocks}


class LegacyBibliographyTests(unittest.TestCase):
    def document(self, **kwargs):
        pdf, saved = fixture(**kwargs)
        self.addCleanup(pdf.close)
        return pdf, saved

    def test_reconstructs_italic_book_and_shared_fragment_members_without_migration(self):
        pdf, saved = self.document()
        before = copy.deepcopy(saved)
        plan = reconstruct_legacy_bibliography(pdf[0], saved, TARGET)
        self.assertEqual(saved, before)
        self.assertEqual([e['title'] for e in plan['entries']], ['研究标题', '完整书籍标题', '最后题名'])
        self.assertTrue(plan['entries'][1]['reference']['italic_title'])
        self.assertEqual(plan['entries'][0]['members'], ['fragment-0', 'fragment-1'])
        self.assertIn('fragment-1', plan['entries'][1]['members'])
        self.assertIn('Journal, 2020.', plan['entries'][0]['text'])
        self.assertNotIn('期刊', plan['entries'][0]['text'])
        self.assertIn('Publisher, 2021, pp. 1-9.', plan['entries'][1]['text'])

    def test_source_sizes_columns_page_geometry_and_four_rotations(self):
        for size, columns, width, height in [(8, 1, 480, 640), (9, 2, 720, 540), (10, 2, 840, 1000)]:
            for rotation in (0, 90, 180, 270):
                with self.subTest(size=size, columns=columns, rotation=rotation):
                    pdf, saved = self.document(size=size, columns=columns, width=width, height=height, rotation=rotation)
                    page = pdf[0]
                    native = [b for b in page.get_text('dict')['blocks'] if b['type'] == 0]
                    plan = reconstruct_legacy_bibliography(page, saved, TARGET, native)
                    self.assertIsNotNone(plan)
                    page.set_rotation(0)
                    left_before = page.get_pixmap(clip=(30, 290, width * .46, 360)).samples if columns == 2 else None
                    typography = font_resources(''.join(e['text'] for e in plan['entries']) + plan['heading']['translation'])
                    with pymupdf.open() as overlays:
                        result = prepare_legacy_bibliography(page, saved, native, overlays, [], {}, typography, TARGET, plan=plan)
                        self.assertIsNotNone(result)
                        items, details = result
                        self.assertEqual(details['font_size'], size)
                        for block, style, placement in items:
                            self.assertEqual(placement['scale'], 1)
                            self.assertEqual(style['size'], size if block.get('kind') == 'reference' else size + 2)
                            for span in style['spans']: page.add_redact_annot(span['bbox'], fill=False, cross_out=False)
                        page.apply_redactions(images=0, graphics=0, text=0)
                        for _, _, placement in items:
                            page.show_pdf_page(pymupdf.Rect(placement['rect']), overlays, placement['overlay'], clip=pymupdf.Rect(placement['clip']))
                    self.assertEqual(sorted(map(int, re.findall(r'\[(\d+)\]', page.get_text()))), [1, 2, 3])
                    self.assertEqual(page.get_text().count('研究标题'), 1)
                    self.assertEqual(page.get_text().count('完整书籍标题'), 1)
                    if columns == 2:
                        self.assertEqual(left_before, page.get_pixmap(clip=(30, 290, width * .46, 360)).samples)
                    page.set_rotation(rotation)
                    self.assertEqual(page.rotation, rotation)

    def test_missing_translation_wrong_number_and_incomplete_metadata_fail_closed(self):
        for change in ('missing', 'number', 'unfinished'):
            pdf, saved = self.document()
            if change == 'missing': saved['blocks'][2]['translation'] = ''
            elif change == 'number': saved['blocks'][2]['translation'] = saved['blocks'][2]['translation'].replace('[2]', '[4]')
            else:
                for block in saved['blocks']: block['text'] = block['text'].replace('[3]', '[5]')
            self.assertIsNone(reconstruct_legacy_bibliography(pdf[0], saved, TARGET))

    def test_overflow_rolls_back_overlays_and_virtual_geometry(self):
        pdf, saved = self.document()
        saved['blocks'][3]['translation'] = saved['blocks'][3]['translation'].replace('最后题名', '很长的题名' * 500)
        plan = reconstruct_legacy_bibliography(pdf[0], saved, TARGET)
        self.assertIsNotNone(plan)
        typography = font_resources(''.join(e['text'] for e in plan['entries']) + '参考文献')
        native = [b for b in pdf[0].get_text('dict')['blocks'] if b['type'] == 0]
        rects = {'existing': pymupdf.Rect(0, 0, 1, 1)}
        with pymupdf.open() as overlays:
            result = prepare_legacy_bibliography(pdf[0], saved, native, overlays, [], rects, typography, TARGET, plan=plan)
            self.assertIsNone(result)
            self.assertEqual(len(overlays), 0)
            self.assertEqual(set(rects), {'existing'})

    def test_normalized_reference_path_also_keeps_source_and_metadata_size(self):
        for size in (7.97, 9, 10):
            with self.subTest(size=size):
                pdf, saved = self.document(size=size, quoted_book=True)
                document = {'pages': [saved]}
                self.assertTrue(normalize_document(document, pdf, force=True))
                saved = document['pages'][0]
                for block in saved['blocks']:
                    if block.get('kind') == 'reference':
                        block.update(translation=format_translation(block, '完整中文题名'), target=TARGET)
                page = pdf[0]
                native = [b for b in page.get_text('dict')['blocks'] if b['type'] == 0]
                typography = font_resources('完整中文题名参考文献')
                with pymupdf.open() as overlays:
                    result = prepare_bibliography(page, saved, native, overlays, [], {}, typography, TARGET)
                    self.assertIsNotNone(result)
                    self.assertAlmostEqual(result[1]['font_size'], size, places=2)
                    self.assertAlmostEqual(result[1]['metadata_font_size'], size, places=2)
                    for block, style, placement in result[0]:
                        if block.get('kind') != 'reference': continue
                        self.assertEqual(placement['scale'], 1)
                        actual = [span['size'] for b in overlays[placement['overlay']].get_text('dict')['blocks']
                                  for line in b.get('lines', ()) for span in line['spans'] if span['text'].strip()]
                        self.assertTrue(all(abs(value - size) < .05 for value in actual), actual)

    def test_following_graphic_limits_safe_column_growth(self):
        pdf, saved = self.document()
        page = pdf[0]
        # Text expansion may use whitespace, but must never cover this artwork.
        page.draw_rect((35, 165, 300, 260), fill=(.8, .2, .3))
        saved['blocks'][3]['translation'] = saved['blocks'][3]['translation'].replace('最后题名', '很长的题名' * 40)
        plan = reconstruct_legacy_bibliography(page, saved, TARGET)
        self.assertIsNotNone(plan)
        typography = font_resources(''.join(e['text'] for e in plan['entries']) + '参考文献')
        native = [b for b in page.get_text('dict')['blocks'] if b['type'] == 0]
        before = page.get_pixmap(clip=(35, 165, 300, 260)).samples
        with pymupdf.open() as overlays:
            result = prepare_legacy_bibliography(page, saved, native, overlays, [], {}, typography, TARGET, plan=plan)
            self.assertIsNone(result)
            self.assertEqual(len(overlays), 0)
        self.assertEqual(before, page.get_pixmap(clip=(35, 165, 300, 260)).samples)

    def render_links(self, pdf, saved):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf.save(root / 'source.pdf')
            report = build_layout(root, {'pages': [saved]}, TARGET)
            with pymupdf.open(root / 'layout' / (report['revision'] + '.pdf')) as output:
                return output[0].get_links(), output[0].get_text(), report

    def test_hidden_uri_title_and_separate_metadata_target_are_reanchored(self):
        pdf, saved = self.document()
        page = pdf[0]
        page.insert_link({'kind': pymupdf.LINK_URI, 'from': page.search_for('research title')[0],
                          'uri': 'https://example.org/paper'})
        page.insert_link({'kind': pymupdf.LINK_URI, 'from': page.search_for('Journal')[0],
                          'uri': 'https://example.org/journal'})
        links, text, report = self.render_links(pdf, saved)
        self.assertIn('研究标题', text)
        self.assertEqual(sorted(link.get('uri') for link in links), ['https://example.org/journal', 'https://example.org/paper'])
        self.assertEqual(len(report['placed_links']), 2)
        self.assertTrue(all(link.get('source_aliases') for link in report['placed_links']))
        self.assertLess((links[0]['from'] & links[1]['from']).get_area(), .1)

    def test_wrapped_hidden_goto_collapses_to_one_translated_anchor(self):
        pdf, saved = self.document()
        page = pdf[0]
        for needle in ('research title', 'continued'):
            page.insert_link({'kind': pymupdf.LINK_GOTO, 'from': page.search_for(needle)[0],
                              'page': 0, 'to': pymupdf.Point(42, 50)})
        links, text, report = self.render_links(pdf, saved)
        self.assertIn('研究标题', text)
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]['kind'], pymupdf.LINK_GOTO)
        self.assertEqual(links[0]['page'], 0)
        self.assertEqual(len(report['placed_links']), 1)
        self.assertEqual(len(report['placed_links'][0]['source_aliases']), 2)

    def test_distinct_hidden_title_links_fail_closed_instead_of_overlapping(self):
        pdf, saved = self.document()
        page = pdf[0]
        for needle, uri in [('research title', 'https://example.org/first'), ('continued', 'https://example.org/second')]:
            page.insert_link({'kind': pymupdf.LINK_URI, 'from': page.search_for(needle)[0], 'uri': uri})
        links, text, report = self.render_links(pdf, saved)
        self.assertNotIn('研究标题', text)
        self.assertIn('A research title', text)
        self.assertEqual(len(links), 2)
        self.assertTrue(any(issue['kind'] == 'reference' and '链接' in issue['message'] for issue in report['issues']))

    def test_literal_url_and_source_annotation_are_not_duplicated(self):
        uri = 'https://example.org/paper?a=1&b=2'
        pdf, saved = self.document(reference_url=uri)
        page = pdf[0]
        page.insert_link({'kind': pymupdf.LINK_URI, 'from': page.search_for(uri)[0], 'uri': uri})
        links, text, report = self.render_links(pdf, saved)
        self.assertIn('研究标题', text)
        self.assertEqual(''.join(text.split()).count(uri), 1)
        self.assertTrue(all(link.get('uri') == uri for link in links))
        self.assertEqual(len({tuple(link['from']) for link in links}), len(links))
        self.assertEqual(len({link['group'] for link in report['placed_links']}), 1)

    def test_reference_heading_link_survives_rotation_and_translation(self):
        for rotation in (0, 90, 180, 270):
            with self.subTest(rotation=rotation):
                pdf, saved = self.document(rotation=rotation)
                page = pdf[0]
                # insert_link receives the page's unrotated source rectangle.
                page.insert_link({'kind': pymupdf.LINK_URI, 'from': page.search_for('REFERENCES')[0],
                                  'uri': 'https://example.org/bibliography'})
                links, text, report = self.render_links(pdf, saved)
                self.assertIn('研究标题', text)
                self.assertEqual([link.get('uri') for link in links], ['https://example.org/bibliography'])
                self.assertEqual(len(report['placed_links']), 1)

    def test_metadata_italic_and_bold_survive_across_lines_in_both_paths(self):
        for normalized in (False, True):
            with self.subTest(normalized=normalized):
                pdf, saved = self.document(styled_publication=True, quoted_book=normalized)
                page = pdf[0]
                native = [b for b in page.get_text('dict')['blocks'] if b['type'] == 0]
                if normalized:
                    document = {'pages': [saved]}
                    self.assertTrue(normalize_document(document, pdf, force=True))
                    saved = document['pages'][0]
                    for block in saved['blocks']:
                        if block.get('kind') == 'reference':
                            block.update(translation=format_translation(block, '研究标题'), target=TARGET)
                    plan = None
                else:
                    plan = reconstruct_legacy_bibliography(page, saved, TARGET, native)
                    self.assertIsNotNone(plan)
                typography = font_resources('研究标题完整书籍标题最后题名参考文献')
                with pymupdf.open() as overlays:
                    if normalized:
                        result = prepare_bibliography(page, saved, native, overlays, [], {}, typography, TARGET)
                    else:
                        result = prepare_legacy_bibliography(page, saved, native, overlays, [], {}, typography, TARGET, plan=plan)
                    self.assertIsNotNone(result)
                    first = result[0][0][2]
                    rendered = overlays[first['overlay']]
                    spans = [span for b in rendered.get_text('dict')['blocks'] for line in b.get('lines', ())
                             for span in line['spans'] if span['text'].strip()]
                    self.assertIn('InternationalJournalofResearch', ''.join(rendered.get_text().split()))
                    self.assertTrue(all(span['flags'] & 2 for span in spans if 'International' in span['text'] or 'Research' in span['text']))
                    volumes = [span for span in spans if span['text'].strip() == '12']
                    self.assertTrue(volumes)
                    self.assertTrue(all(span['flags'] & 16 for span in volumes))
                    self.assertTrue(all(not span['flags'] & 18 for span in spans if '2020' in span['text'] or '研究标题' in span['text']))
                    self.assertTrue(all(abs(span['size'] - 8) < .05 for span in spans))


if __name__ == '__main__':
    unittest.main()
