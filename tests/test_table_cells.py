"""Cell-level table placement, source glyph ownership, and failure atomicity."""
import copy
import unittest

import pymupdf

import pdf_layout
from pdf_tables import cell_mapping, prepare_table_overlays, table_note_region, _painted_bounds
from pdf_typography import font_resources


class TableCellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.typography = font_resources('模型数量环境数量视觉本工作是否无视觉测试或值' * 2)

    @staticmethod
    def native(page):
        return [b for b in page.get_text('dict')['blocks'] if b['type'] == 0]

    @staticmethod
    def spans(page):
        return [s for b in TableCellTests.native(page) for line in b['lines'] for s in line['spans']]

    def apply(self, page, table, translate):
        rotation = page.rotation
        page.set_rotation(0)
        native = self.native(page)
        blocks = []
        for index, raw in enumerate(native):
            text = '\n'.join(''.join(s['text'] for s in line['spans']).strip() for line in raw['lines'])
            box = pymupdf.Rect(raw['bbox'])
            if not table.contains((box.tl + box.br) * .5):
                continue
            blocks.append({'id': f'block-{index}', 'text': text, 'translation': translate(text),
                           'target': 'zh', 'bbox': list(box)})
        original = copy.deepcopy(blocks)
        rects = {b['id']: pymupdf.Rect(b['bbox']) for b in blocks}
        with pymupdf.open() as overlays:
            prepared, handled, issues, details = prepare_table_overlays(
                page, blocks, rects, native, [table], overlays, self.typography, 'zh',
                drawings=page.get_drawings())
            index = pdf_layout._PageSpanIndex([(tuple(s['bbox']), id(s)) for b in native
                                               for line in b['lines'] for s in line['spans']])
            for _, style, _ in prepared:
                for box in pdf_layout.merged_line_boxes(style, index):
                    page.add_redact_annot(box, fill=False, cross_out=False)
            if prepared:
                page.apply_redactions(images=0, graphics=0, text=0)
            for _, _, result in prepared:
                page.show_pdf_page(pymupdf.Rect(result['rect']), overlays, result['overlay'],
                                   clip=pymupdf.Rect(result['clip']))
            self.assertEqual(blocks, original)
            page.set_rotation(rotation)
            return prepared, handled, issues, details

    @staticmethod
    def centered(page, x, y, value, font='tiro', size=8):
        width = pymupdf.get_text_length(value, fontname=font, fontsize=size)
        page.insert_text((x - width / 2, y), value, fontsize=size, fontname=font)

    def test_cells_keep_numbers_weights_rules_and_positions_in_four_rotations(self):
        for columns, width, offset in [(1, 420, 40), (2, 720, 390)]:
            for rotation in (0, 90, 180, 270):
                with self.subTest(columns=columns, rotation=rotation), pymupdf.open() as pdf:
                    page = pdf.new_page(width=width, height=560)
                    box = pymupdf.Rect(offset, 70, offset + 270, 158)
                    for y in (70, 96, 158):
                        page.draw_line((box.x0, y), (box.x1, y), width=.4)
                    for x, text in [(offset + 35, 'Model'), (offset + 130, 'Count'), (offset + 225, 'Vision')]:
                        self.centered(page, x, 87, text)
                    for row in range(4):
                        y = 110 + row * 12
                        self.centered(page, offset + 35, y, 'Alpha')
                        self.centered(page, offset + 130, y, str(row + 1) + '.0')
                        self.centered(page, offset + 225, y, 'Yes' if row % 2 else 'No',
                                      font='tibo' if row % 2 else 'tiro')
                    if columns == 2:
                        page.insert_text((40, 110), 'Neighbouring prose must remain unchanged.', fontsize=10)
                    rule_pixels = [page.get_pixmap(matrix=pymupdf.Matrix(4, 4),
                                   clip=pymupdf.Rect(box.x0, y - 1, box.x1, y + 1)).samples
                                   for y in (70, 96, 158)]
                    numeric = {s['text']: (s['origin'], s['font'], s['size']) for s in self.spans(page)
                               if s['text'].endswith('.0')}
                    drawings = [tuple(d['rect']) for d in page.get_drawings()]
                    page.set_rotation(rotation)
                    prepared, handled, issues, details = self.apply(page, box, lambda text: text.replace('Model', '模型')
                        .replace('Count', '数量').replace('Vision', '视觉').replace('Yes', '是').replace('No', '否'))
                    self.assertFalse(issues)
                    self.assertTrue(handled and prepared)
                    self.assertEqual(page.rotation, rotation)
                    page.set_rotation(0)
                    self.assertEqual([tuple(d['rect']) for d in page.get_drawings()], drawings)
                    for i, y in enumerate((70, 96, 158)):
                        self.assertEqual(page.get_pixmap(matrix=pymupdf.Matrix(4, 4),
                            clip=pymupdf.Rect(box.x0, y - 1, box.x1, y + 1)).samples, rule_pixels[i])
                    for span in self.spans(page):
                        if span['text'] in numeric:
                            self.assertEqual((span['origin'], span['font'], span['size']), numeric[span['text']])
                        if span['text'] in ('是', '否'):
                            self.assertAlmostEqual(span['size'], 8, delta=.01)
                            self.assertEqual(bool(span['flags'] & 16), span['text'] == '是')
                    if columns == 2:
                        self.assertIn('Neighbouring prose must remain unchanged.', page.get_text())
                    self.assertTrue(all(item['complete'] for item in details))

    def test_two_line_headers_are_reconstructed_by_column_axes(self):
        with pymupdf.open() as pdf:
            page = pdf.new_page(width=500, height=300)
            page.draw_line((40, 60), (450, 60))
            page.draw_line((40, 100), (450, 100))
            for y, values in [(75, ['Model', 'Environment', 'Vision']), (84, ['Count', 'Count', 'Input'])]:
                for x, text in zip((110, 245, 380), values):
                    self.centered(page, x, y, text)
            lines = [line for b in self.native(page) for line in b['lines']]
            text = '\n'.join(''.join(s['text'] for s in line['spans']) for line in lines)
            mapping, reason = cell_mapping(lines, text, '模型数量\n环境数量\n视觉')
            self.assertFalse(reason)
            self.assertEqual([cell['source'] for cell, _ in mapping], ['Model Count', 'Environment Count', 'Vision Input'])
            self.assertTrue(all(mode == 'stacked-header' for _, mode in mapping))
            prepared, handled, issues, _ = self.apply(page, pymupdf.Rect(40, 60, 450, 100),
                lambda _: '模型数量\n环境数量\n视觉')
            self.assertFalse(issues)
            self.assertTrue(prepared and handled)
            self.assertIn('模型数量', page.get_text())
            self.assertTrue(all(abs(cell['source_size'] - cell['output_size']) < .01
                                for _, _, result in prepared for cell in result['structure']))

    def test_table_note_keeps_raised_marker_and_source_baseline(self):
        with pymupdf.open() as pdf:
            page = pdf.new_page(width=500, height=300)
            page.insert_htmlbox((50, 60, 350, 100), '<sup>*</sup> or Renderer',
                                css='body{font-family:serif;font-size:8pt}')
            before = next(s for s in self.spans(page) if s['text'] == '*')
            prepared, handled, issues, _ = self.apply(page, pymupdf.Rect(40, 50, 380, 100),
                                                      lambda text: text.replace('or', '或'))
            self.assertFalse(issues)
            self.assertTrue(prepared and handled)
            after = next(s for s in self.spans(page) if s['text'] == '*')
            self.assertEqual((after['origin'], after['size'], after['font']),
                             (before['origin'], before['size'], before['font']))
            self.assertIn('或', page.get_text())
            self.assertEqual(prepared[0][2]['structure'][0]['retained_source_spans'][0]['text'], '*')

    def test_only_nearby_raised_marker_notes_inherit_table_width(self):
        with pymupdf.open() as pdf:
            page = pdf.new_page(width=500, height=400)
            table = pymupdf.Rect(50, 40, 350, 100)
            page.insert_text((70, 70), 'Header', fontsize=8)
            page.insert_htmlbox((70, 116, 340, 145), '<sup>*</sup> or Renderer',
                                css='body{font-family:serif;font-size:8pt}')
            page.insert_text((70, 180), 'Ordinary prose remains a paragraph.', fontsize=8)
            native = self.native(page)
            note = next(b for b in native if any(s['text'] == '*' for l in b['lines'] for s in l['spans']))
            mapped = table_note_region(pymupdf.Rect(note['bbox']), native, [table])
            self.assertIsNotNone(mapped)
            self.assertEqual((mapped.x0, mapped.x1), (table.x0, table.x1))
            ordinary = next(b for b in native if any('Ordinary' in s['text'] for l in b['lines'] for s in l['spans']))
            self.assertIsNone(table_note_region(pymupdf.Rect(ordinary['bbox']), native, [table]))
            self.assertIsNone(table_note_region(pymupdf.Rect(note['bbox']), native,
                                               [pymupdf.Rect(50, 20, 350, 60)]))

    def test_generated_overlay_alpha_bounds_agree_with_full_page_pixels(self):
        with pymupdf.open() as pdf:
            page = pdf.new_page(width=300, height=200)
            page.insert_htmlbox((40, 40, 200, 90), '模型数量 12.5', css=self.typography['css']
                + f"body{{font-family:{self.typography['family']};font-size:8pt}}", archive=self.typography['archive'])
            box = pymupdf.Rect(35, 35, 205, 95)
            measured = _painted_bounds(page, box)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(6, 6), alpha=True)
            alpha = memoryview(pix.samples)[pix.n - 1::pix.n]
            cells = [i for i, a in enumerate(alpha) if a]
            xs, ys = [i % pix.width for i in cells], [i // pix.width for i in cells]
            actual = pymupdf.Rect((pix.x + min(xs) - 1) / 6, (pix.y + min(ys) - 1) / 6,
                                  (pix.x + max(xs) + 2) / 6, (pix.y + max(ys) + 2) / 6)
            self.assertEqual(measured, actual)

    def test_ambiguous_mapping_and_changed_numeric_values_reject_whole_block(self):
        for mode in ('mapping', 'numbers'):
            with self.subTest(mode=mode), pymupdf.open() as pdf:
                page = pdf.new_page(width=420, height=400)
                for x, text in [(70, 'Value 1.0'), (200, 'Value 2.0')]:
                    page.insert_text((x, 90), text, fontsize=8)
                before = page.get_pixmap().samples
                prepare, handled, issues, _ = self.apply(page, pymupdf.Rect(40, 70, 350, 110),
                    lambda text: '测试' if mode == 'mapping' else text.replace('1.0', '9.0').replace('Value', '值'))
                self.assertFalse(prepare)
                self.assertFalse(handled)
                self.assertTrue(issues)
                self.assertEqual(page.get_pixmap().samples, before)

    def test_too_long_cell_never_shrinks_or_covers_an_adjacent_row(self):
        with pymupdf.open() as pdf:
            page = pdf.new_page(width=300, height=200)
            page.draw_line((40, 70), (200, 70))
            page.draw_line((40, 94), (200, 94))
            for x, label in [(60, 'First'), (120, 'Second'), (180, 'Third')]:
                self.centered(page, x, 87, label)
            before = page.get_pixmap().samples
            prepared, handled, issues, _ = self.apply(page, pymupdf.Rect(40, 70, 200, 94),
                lambda text: '\n'.join('测试' * 15 for _ in text.splitlines()))
            self.assertFalse(prepared)
            self.assertFalse(handled)
            self.assertTrue(issues)
            self.assertEqual(page.get_pixmap().samples, before)


if __name__ == '__main__':
    unittest.main()
