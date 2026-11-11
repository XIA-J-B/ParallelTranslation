"""Reader selections keep unchanged cells when only nearby labels change."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf
import pdf_layout


class StructuredSelectionTests(unittest.TestCase):
    def test_table_header_selection_still_covers_unchanged_product_name(self):
        for rotation in (0, 90, 180, 270):
            with self.subTest(rotation=rotation), tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / 'source.pdf'
                with pymupdf.open() as pdf:
                    page = pdf.new_page(width=420, height=320)
                    page.draw_line((40, 70), (370, 70))
                    page.draw_line((40, 100), (370, 100))
                    page.insert_text((55, 90), 'Model', fontsize=9, fontname='tiro')
                    page.insert_text((270, 90), 'Renderer', fontsize=9, fontname='tiro')
                    page.set_rotation(rotation)
                    blocks = []
                    for index, raw in enumerate(page.get_text('dict')['blocks']):
                        if raw['type'] != 0:
                            continue
                        box = pymupdf.Rect(raw['bbox']) * page.rotation_matrix
                        text = '\n'.join(''.join(s['text'] for s in line['spans']) for line in raw['lines'])
                        blocks.append({'id': str(index), 'text': text,
                                       'translation': text.replace('Model', '模型'), 'target': 'zh',
                                       'bbox': [box.x0/page.rect.width, box.y0/page.rect.height,
                                                box.x1/page.rect.width, box.y1/page.rect.height]})
                    product = page.search_for('Renderer')[0] * page.rotation_matrix
                    product = pymupdf.Rect(product.x0/page.rect.width, product.y0/page.rect.height,
                                           product.x1/page.rect.width, product.y1/page.rect.height)
                    pdf.save(source)
                self.assertEqual(len(blocks), 1, 'Fixture must contain one shared saved header block')
                document = {'pages': [{'number': 1, 'blocks': blocks}]}
                baseline = copy.deepcopy(document)
                with patch.object(pdf_layout, 'table_regions', return_value=[pymupdf.Rect(40, 70, 370, 100)]):
                    raw, report = pdf_layout.typeset(source, document, 'zh')
                self.assertEqual(document, baseline)
                self.assertEqual(report['preserved'], 0)
                self.assertEqual(report['scaled'], 0)
                self.assertTrue(pymupdf.Rect(report['placements'][blocks[0]['id']]).contains(product))
                with pymupdf.open(stream=raw, filetype='pdf') as pdf:
                    self.assertIn('模型', pdf[0].get_text())
                    self.assertIn('Renderer', pdf[0].get_text())


if __name__ == '__main__':
    unittest.main()
