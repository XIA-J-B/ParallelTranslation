import copy
import tempfile
import unittest
from collections import Counter
from pathlib import Path

import pymupdf

import pdf_layout as layout
from pdf_flow import visible_drawings


class ColumnSourceSizeTests(unittest.TestCase):
    def fixture(self, columns=1, rotation=0, linked=False, overflow=False, density=(1, 1), last_leading=1.2):
        pdf = pymupdf.open()
        page = pdf.new_page(width=340 if columns == 1 else 650, height=500)
        figures = []
        for column in range(columns):
            left = 35 + column * 315
            figure = pymupdf.Rect(left, 30, left + 245, 62)
            page.draw_rect(figure, fill=(.3, .5, .8), color=(.1, .2, .4))
            figures.append(figure)
            first = ("The surrounding context describes the controller and the conditions of this experiment. "
                     "The measured states and commands are used to compare the behavior of the model. "
                     "The results provide evidence for the following analysis.")
            self.assertGreaterEqual(page.insert_textbox((left, 80, left + 245, 142), first,
                                    fontname="tiro", fontsize=10, lineheight=1.2), 0)
            page.insert_text((left + 50, 157), "u = x + 2", fontsize=10, fontname="tiro")
            page.insert_text((left + 225, 157), "(4)", fontsize=10, fontname="tiro")
            body = "The workflow uses several inputs and an independent estimate for every robot in the experiment."
            self.assertGreaterEqual(page.insert_textbox((left, 174, left + 245, 201), body,
                                    fontname="tiro", fontsize=10, lineheight=1.2), 0)
            for index, command in enumerate(("$ python3 run.py --value 0.125", "  --output ./results/example")):
                top = 207 + index * 10
                page.draw_rect((left, top, left + 245, top + 10), color=None, fill=(.94, .94, .94))
                page.insert_text((left + 1, top + 8), command, fontsize=8, fontname="cour")
            if linked:
                page.insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(left, 207, left + 245, 217),
                                  "uri": "https://example.org/command"})
            last = ("The following discussion describes the interpretation of all of these results and their limitations. "
                    "The observed behavior is consistent with the assumptions used in the experiment. "
                    "The proposed method can be examined in additional conditions without changing the definition of the task. "
                    "The same evaluation is used for every model.")
            self.assertGreaterEqual(page.insert_textbox((left, 240, left + 245, 350), last,
                                    fontname="tiro", fontsize=10, lineheight=last_leading), 0)
        page.set_rotation(rotation)
        blocks = []
        for index, native in enumerate(page.get_text("dict")["blocks"]):
            if native["type"] != 0:
                continue
            text = "\n".join("".join(span["text"] for span in line["spans"]) for line in native["lines"])
            translated = text
            if text.startswith("The surrounding"):
                translated = "前文说明控制器、实验条件和需要比较的模型行为。" * density[0]
            elif text.startswith("The workflow"):
                translated = ("该工作流使用一个具有二十五个输入的集中式模型，以及两个具有十二个输入的独立控制模型。"
                              "每个模型都包含两个大小为二百五十六的隐藏层，并采用指定激活函数以完成实验中的状态估计。")
                if overflow:
                    translated *= 30
            elif text.startswith("The following"):
                translated = "后续讨论解释实验结果和局限，并在相同条件下评价各个模型。" * density[1]
            box = pymupdf.Rect(native["bbox"]) * page.rotation_matrix
            blocks.append({"id": f"region-{index}", "text": text, "translation": translated, "target": "简体中文",
                           "bbox": [box.x0 / page.rect.width, box.y0 / page.rect.height,
                                    box.x1 / page.rect.width, box.y1 / page.rect.height]})
        return pdf, {"pages": [{"number": 1, "blocks": blocks}]}, figures

    def render(self, **options):
        source, document, figures = self.fixture(**options)
        self.addCleanup(source.close)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "source.pdf"
            source.save(path)
            original_bytes = path.read_bytes()
            snapshot = copy.deepcopy(document)
            raw, report = layout.typeset(path, document, "简体中文")
            self.assertEqual(path.read_bytes(), original_bytes)
            self.assertEqual(document, snapshot)
        result = pymupdf.open(stream=raw, filetype="pdf")
        self.addCleanup(result.close)
        return source, result, document, report, figures

    def test_original_size_moves_complete_code_and_formula_across_columns_and_rotations(self):
        for columns, rotation in ((1, 0), (2, 90), (2, 180), (1, 270)):
            with self.subTest(columns=columns, rotation=rotation):
                source, result, document, report, figures = self.render(columns=columns, rotation=rotation)
                bodies = [block for block in document["pages"][0]["blocks"] if block["text"].startswith("The workflow")]
                self.assertTrue(bodies)
                self.assertTrue(all(block["id"] in report["placements"] for block in bodies), report["issues"])
                flows = [item for item in report["flow"] if item.get("spacing_reason")]
                self.assertTrue(flows)
                self.assertTrue(all(.88 <= item["gap_factor"] <= 1 for item in flows))
                self.assertTrue(all(item["gap"] >= 1.59 for item in flows))  # 2pt ink gap minus two 0.2pt crops.
                records = [entry for entry in report["typography"] if any(block["id"] in entry["blocks"] for block in bodies)]
                self.assertTrue(all(entry["scale"] == 1 and entry["reason"] == "column-source-size" for entry in records))
                self.assertTrue(all(font["size"] == 10 for entry in records for font in entry["fonts"]))
                text = result[0].get_text()
                self.assertEqual(text.count("$ python3 run.py --value 0.125"), columns)
                self.assertEqual(text.count("--output ./results/example"), columns)
                self.assertEqual(text.count("u = x + 2"), columns)
                self.assertEqual(text.count("(4)"), columns)
                code_blocks = [block for block in document["pages"][0]["blocks"] if block["text"].startswith("$ python3")]
                self.assertTrue(all(block["id"] in report["original_placements"] for block in code_blocks))
                chinese = lambda value: Counter(char for char in value if "\u3400" <= char <= "\u9fff")
                expected = chinese("".join(block["translation"] for block in document["pages"][0]["blocks"]))
                self.assertEqual(chinese(text), expected)
                self.assertEqual(result[0].rotation, rotation)
                source[0].set_rotation(0)
                result[0].set_rotation(0)
                for figure in figures:
                    self.assertEqual(source[0].get_pixmap(clip=figure, matrix=pymupdf.Matrix(3, 3)).samples,
                                     result[0].get_pixmap(clip=figure, matrix=pymupdf.Matrix(3, 3)).samples)
                gray = [drawing for drawing in visible_drawings(result[0])
                        if drawing.get("fill") and max(abs(c - .94) for c in drawing["fill"]) < .001]
                self.assertEqual(len(gray), columns * 2)
                self.assertTrue(all(abs(drawing["rect"].width - 245) < .01 and abs(drawing["rect"].height - 10) < .01
                                    for drawing in gray))

    def test_linked_code_stays_fixed_when_surrounding_prose_reflows(self):
        source, result, document, report, _ = self.render(linked=True)
        code = next(block for block in document["pages"][0]["blocks"] if block["text"].startswith("$ python3"))
        self.assertNotIn(code["id"], report["placements"])
        clip = pymupdf.Rect(35, 207, 280, 227)
        self.assertEqual(source[0].get_pixmap(clip=clip, matrix=pymupdf.Matrix(3, 3)).samples,
                         result[0].get_pixmap(clip=clip, matrix=pymupdf.Matrix(3, 3)).samples)
        original = next(link for link in source[0].get_links() if link.get("uri"))
        current = next(link for link in result[0].get_links() if link.get("uri") == original["uri"])
        self.assertEqual(current["from"], original["from"])

    def test_tight_segment_uses_only_bounded_source_gap_compression(self):
        _, result, document, report, _ = self.render(density=(3, 4), last_leading=1.26)
        flows = [item for item in report["flow"] if item.get("spacing_reason")]
        self.assertTrue(flows)
        self.assertTrue(all(.88 <= item["gap_factor"] < 1 for item in flows))
        for item in flows:
            self.assertGreaterEqual(item["actual_ink_gap"], 2)
            self.assertGreaterEqual(item["actual_ink_gap"], item["source_ink_gap"] * .88)
            self.assertAlmostEqual(item["gap"] + item["ink_padding"], item["actual_ink_gap"], places=4)
        self.assertFalse(any(item["kind"] == "font_size" for item in report["issues"]))
        cjk = lambda text: Counter(char for char in text if "\u3400" <= char <= "\u9fff")
        self.assertEqual(cjk(result[0].get_text()), cjk("".join(block["translation"]
                                                             for block in document["pages"][0]["blocks"])))

    def test_failed_column_plan_does_not_move_original_code_or_drop_text(self):
        source, result, document, report, _ = self.render(overflow=True)
        body = next(block for block in document["pages"][0]["blocks"] if block["text"].startswith("The workflow"))
        self.assertNotIn(body["id"], report["placements"])
        self.assertTrue(any(item["block_id"] == body["id"] and item["kind"] == "font_size" for item in report["issues"]))
        clip = pymupdf.Rect(35, 207, 280, 227)
        self.assertEqual(source[0].get_pixmap(clip=clip, matrix=pymupdf.Matrix(3, 3)).samples,
                         result[0].get_pixmap(clip=clip, matrix=pymupdf.Matrix(3, 3)).samples)
        self.assertEqual(result[0].get_text().count("$ python3 run.py --value 0.125"), 1)


if __name__ == "__main__":
    unittest.main()
