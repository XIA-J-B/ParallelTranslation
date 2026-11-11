import tempfile
import unittest
from pathlib import Path

import pymupdf

import pdf_layout as layout


class FootnoteMarkerTests(unittest.TestCase):
    def source_line(self, page, left, baseline, marker="a", size=10, math=False):
        prefix = "The value of the state is " if math else "The environment"
        page.insert_text((left, baseline), prefix, fontsize=size, fontname="tiro")
        x = left + pymupdf.get_text_length(prefix, fontsize=size, fontname="tiro")
        if math:
            page.insert_text((x, baseline), "x", fontsize=size, fontname="tiit")
            x += pymupdf.get_text_length("x", fontsize=size, fontname="tiit")
        page.insert_text((x, baseline - size * .35), marker, fontsize=size * .7, fontname="tiit")
        x += pymupdf.get_text_length(marker, fontsize=size * .7, fontname="tiit")
        page.insert_text((x, baseline), " is used for the study of the model.", fontsize=size, fontname="tiro")

    def style(self, page):
        lines = [line for block in page.get_text("dict")["blocks"] if block["type"] == 0
                 for line in block["lines"]]
        return {"lines": lines, "spans": [span for line in lines for span in line["spans"]]}

    def test_only_raised_prose_markers_become_footnotes(self):
        with pymupdf.open() as pdf:
            page = pdf.new_page()
            self.source_line(page, 40, 70, "a")
            self.source_line(page, 40, 100, "bc")
            self.source_line(page, 40, 130, "a", math=True)
            marks = layout.source_footnote_marks(self.style(page))
            self.assertEqual([item["marker"] for item in marks], ["a", "bc"])
            text = "公式 x^a 不变，环境^a 可用，软件^{b,c} 有说明；未知标记^z 保留。"
            markup, plain, labels, _ = layout.inline_math_markup(text, [], pymupdf.Archive(), footnotes=marks)
            self.assertEqual(markup.count("vertical-align:super"), 2)
            self.assertEqual(plain, "公式 x^a 不变，环境a 可用，软件b,c 有说明；未知标记^z 保留。")
            self.assertFalse(labels)

    def test_latin_translation_requires_the_original_word_anchor(self):
        with pymupdf.open() as pdf:
            page = pdf.new_page()
            self.source_line(page, 40, 70)
            marks = layout.source_footnote_marks(self.style(page))
            ranges = layout.translated_footnote_ranges("x^a and abc^a; environment^a", marks)
            self.assertEqual(len(ranges), 1)
            self.assertEqual(ranges[0]["start"], len("x^a and abc^a; environment"))

    def test_baseline_letters_do_not_authorize_caret_conversion(self):
        with pymupdf.open() as pdf:
            page = pdf.new_page()
            page.insert_text((40, 70), "The environment a is used for this experiment.", fontsize=10)
            self.assertFalse(layout.source_footnote_marks(self.style(page)))
            markup, plain, _, _ = layout.inline_math_markup("公式 x^a 和说明^a", [], pymupdf.Archive())
            self.assertEqual(plain, "公式 x^a 和说明^a")
            self.assertNotIn("vertical-align:super", markup)

    def test_markers_are_raised_in_export_across_columns_sizes_and_rotations(self):
        for columns, rotation, size in ((1, 0, 10), (2, 90, 9), (2, 180, 11), (1, 270, 10)):
            with self.subTest(columns=columns, rotation=rotation, size=size), tempfile.TemporaryDirectory() as temp:
                with pymupdf.open() as source:
                    page = source.new_page(width=720, height=500)
                    for column in range(columns):
                        self.source_line(page, 35 + column * 350, 100, size=size)
                    page.set_rotation(rotation)
                    blocks = []
                    lines = [line for native in page.get_text("dict")["blocks"] if native["type"] == 0
                             for line in native["lines"]]
                    for index, line in enumerate(lines):
                        box = pymupdf.Rect(line["bbox"]) * page.rotation_matrix
                        blocks.append({"id": f"prose-{index}", "text": "".join(span["text"] for span in line["spans"]),
                                       "translation": "此实验环境^a 用于研究模型的运行情况。", "target": "简体中文",
                                       "bbox": [box.x0 / page.rect.width, box.y0 / page.rect.height,
                                                box.x1 / page.rect.width, box.y1 / page.rect.height]})
                    path = Path(temp) / "source.pdf"
                    source.save(path)
                output, report = layout.typeset(path, {"pages": [{"number": 1, "blocks": blocks}]}, "简体中文")
                self.assertFalse(report["issues"], report["issues"])
                with pymupdf.open(stream=output, filetype="pdf") as result:
                    page = result[0]
                    self.assertEqual(page.rotation, rotation)
                    self.assertNotIn("^", page.get_text())
                    spans = [span for block in page.get_text("dict")["blocks"] if block["type"] == 0
                             for line in block["lines"] for span in line["spans"] if span["text"].strip()]
                    markers = [span for span in spans if span["text"].strip() == "a"]
                    self.assertEqual(len(markers), columns)
                    body = [span for span in spans if "环境" in span["text"]]
                    self.assertEqual(len(body), columns)
                    for marker in markers:
                        neighbor = min(body, key=lambda span: abs(span["bbox"][2] - marker["bbox"][0]))
                        self.assertAlmostEqual(marker["size"] / neighbor["size"], .7, delta=.01)
                        self.assertLess(marker["origin"][1], neighbor["origin"][1] - size * .2)


if __name__ == "__main__":
    unittest.main()
