import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf

import pdf_layout as layout
from tests.test_inline_math_layout import named_math_font


class CaptionMathTests(unittest.TestCase):
    def fixture(self, columns=1, rotation=0, size=8, mismatch=False):
        pdf = pymupdf.open()
        page = pdf.new_page(width=columns * 360, height=400)
        page.insert_font(fontname="boldmath", fontbuffer=named_math_font("bold"))
        page.insert_font(fontname="italicmath", fontbuffer=named_math_font("italic"))
        figures = []
        for column in range(columns):
            left = 30 + column * 360
            figure = pymupdf.Rect(left, 35, left + 290, 135)
            page.draw_rect(figure, fill=(.7, .8, .9), color=(.2, .3, .4))
            page.insert_text((left + 40, 85), "x_axis = 7", fontname="cour", fontsize=9)
            figures.append(figure)
            x, y = left, 160

            def prose(value, font="tiro"):
                nonlocal x
                page.insert_text((x, y), value, fontsize=size, fontname=font)
                x += pymupdf.get_text_length(value, fontsize=size, fontname=font)

            def variable(base, sub, accent=None):
                nonlocal x
                if accent:
                    page.insert_text((x + size * .1, y), accent, fontsize=size, fontname="boldmath")
                page.insert_text((x, y), base, fontsize=size, fontname="boldmath" if accent else "italicmath")
                width = pymupdf.Font(fontbuffer=named_math_font("bold" if accent else "italic")).text_length(base, fontsize=size)
                page.insert_text((x + width, y + size * .2), sub, fontsize=size * .7, fontname="italicmath")
                x += width + size * .6

            prose("Fig. 2. ")
            prose("Measured motion.", "tibo")
            prose(" Velocity ")
            variable("x", "n", "˙")
            prose(" and speed ")
            variable("P", "0")
            prose(" with rate ")
            variable("ω", "y")
            prose(".")
            x, y = left, y + size * 1.5
            prose("Robot ")
            variable("CF", "0")
            prose(" follows the same trajectory in this experiment.")
        page.set_rotation(rotation)
        blocks = []
        for index, native in enumerate(page.get_text("dict")["blocks"]):
            if native["type"] != 0:
                continue
            text = "\n".join("".join(span["text"] for span in line["spans"]) for line in native["lines"])
            translation = text
            if text.startswith("Fig."):
                translation = ("图 2. 运动测量。线速度 ẋ_{n}、转速 P_0 及角速度 ω_y；"
                               "机器人 Crazyflie CF_0 沿相同轨迹运动。")
                if mismatch:
                    translation = translation.replace("ẋ_{n}", "q_n")
            box = pymupdf.Rect(native["bbox"]) * page.rotation_matrix
            blocks.append({"id": f"arbitrary-{index}", "text": text, "translation": translation,
                           "target": "简体中文", "bbox": [box.x0 / page.rect.width, box.y0 / page.rect.height,
                                                           box.x1 / page.rect.width, box.y1 / page.rect.height]})
        return pdf, {"pages": [{"number": 1, "blocks": blocks}]}, figures

    def render(self, **options):
        source, document, figures = self.fixture(**options)
        self.addCleanup(source.close)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "source.pdf"
            source.save(path)
            raw, report = layout.typeset(path, document, "简体中文")
        output = pymupdf.open(stream=raw, filetype="pdf")
        self.addCleanup(output.close)
        return source, output, document, report, figures

    def test_caption_math_keeps_accents_scripts_source_size_emphasis_and_fixed_figure(self):
        for columns, rotation, size in ((1, 0, 8), (2, 90, 8), (2, 180, 9), (1, 270, 10)):
            with self.subTest(columns=columns, rotation=rotation, size=size):
                source, output, document, report, figures = self.render(columns=columns, rotation=rotation, size=size)
                captions = [block for block in document["pages"][0]["blocks"] if block["text"].startswith("Fig.")]
                self.assertEqual(len(captions), columns)
                self.assertFalse([issue for issue in report["issues"] if issue["kind"] != "figure"], report["issues"])
                math = [entry for entry in report["inline_math"] if any(b["id"] in entry["blocks"] for b in captions)]
                self.assertEqual(len(math), columns)
                for entry in math:
                    self.assertCountEqual(entry["matched"], [layout.normalized_inline_math("˙xn"), "P0", "ωy", "CF0"])
                    self.assertCountEqual(entry["source"], entry["matched"])
                records = [entry for entry in report["typography"] if any(b["id"] in entry["blocks"] for b in captions)]
                self.assertTrue(all(entry["scale"] == 1 for entry in records))
                self.assertTrue(all(abs(font["size"] - size) < .01 for entry in records for font in entry["fonts"]))
                visible = "".join(chr(char[0]) for span in output[0].get_texttrace() if span["type"] != 3
                                  for char in span["chars"])
                self.assertNotIn("˙", visible)
                self.assertNotIn("ẋ", visible)
                self.assertNotIn("P_0", visible)
                self.assertNotIn("CF_0", visible)
                spans = [span for block in output[0].get_text("dict")["blocks"] if block["type"] == 0
                         for line in block["lines"] for span in line["spans"]]
                self.assertTrue(any("运动测量" in span["text"] and span["flags"] & 16 for span in spans))
                self.assertFalse(any("线速度" in span["text"] and span["flags"] & 16 for span in spans))
                self.assertEqual(output[0].rotation, rotation)
                source[0].set_rotation(0)
                output[0].set_rotation(0)
                for figure in figures:
                    self.assertEqual(source[0].get_pixmap(clip=figure, matrix=pymupdf.Matrix(3, 3)).samples,
                                     output[0].get_pixmap(clip=figure, matrix=pymupdf.Matrix(3, 3)).samples)

    def test_unmatched_caption_variable_preserves_the_whole_caption_with_reason(self):
        _, output, document, report, _ = self.render(mismatch=True)
        block = next(block for block in document["pages"][0]["blocks"] if block["text"].startswith("Fig."))
        self.assertNotIn(block["id"], report["placements"])
        self.assertIn("Measured motion", output[0].get_text())
        self.assertNotIn("运动测量", output[0].get_text())
        self.assertTrue(any(issue["block_id"] == block["id"] and "数学变量" in issue["message"] for issue in report["issues"]))

    def test_failed_glyph_asset_preserves_the_whole_caption(self):
        with patch.object(layout, "inline_math_assets", return_value=[]):
            _, output, document, report, _ = self.render()
        block = next(block for block in document["pages"][0]["blocks"] if block["text"].startswith("Fig."))
        self.assertNotIn(block["id"], report["placements"])
        self.assertIn("Measured motion", output[0].get_text())
        self.assertTrue(any("数学字形" in issue["message"] for issue in report["issues"]))

    def test_table_cells_and_figure_labels_do_not_enter_caption_math_path(self):
        for kind in ("figure_label", "table", "table_cell", "reference"):
            block = {"kind": kind, "text": "Fig. 2. Measured motion with variables x and y.",
                     "translation": "图 2. 这是图中的一个标签或表格单元。"}
            self.assertFalse(layout.should_preserve_inline_symbols(block))
        self.assertFalse(layout.should_preserve_inline_symbols({"kind": "figure", "text": "Velocity x",
                                                               "translation": "速度的刻度标签"}))

    def test_figure_and_table_references_in_running_prose_keep_complete_math(self):
        for prefix, translated_prefix in (("Figure 3 shows", "图 3 展示了"), ("Table 3 compares", "表 3 比较了")):
            with self.subTest(prefix=prefix), tempfile.TemporaryDirectory() as temp, pymupdf.open() as source:
                page = source.new_page(width=520, height=300)
                page.insert_font(fontname="boldmath", fontbuffer=named_math_font("bold"))
                page.insert_font(fontname="italicmath", fontbuffer=named_math_font("italic"))
                x, y = 35, 75
                first = prefix + " the velocity "
                page.insert_text((x, y), first, fontsize=10, fontname="tiro")
                x += pymupdf.get_text_length(first, fontsize=10, fontname="tiro")
                page.insert_text((x + 1, y), "˙", fontsize=10, fontname="boldmath")
                page.insert_text((x, y), "x", fontsize=10, fontname="boldmath")
                page.insert_text((x + 5, y + 2), "n", fontsize=7, fontname="italicmath")
                x += 13
                middle = " and the motor speed "
                page.insert_text((x, y), middle, fontsize=10, fontname="tiro")
                x += pymupdf.get_text_length(middle, fontsize=10, fontname="tiro")
                page.insert_text((x, y), "P", fontsize=10, fontname="italicmath")
                page.insert_text((x + 6, y + 2), "0", fontsize=7, fontname="italicmath")
                page.insert_text((x + 12, y), " in the experiment.", fontsize=10, fontname="tiro")
                native = page.get_text("dict")["blocks"][0]
                text = " ".join("".join(span["text"] for span in line["spans"]) for line in native["lines"])
                block = {"id": "ordinary-paragraph", "text": text, "target": "简体中文",
                         "translation": translated_prefix + "线速度 ẋ_n 和电机转速 P_0，用于描述实验中的状态变化。",
                         "bbox": [native["bbox"][0] / 520, native["bbox"][1] / 300,
                                  native["bbox"][2] / 520, native["bbox"][3] / 300]}
                self.assertTrue(layout.is_prose(text))
                self.assertFalse(layout.flow_caption(block))
                path = Path(temp) / "source.pdf"
                source.save(path)
                raw, report = layout.typeset(path, {"pages": [{"number": 1, "blocks": [block]}]}, "简体中文")
                self.assertFalse(report["issues"], report["issues"])
                self.assertCountEqual(report["inline_math"][0]["matched"], [layout.normalized_inline_math("˙xn"), "P0"])
                with pymupdf.open(stream=raw, filetype="pdf") as output:
                    visible = "".join(chr(char[0]) for span in output[0].get_texttrace() if span["type"] != 3
                                      for char in span["chars"])
                    self.assertNotIn("ẋ", visible)
                    self.assertNotIn("_", visible)


if __name__ == "__main__":
    unittest.main()
