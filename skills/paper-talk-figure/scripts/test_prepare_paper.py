"""Regression checks for preservation, page geometry and explicit extraction gaps."""
import hashlib
import importlib.util
import math
from pathlib import Path
import tempfile
import unittest

import pymupdf

spec = importlib.util.spec_from_file_location("prepare_paper", Path(__file__).with_name("prepare_paper.py"))
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class PreparePaperTest(unittest.TestCase):
    def test_varied_pages_keep_all_text_and_rotated_locations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "paper.pdf"
            pdf = pymupdf.open()
            for index, rotation in enumerate((0, 90, 180, 270)):
                page = pdf.new_page(width=540 + 20 * index, height=720 + 30 * index)
                page.insert_text((40, 90), f"LEFT-{rotation}")
                page.insert_text((300, 170), f"RIGHT-{rotation}")
                page.insert_text((40, 250), f"Caption-{rotation}", fontsize=9)
                page.set_rotation(rotation)
            pdf.new_page(width=410, height=610)  # A page without a text layer.
            pdf.save(source)
            pdf.close()
            original = source.read_bytes()
            data = helper.prepare(source, root / "out", "1-5", 0.5)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(data["source_sha256"], hashlib.sha256(original).hexdigest())
            self.assertEqual(data["page_count"], 5)
            for index, rotation in enumerate((0, 90, 180, 270)):
                page = data["pages"][index]
                text = "".join(block["text"] for block in page["blocks"])
                for label in ("LEFT", "RIGHT", "Caption"):
                    self.assertIn(f"{label}-{rotation}", text)
                self.assertEqual(page["rotation"], rotation)
                left = next(block for block in page["blocks"] if f"LEFT-{rotation}" in block["text"])
                x0, y0, x1, y1 = left["bbox_display_normalized"]
                self.assertTrue(all(math.isfinite(v) and 0 <= v <= 1 for v in (x0, y0, x1, y1)))
                # Independently known quadrants for an upper-left mark rotated with the page.
                if rotation in (0, 270):
                    self.assertLess(x1, 0.5)
                else:
                    self.assertGreater(x0, 0.5)
                if rotation in (0, 90):
                    self.assertLess(y1, 0.5)
                else:
                    self.assertGreater(y0, 0.5)
                render = pymupdf.Pixmap(str(root / "out" / "source-pages" / f"page-{index + 1:03d}.png"))
                self.assertAlmostEqual(render.width, page["width"] * 0.5, delta=1)
                self.assertAlmostEqual(render.height, page["height"] * 0.5, delta=1)
            self.assertFalse(data["pages"][-1]["blocks"])
            self.assertTrue(data["pages"][-1]["warnings"])
            snapshot = (root / "out" / "paper-source.json").read_bytes()
            with self.assertRaises(FileExistsError):
                helper.prepare(source, root / "out")
            self.assertEqual((root / "out" / "paper-source.json").read_bytes(), snapshot)

    def test_bad_options_do_not_write_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "one.pdf"
            with pymupdf.open() as pdf:
                pdf.new_page()
                pdf.save(source)
            for pages in ("0", "2", "2-1", "1-2-3"):
                with self.assertRaises(ValueError):
                    helper.prepare(source, root / "bad", pages)
            for scale in (0, float("nan"), 5):
                with self.assertRaises(ValueError):
                    helper.prepare(source, root / "bad", scale=scale)
            self.assertFalse((root / "bad").exists())


if __name__ == "__main__":
    unittest.main()
