"""Explicit spacing exceptions cannot hide excessive compression or bad geometry."""
import unittest

import pymupdf

from audit_corpus_layout import spacing_is_safe, expected_han, collision_regions, han


class SpacingAuditTests(unittest.TestCase):
    def test_ordinary_flow_still_requires_source_ink_spacing(self):
        row = dict(gap=6, source_gap=4, source_ink_gap=8, ink_padding=1)
        self.assertFalse(spacing_is_safe(row, 6))
        self.assertTrue(spacing_is_safe({**row, 'gap': 7}, 7))

    def test_only_explicit_bounded_fit_can_use_twelve_percent(self):
        row = dict(gap=6.12, source_gap=6, source_ink_gap=8, ink_padding=1,
                   gap_factor=.89, actual_ink_gap=7.12,
                   spacing_reason='bounded-column-source-size')
        self.assertTrue(spacing_is_safe(row, 6.12))
        self.assertFalse(spacing_is_safe({**row, 'gap_factor': .87}, 6.12))
        self.assertFalse(spacing_is_safe({**row, 'spacing_reason': ''}, 6.12))
        self.assertFalse(spacing_is_safe(row, 5.8))
        self.assertFalse(spacing_is_safe({**row, 'actual_ink_gap': 8}, 6.12))

    def test_two_point_minimum_and_finite_measurements_are_required(self):
        row = dict(gap=.5, source_ink_gap=2, ink_padding=1, gap_factor=.9,
                   actual_ink_gap=1.5, spacing_reason='bounded-column-source-size')
        self.assertFalse(spacing_is_safe(row, .5))
        self.assertFalse(spacing_is_safe({**row, 'gap_factor': float('nan')}, .5))


class StructuredAuditTests(unittest.TestCase):
    def test_rebuilt_reference_checks_target_titles_and_source_metadata_once(self):
        blocks = [({'id': 'a', 'text': '[1] Author', 'translation': '标题出版信息',
                    'target': 'zh'}, None),
                  ({'id': 'b', 'text': 'continuation', 'translation': '继续出版信息',
                    'target': 'zh'}, None),
                  ({'id': 'body', 'text': 'Text', 'translation': '正文', 'target': 'zh'}, None)]
        plans = [{'blocks': ['a', 'b'], 'text': '[1] Author. 标题继续. Publisher 2024.'},
                 {'blocks': ['b'], 'text': '[2] Another Author. 第二标题. Publisher 2025.'}]
        expected = expected_han(blocks, set(), 'zh', plans)
        self.assertEqual(expected, han('标题继续第二标题正文'))
        self.assertTrue(expected - han('标题继续第二标题正'))
        self.assertTrue(expected - han('标题继续第二题正文'))

    def test_spanning_saved_block_uses_separate_painted_regions_at_all_rotations(self):
        for rotation in (0, 90, 180, 270):
            with self.subTest(rotation=rotation), pymupdf.open() as pdf:
                page = pdf.new_page(width=320, height=500)
                page.set_rotation(rotation)
                entries = [({'id': 'cells', 'bbox': [0, 0, 1, 1]}, pymupdf.Rect(0, 0, 1, 1))]
                parts = [{'blocks': ['cells'], 'source': [20, 30, 60, 45],
                          'rect': [20, 30, 60, 45]},
                         {'blocks': ['cells'], 'source': [200, 30, 240, 45],
                          'rect': [200, 30, 240, 45]}]
                regions = collision_regions(page, entries, parts)
                self.assertEqual(len(regions), 2)
                self.assertTrue((regions[0][1] & regions[1][1]).is_empty)
                for _, box, source in regions:
                    self.assertTrue(pymupdf.Rect(0, 0, 1, 1).contains(box))
                    self.assertEqual(box, source[0])


if __name__ == '__main__':
    unittest.main()
