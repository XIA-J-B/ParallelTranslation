"""Source style, paragraph boundaries and safe column space remain independent."""
import copy
import tempfile
import unittest
from pathlib import Path

import pymupdf

import pdf_layout
from pdf_flow import caption


def native(text, box, size=10, font="Times-Roman"):
    return {"type": 0, "bbox": box, "lines": [{"bbox": box, "dir": (1, 0), "spans": [
        {"text": text, "bbox": box, "font": font, "size": size, "color": 0, "flags": 0}]}]}


def saved(items, width=400, height=400):
    return [{"id": str(index), "text": "\n".join("".join(s["text"] for s in line["spans"])
                                                        for line in item["lines"]),
             "bbox": [item["bbox"][0] / width, item["bbox"][1] / height,
                      item["bbox"][2] / width, item["bbox"][3] / height],
             "translation": "正文保持原有字号与完整段落。", "target": "简体中文"}
            for index, item in enumerate(items)]


class TypographicConsistencyTests(unittest.TestCase):
    def test_running_figure_references_are_body_not_captions(self):
        for text in ("Figure 6 plots the position of the vehicle during the experiment.",
                     "Table 2 shows the results of the proposed method in our study."):
            self.assertFalse(caption({"text": text}))
            self.assertTrue(pdf_layout.body_flow_candidate({"text": text}, {"_list_structure": None}))
        for text in ("Figure 6: The vehicle position.", "Fig. 6. The vehicle position.",
                     "TABLE II\nMEASURED PERFORMANCE", "图 6：车辆位置"):
            self.assertTrue(caption({"text": text}), text)
        item = native("Figure 6 shows the model for the control of a robot.", [50, 50, 350, 62])
        style, _ = pdf_layout.inspect_block([item], pymupdf.Rect(item["bbox"]))
        alignment, _, _ = pdf_layout.source_paragraph_style(
            style, pymupdf.Rect(item["bbox"]), item["lines"][0]["spans"][0]["text"], 400)
        self.assertEqual(alignment, "left")

    def test_touching_font_frames_do_not_merge_indented_paragraphs(self):
        with pymupdf.open() as pdf:
            page = pdf.new_page(width=400, height=400)
            prose = "The method is useful for the control of a robot in the experiment."
            items = [native(prose, [50, 50, 350, 80]), native(prose, [50, 79.4, 350, 110])]
            items[1]["lines"][0]["bbox"] = [60, 79.4, 350, 92]
            # One inline mathematical font elsewhere must not justify joining
            # two independent paragraphs whose padded glyph frames touch.
            items[0]["lines"][0]["spans"].append(
                {"text": "x", "font": "CMMI10", "size": 10, "flags": 0, "color": 0,
                 "bbox": [90, 55, 97, 65]})
            blocks = saved(items)
            before = copy.deepcopy(blocks)
            grouped = pdf_layout.layout_blocks(page, {"blocks": blocks}, items, "简体中文")
            self.assertEqual(len(grouped), 2)
            self.assertEqual(blocks, before)

    def test_full_width_table_stops_before_fragmented_two_column_prose(self):
        with pymupdf.open() as pdf:
            page = pdf.new_page(width=600, height=800)
            items = [native("TABLE I\nMEASUREMENTS", [200, 30, 400, 50], 8)]
            for y in (65, 78, 91, 104):
                for column in range(5):
                    x = 40 + column * 110
                    items.append(native("Value", [x, y, x + 35, y + 9], 8))
            items.append(native("The method is useful for the control of a robot.", [320, 117, 560, 129]))
            for index, word in enumerate(("The", "method", "is", "useful", "for", "control")):
                x = 40 + index * 38
                items.append(native(word, [x, 117, x + 30, 129]))
            regions = pdf_layout.table_regions(page, items)
            self.assertEqual(len(regions), 1)
            self.assertLess(regions[0].y1, 117)

    def test_small_caps_caption_continuation_uses_one_nominal_size(self):
        with pymupdf.open() as pdf:
            page = pdf.new_page(width=400, height=400)
            first = native("TABLE II\nCPU PERFORMANCE", [50, 50, 350, 70], 8)
            second = native("WITH PARALLEL ENVIRONMENTS", [65, 72, 335, 80], 6.4)
            blocks = saved([first, second])
            blocks[0]["translation"] = "表 II\nCPU 性能"
            blocks[1]["translation"] = "使用并行环境"
            grouped = pdf_layout.layout_blocks(page, {"blocks": blocks}, [first, second], "简体中文")
            self.assertEqual(len(grouped), 1)
            self.assertEqual(grouped[0]["_members"], ["0", "1"])
            self.assertEqual(grouped[0]["_nominal_size"], 8)
            self.assertTrue(caption(grouped[0]))

    def test_long_cell_with_table_font_and_axis_stays_inside_table(self):
        with pymupdf.open() as pdf:
            page = pdf.new_page(width=600, height=800)
            items = [native("TABLE I\nMEASUREMENTS", [200, 30, 400, 50], 8)]
            for y in (65, 78, 91, 104):
                for x in (40, 350, 490):
                    items.append(native("Value", [x, y, x + 35, y + 9], 8))
            items.append(native("The detailed description of this method belongs to the table cell.",
                                [40, 117, 280, 126], 8))
            items.extend(native("Value", [x, 117, x + 35, 126], 8) for x in (350, 490))
            regions = pdf_layout.table_regions(page, items)
            self.assertEqual(len(regions), 1)
            self.assertGreaterEqual(regions[0].y1, 126)

    def test_numbered_run_in_label_can_share_body_space_but_real_list_cannot(self):
        block = {"text": "1) Dynamics: The model is used for the control of a robot in motion."}
        self.assertTrue(pdf_layout.body_flow_candidate(block, {"_list_structure": None}))
        self.assertFalse(pdf_layout.body_flow_candidate(block, {"_list_structure": [{"marker": "1)"}]}))

    def test_long_translated_heading_uses_safe_column_width_at_source_size(self):
        with tempfile.TemporaryDirectory() as folder, pymupdf.open() as pdf:
            page = pdf.new_page(width=400, height=400)
            page.insert_text((50, 60), "B. Dynamics", fontname="tiit", fontsize=10)
            page.insert_text((50, 85), "The method is useful for the control of a robot in motion.",
                             fontname="tiro", fontsize=10)
            items = page.get_text("dict")["blocks"]
            blocks = saved(items)
            blocks[0]["translation"] = "B. 飞行器的动力学建模"
            blocks[1]["translation"] = "该方法用于控制运动中的机器人。"
            source = Path(folder) / "source.pdf"
            pdf.save(source)
            raw, report = pdf_layout.typeset(source, {"pages": [{"number": 1, "blocks": blocks}]}, "简体中文")
        self.assertIn("0", report["placements"], report["issues"])
        with pymupdf.open(stream=raw, filetype="pdf") as result:
            spans = [span for block in result[0].get_text("dict")["blocks"] for line in block["lines"]
                     for span in line["spans"] if "飞行器" in span["text"]]
            self.assertTrue(spans)
            self.assertAlmostEqual(spans[0]["size"], 10, places=2)

    def test_visible_font_report_ignores_hidden_math_search_layer(self):
        with pymupdf.open() as pdf:
            page = pdf.new_page(width=400, height=400)
            page.insert_text((50, 70), "Visible body", fontsize=10)
            page.insert_text((50, 70), "hidden math", fontsize=3, render_mode=3)
            details = pdf_layout.visible_typography(page, [({"id": "body"}, {"size": 10},
                {"rect": [40, 40, 200, 90], "scale": 1, "font_reason": "source-size"})], 1)
            self.assertEqual({item["size"] for item in details[0]["fonts"]}, {10})
            self.assertEqual(sum(item["characters"] for item in details[0]["fonts"]), len("Visiblebody"))


if __name__ == "__main__":
    unittest.main()
