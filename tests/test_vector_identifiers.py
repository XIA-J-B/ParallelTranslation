import copy
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import pymupdf

from pdf_identifiers import prepare_vector_identifiers
from pdf_layout import inline_math_assets, inline_math_markup, typeset


class VectorIdentifierTests(unittest.TestCase):
    def fixture(self, *, size=10, dimensions=(595, 842), rotation=0, parts=('sensor', 'suite')):
        pdf = pymupdf.open()
        self.addCleanup(pdf.close)
        page = pdf.new_page(width=dimensions[0], height=dimensions[1])
        cell, x, baseline = size * .6, 50, 80
        for index, part in enumerate(parts):
            page.insert_text((x, baseline), part, fontname='cour', fontsize=size)
            x += len(part) * cell
            if index + 1 < len(parts):
                page.draw_line((x + .1 * cell, baseline - .02 * size),
                               (x + .5 * cell, baseline - .02 * size), width=.04 * size)
                x += .5 * cell
        page.insert_text((50, baseline + size * 1.5), 'foreign neighbor', fontsize=size)
        page.set_rotation(rotation)
        style = {'spans': [span for item in page.get_text('dict')['blocks']
                           for line in item.get('lines', []) for span in line['spans']]}
        block = {'id': 'stable', 'text': ' '.join(parts), 'translation': '保留 ' + ' '.join(parts) + '。'}
        return page, block, style

    def test_identifier_and_underscore_are_one_original_glyph_asset(self):
        page, block, style = self.fixture()
        before = copy.deepcopy(block)
        source = page.get_text()
        drawings = page.get_drawings()
        result = prepare_vector_identifiers(page, block, style, drawings)
        self.assertEqual(result['translation'], '保留 sensor_suite。')
        self.assertEqual(result['identifiers'], ['sensor_suite'])
        self.assertEqual(len(result['owned_strokes']), 1)
        assets = inline_math_assets(page, result['runs'], drawings=result['drawings'])
        self.assertEqual(len(assets), 1)
        root = ET.fromstring(assets[0]['svg'])
        ns = '{http://www.w3.org/2000/svg}'
        self.assertEqual(''.join(node.get('data-text', '') for node in root.iter(ns + 'use')), 'sensorsuite')
        self.assertEqual(len([node for node in root.iter(ns + 'path') if node.get('stroke')]), 1)
        markup, plain, labels, _ = inline_math_markup(result['translation'], assets, pymupdf.Archive())
        self.assertEqual(markup.count('<img'), 1)
        self.assertEqual(labels, ['sensor_suite'])
        self.assertEqual(plain, '保留 。')
        self.assertEqual(block, before)
        self.assertEqual(page.get_text(), source)
        self.assertEqual(len(page.get_drawings()), len(drawings))

    def test_multiple_vector_underscores_form_a_complete_identifier(self):
        page, block, style = self.fixture(parts=('sensor', 'suite', 'config'))
        result = prepare_vector_identifiers(page, block, style, page.get_drawings())
        self.assertEqual(result['identifiers'], ['sensor_suite_config'])
        self.assertEqual(len(result['runs']), 1)
        self.assertEqual(len(result['owned_strokes']), 2)

    def test_repeated_identifier_maps_all_equal_style_occurrences_but_rejects_count_or_style_mismatch(self):
        for second_font in ('cour', 'cobo'):
            page, block, _ = self.fixture()
            page.insert_text((50, 130), 'sensor', fontname=second_font, fontsize=10)
            page.insert_text((89, 130), 'suite', fontname=second_font, fontsize=10)
            page.draw_line((86.6, 129.8), (89, 129.8), width=.4)
            style = {'spans': [span for item in page.get_text('dict')['blocks']
                               for line in item.get('lines', []) for span in line['spans']]}
            block['translation'] = '使用 sensor suite，再比较 sensor_suite。'
            result = prepare_vector_identifiers(page, block, style, page.get_drawings())
            if second_font != 'cour':
                self.assertIn('reason', result)
                self.assertEqual(result['owned_strokes'], [])
                continue
            self.assertNotIn('reason', result)
            self.assertEqual(result['translation'], '使用 sensor_suite，再比较 sensor_suite。')
            self.assertEqual(len(result['runs']), 2)
            self.assertEqual(len(result['owned_strokes']), 2)
            assets = inline_math_assets(page, result['runs'], drawings=result['drawings'])
            markup, _, labels, _ = inline_math_markup(result['translation'], assets, pymupdf.Archive())
            self.assertEqual(markup.count('<img'), 2)
            self.assertEqual(labels, ['sensor_suite', 'sensor_suite'])
            block['translation'] = '只有一次 sensor_suite。'
            result = prepare_vector_identifiers(page, block, style, page.get_drawings())
            self.assertIn('reason', result)
            self.assertEqual(result['owned_strokes'], [])

    def test_detection_uses_native_geometry_across_sizes_and_page_rotations(self):
        for dimensions in ((595, 842), (840, 540)):
            for size in (8, 10, 14):
                for rotation in (0, 90, 180, 270):
                    with self.subTest(dimensions=dimensions, size=size, rotation=rotation):
                        page, block, style = self.fixture(size=size, dimensions=dimensions, rotation=rotation)
                        result = prepare_vector_identifiers(page, block, style, page.get_drawings())
                        self.assertEqual(result['identifiers'], ['sensor_suite'])

    def test_a_rule_in_another_column_is_not_owned_by_this_paragraph(self):
        page, block, style = self.fixture()
        page.insert_text((330, 80), 'sensor', fontname='cour', fontsize=10)
        page.insert_text((369, 80), 'suite', fontname='cour', fontsize=10)
        page.draw_line((366.6, 79.8), (369, 79.8), width=.4)
        result = prepare_vector_identifiers(page, block, style, page.get_drawings())
        self.assertEqual(result['identifiers'], ['sensor_suite'])
        self.assertEqual(len(result['owned_strokes']), 1)
        self.assertLess(result['owned_strokes'][0][2], 200)

    def test_unmapped_duplicate_or_larger_identifier_keeps_ownership_unclaimed(self):
        page, block, style = self.fixture()
        for translation in ('遗漏了代码标识符', 'sensor_suite 与 sensor suite', 'other_sensor_suite'):
            with self.subTest(translation=translation):
                result = prepare_vector_identifiers(page, {**block, 'translation': translation}, style, page.get_drawings())
                self.assertIn('reason', result)
                self.assertEqual(result['runs'], [])
                self.assertEqual(result['owned_strokes'], [])
                self.assertEqual(result['translation'], translation)

    def test_normal_spaces_long_rules_math_bars_and_other_colors_are_not_claimed(self):
        page, block, style = self.fixture()
        original = page.get_drawings()[0]
        for changes in (
            {'items': [('l', pymupdf.Point(80, 79.8), pymupdf.Point(100, 79.8))]},
            {'items': [('l', pymupdf.Point(86.6, 72), pymupdf.Point(89, 72))]},
            {'color': (1, 0, 0)},
            {'items': original['items'] + [('l', pymupdf.Point(20, 20), pymupdf.Point(30, 20))]},
        ):
            with self.subTest(changes=changes):
                result = prepare_vector_identifiers(page, block, style, [{**original, **changes}])
                self.assertEqual(result['owned_strokes'], [])
        raw = page.get_text('rawdict')
        for item in raw['blocks']:
            for line in item.get('lines', []):
                for span in line['spans']:
                    for char in span['chars']:
                        char['synthetic'] = False
        self.assertEqual(prepare_vector_identifiers(page, block, style, [original], raw)['owned_strokes'], [])
        self.assertEqual(prepare_vector_identifiers(page, block, {'spans': []}, [original])['owned_strokes'], [])

    def test_typeset_moves_the_complete_identifier_without_leaving_its_old_rule(self):
        with tempfile.TemporaryDirectory() as temp, pymupdf.open() as source:
            page = source.new_page()
            page.insert_textbox((50, 65, 300, 105),
                'This paragraph introduces the experimental procedure and describes the evaluation protocol.',
                fontsize=11, fontname='tiro')
            page.insert_text((50, 120), 'The simulator stores evaluation results using', fontsize=11, fontname='tiro')
            page.insert_text((50, 135), 'sensor', fontsize=10, fontname='cour')
            page.insert_text((89, 135), 'suite', fontsize=10, fontname='cour')
            page.draw_line((86.6, 134.8), (89, 134.8), width=.4)
            page.insert_text((125, 135), 'for every control experiment.', fontsize=11, fontname='tiro')
            page.insert_text((50, 150), 'It records all observations and model parameters', fontsize=11, fontname='tiro')
            page.insert_text((50, 165), 'so the protocol is reproducible across machines.', fontsize=11, fontname='tiro')
            old_rule = pymupdf.Rect(page.get_drawings()[0]['rect'])
            blocks = []
            for index, native in enumerate(page.get_text('blocks')):
                box = pymupdf.Rect(native[:4])
                blocks.append({'id': f'body-{index}', 'text': native[4].strip(), 'target': '简体中文',
                    'translation': ('第一段介绍实验流程与评估方案，并说明如何在控制实验中比较不同设置，完整保存所有观测结果以便后续分析和可靠复现。'
                                    '同时检查不同机器上的运行行为以及输出的一致性。' if index == 0 else '第二段保留 sensor suite 用于评估。'),
                    'bbox': [box.x0/page.rect.width, box.y0/page.rect.height, box.x1/page.rect.width, box.y1/page.rect.height]})
            document = {'pages': [{'number': 1, 'blocks': blocks}]}
            before = copy.deepcopy(document)
            path = Path(temp)/'source.pdf'
            source.save(path)
            raw, report = typeset(path, document, '简体中文')
            with pymupdf.open(stream=raw, filetype='pdf') as output:
                self.assertIn('sensor_suite', output[0].get_text())
                self.assertTrue(output[0].get_image_info())
                self.assertFalse(any(all(abs(a-b) < .1 for a, b in zip(drawing['rect'], old_rule))
                                     for drawing in output[0].get_drawings()))
            self.assertEqual(document, before)
            self.assertFalse(report['issues'])
            self.assertEqual(report['scaled'], 0)
            self.assertGreater(report['placements']['body-0'][3], blocks[1]['bbox'][1])
            entries = [item for item in report['typography'] if any(key.startswith('body-') for key in item['blocks'])]
            self.assertEqual(len(entries), 2)
            self.assertTrue(all(abs(font['size']-11) < .02 for item in entries for font in item['fonts']))
            self.assertEqual(report['inline_math'][0]['source'], report['inline_math'][0]['matched'])


if __name__ == '__main__':
    unittest.main()
