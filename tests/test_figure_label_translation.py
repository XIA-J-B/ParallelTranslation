"""Actual glyph safety for anchored figure labels across page geometries."""
import copy
import unittest
from unittest.mock import patch

import pymupdf

from pdf_figure_labels import (is_figure_label_candidate, normalized,
                               prepare_figure_label)
from pdf_typography import font_resources


def native(page):
    return [block for block in page.get_text('dict', flags=pymupdf.TEXTFLAGS_DICT &
            ~pymupdf.TEXT_PRESERVE_IMAGES)['blocks'] if block['type'] == 0]


def text(line):
    return ''.join(span['text'] for span in line['spans'])


class FigureLabelTranslationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.typography = font_resources('训练后的强化学习策略回合平均奖励时间实验第一个和第二个物理引擎完整标题'
                                        'RGB视图深度分割PID、MPC、……第一模型第二模型')

    def render(self, page, source_text, translation):
        blocks = native(page)
        selected = [line for block in blocks for line in block['lines']
                    if text(line).strip() in source_text.splitlines()]
        box = pymupdf.Rect(selected[0]['bbox'])
        for line in selected[1:]:
            box |= pymupdf.Rect(line['bbox'])
        saved = {'id': 'label', 'text': source_text, 'translation': translation}
        before = copy.deepcopy(saved)
        with pymupdf.open() as overlays:
            result, style, reason = prepare_figure_label(overlays, page, saved, box, blocks, self.typography)
            self.assertEqual(saved, before)
            if result:
                for erase in result['redaction_boxes']:
                    page.add_redact_annot(erase, fill=False, cross_out=False)
                page.apply_redactions(images=0, graphics=0, text=0)
                page.show_pdf_page(pymupdf.Rect(result['rect']), overlays, result['overlay'],
                                   clip=pymupdf.Rect(result['clip']))
            return result, reason

    def test_single_label_preserves_graphics_pixels_and_nominal_font(self):
        with pymupdf.open() as pdf:
            page = pdf.new_page(width=420, height=500)
            page.draw_rect((50, 80, 370, 210), fill=(.82, .9, 1))
            page.draw_line((60, 190), (360, 100))
            page.insert_text((130, 65), 'Episode Mean Reward', fontsize=10)
            plot = page.get_pixmap(clip=(49, 79, 371, 211), matrix=pymupdf.Matrix(3, 3)).samples
            result, reason = self.render(page, 'Episode Mean Reward', '回合平均奖励')
            self.assertFalse(reason)
            self.assertEqual(result['scale'], 1)
            self.assertEqual(result['structure'][0]['source_size'], 10)
            self.assertEqual(result['structure'][0]['output_size'], 10)
            self.assertIn('回合平均奖励', page.get_text())
            self.assertEqual(plot, page.get_pixmap(clip=(49, 79, 371, 211), matrix=pymupdf.Matrix(3, 3)).samples)

    def test_multiple_columns_sizes_page_rotations_and_rotated_axis_titles(self):
        cases = ((1, 420, 7, 0), (2, 700, 9, 90), (3, 960, 10, 180), (2, 780, 11, 270))
        for columns, width, size, page_rotation in cases:
            for label_rotation in (0, 90, 180, 270):
                with self.subTest(columns=columns, page_rotation=page_rotation,
                                  label_rotation=label_rotation), pymupdf.open() as pdf:
                    page = pdf.new_page(width=width, height=560)
                    for column in range(columns):
                        x = 100 + column * (width - 140) / max(1, columns)
                        page.draw_rect((x - 45, 55, x + 140, 430), fill=(.9, .96, 1))
                    page.insert_text((160, 240), 'Time (s)', fontsize=size, rotate=label_rotation)
                    page.set_rotation(page_rotation)
                    # Call contract is unrotated source geometry; the caller
                    # restores the original display rotation after compositing.
                    page.set_rotation(0)
                    result, reason = self.render(page, 'Time (s)', '时间 (s)')
                    self.assertFalse(reason)
                    self.assertIsNotNone(result)
                    self.assertEqual(result['structure'][0]['output_size'], size)
                    self.assertIn('时间', page.get_text())
                    line = next(line for b in native(page) for line in b['lines']
                                if '时间' in text(line))
                    expected = {0: (1, 0), 90: (0, -1), 180: (-1, 0), 270: (0, 1)}[label_rotation]
                    self.assertAlmostEqual(line['dir'][0], expected[0], delta=.001)
                    self.assertAlmostEqual(line['dir'][1], expected[1], delta=.001)
                    page.set_rotation(page_rotation)
                    self.assertEqual(page.rotation, page_rotation)

    def test_cohesive_label_reflows_without_changing_font_size(self):
        with pymupdf.open() as pdf:
            page = pdf.new_page(width=360, height=400)
            page.draw_rect((60, 70, 170, 210), fill=(.95, .9, 1))
            page.insert_text((101, 130), 'Trained', fontsize=8)
            page.insert_text((98, 140), 'RL Policy', fontsize=8)
            result, reason = self.render(page, 'Trained\nRL Policy', '训练后的强化学习策略')
            self.assertFalse(reason)
            self.assertEqual(normalized(page.get_text()), '训练后的强化学习策略')
            self.assertEqual(result['structure'][0]['output_size'], 8)

    def test_independent_labels_never_merge_into_one_translation(self):
        with pymupdf.open() as pdf:
            page = pdf.new_page(width=400, height=300)
            page.draw_rect((30, 60, 350, 140))
            page.insert_text((50, 90), 'First', fontsize=8)
            page.insert_text((200, 90), 'Second', fontsize=8)
            before = page.get_pixmap().samples
            result, reason = self.render(page, 'First\nSecond', '第一个和第二个')
            self.assertIsNone(result)
            self.assertIn('数量不匹配', reason)
            self.assertEqual(before, page.get_pixmap().samples)

    def test_partial_label_preserves_unchanged_name_glyphs(self):
        with pymupdf.open() as pdf:
            page = pdf.new_page(width=400, height=300)
            page.insert_text((100, 100), 'Bullet', fontsize=7)
            page.insert_text((99, 106.4), 'Physics', fontsize=7)
            name = next(span for b in native(page) for line in b['lines'] for span in line['spans']
                        if span['text'] == 'Bullet')
            result, reason = self.render(page, 'Bullet\nPhysics', 'Bullet\n物理引擎')
            self.assertFalse(reason)
            after = next(span for b in native(page) for line in b['lines'] for span in line['spans']
                         if span['text'] == 'Bullet')
            self.assertEqual(name, after)
            self.assertEqual(len(result['structure']), 1)

    def test_real_stroke_collision_rejects_without_mutating_source(self):
        with pymupdf.open() as pdf:
            page = pdf.new_page(width=400, height=300)
            page.insert_text((160, 100), 'X', fontsize=10)
            for x in (145, 150, 155, 172, 177, 182):
                page.draw_line((x, 80), (x, 110), width=1.2)
            before = page.get_pixmap().samples
            result, reason = self.render(page, 'X', '完整时间标题')
            self.assertIsNone(result)
            self.assertIn('图形墨迹', reason)
            self.assertEqual(before, page.get_pixmap().samples)

    def test_pale_grid_stroke_is_protected_at_original_font_size(self):
        # First prove that the replacement fits: the rejection below must be
        # caused by the visible pale lines, not an overlong translation.
        with pymupdf.open() as pdf:
            clear = pdf.new_page(width=400, height=300)
            clear.insert_text((160, 100), 'X', fontsize=10)
            result, reason = self.render(clear, 'X', '时间标题')
            self.assertFalse(reason)
            self.assertIsNotNone(result)
            self.assertEqual(result['structure'][0]['output_size'], 10)
        with pymupdf.open() as pdf:
            page = pdf.new_page(width=400, height=300)
            page.insert_text((160, 100), 'X', fontsize=10)
            for x in (145, 150, 155, 172, 177, 182):
                page.draw_line((x, 80), (x, 110), color=(221 / 255,) * 3, width=.35)
            before = page.get_pixmap().samples
            result, reason = self.render(page, 'X', '时间标题')
            self.assertIsNone(result)
            self.assertIn('图形墨迹', reason)
            self.assertEqual(before, page.get_pixmap().samples)

    def test_partial_render_omission_cannot_hide_existing_chart_ink(self):
        # Model the observed PDF renderer failure: a clipped opaque rendering
        # can omit source marks, while the complete page remains correct.
        original_render = pymupdf.Page.get_pixmap

        def incomplete_clip(page, *args, **kwargs):
            bitmap = original_render(page, *args, **kwargs)
            if kwargs.get('clip') is not None and not kwargs.get('alpha'):
                bitmap.clear_with(255)
            return bitmap

        with pymupdf.open() as pdf:
            page = pdf.new_page(width=400, height=300)
            page.insert_text((160, 100), 'X', fontsize=10)
            for x in (145, 150, 155, 172, 177, 182):
                page.draw_line((x, 80), (x, 110), width=1.2)
            with patch.object(pymupdf.Page, 'get_pixmap', incomplete_clip):
                result, reason = self.render(page, 'X', '完整时间标题')
            self.assertIsNone(result)
            self.assertIn('图形墨迹', reason)

    def test_same_math_ticks_and_compatibility_punctuation_use_source_glyphs(self):
        with pymupdf.open() as pdf, pymupdf.open() as overlays:
            page = pdf.new_page(width=400, height=300)
            block = {'text': 'P0,1,2,3 (RPM)', 'translation': 'P0,1,2,3（RPM）'}
            self.assertEqual(prepare_figure_label(overlays, page, block, pymupdf.Rect(10, 10, 90, 30),
                                                 [], self.typography), (None, None, ''))
            self.assertEqual(len(overlays), 0)

    def test_axis_candidate_requires_plot_geometry_and_axis_syntax(self):
        with pymupdf.open() as pdf:
            page = pdf.new_page(width=500, height=500)
            page.draw_rect((80, 60, 380, 150))
            page.insert_text((180, 164), '# timesteps', fontsize=9)
            line = native(page)[0]['lines'][0]
            rect = pymupdf.Rect(line['bbox'])
            self.assertTrue(is_figure_label_candidate(page, {'text': '# timesteps'}, rect,
                                                     native(page), drawings=page.get_drawings()))
            self.assertFalse(is_figure_label_candidate(page, {'text': 'Our results'}, rect,
                                                      native(page), drawings=page.get_drawings()))
            self.assertFalse(is_figure_label_candidate(page, {'text': '# timesteps'}, rect,
                                                      native(page), drawings=[]))

    def test_raster_background_is_preserved_inside_original_label_footprint(self):
        with pymupdf.open() as pdf:
            page = pdf.new_page(width=400, height=300)
            pixels = bytes(channel for y in range(80) for x in range(160)
                           for channel in (220 - x // 4, 225 - x // 5, 230 - x // 8))
            image = pymupdf.Pixmap(pymupdf.csRGB, 160, 80, pixels, False)
            page.insert_image((40, 50, 360, 210), pixmap=image)
            page.insert_text((160, 155), 'Depth View', fontsize=10)
            source_images = [pdf.extract_image(info[0])['image'] for info in page.get_images()]
            result, reason = self.render(page, 'Depth View', '深度视图')
            self.assertFalse(reason)
            self.assertEqual(source_images, [pdf.extract_image(info[0])['image'] for info in page.get_images()])
            source = pymupdf.Rect(result['structure'][0]['source']) + (-.3, -.3, .3, .3)
            self.assertTrue(source.contains(pymupdf.Rect(result['structure'][0]['painted_rect'])))

    def test_raster_label_cannot_expand_into_new_image_area(self):
        with pymupdf.open() as pdf:
            page = pdf.new_page(width=400, height=300)
            pixels = bytes((210, 220, 230)) * 80 * 160
            page.insert_image((40, 50, 360, 210), pixmap=pymupdf.Pixmap(pymupdf.csRGB, 160, 80, pixels, False))
            page.insert_text((160, 155), 'X', fontsize=10)
            before = page.get_pixmap().samples
            result, reason = self.render(page, 'X', '完整时间标题')
            self.assertIsNone(result)
            self.assertTrue(reason)
            self.assertEqual(before, page.get_pixmap().samples)

    def test_expanded_labels_are_checked_against_previous_translated_ink(self):
        for color in ((0, 0, 0), (1, 1, 1)):
            with self.subTest(color=color), pymupdf.open() as pdf, pymupdf.open() as overlays:
                page = pdf.new_page(width=400, height=300)
                if color == (1, 1, 1):
                    page.draw_rect((100, 100, 250, 200), fill=(.2, .2, .2))
                page.insert_text((140, 150), 'X', fontsize=7, color=color)
                page.insert_text((160, 150), 'Y', fontsize=7, color=color)
                blocks = native(page)
                ready = []
                for original, translation in [('X', '第一模型'), ('Y', '第二模型')]:
                    line = next(line for b in blocks for line in b['lines'] if text(line) == original)
                    saved = {'text': original, 'translation': translation}
                    result, _, reason = prepare_figure_label(overlays, page, saved, pymupdf.Rect(line['bbox']),
                                                             blocks, self.typography, occupied=ready)
                    if original == 'X':
                        self.assertFalse(reason)
                        self.assertIsNotNone(result)
                        ready.append(result)
                    else:
                        self.assertIsNone(result)
                        self.assertIn('墨迹', reason)


if __name__ == '__main__':
    unittest.main()
