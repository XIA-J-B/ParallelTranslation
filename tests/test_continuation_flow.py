import copy
import json
import unittest
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import app as service
from pdf_continuation import continuation_map, continuation_pairs

LONG = ("Learning based controllers are compared with analytical controllers on standard "
        "aerial vehicle tasks and the empirical protocol is described in detail here")
CONTINUATION = ("and analytical controllers like geometric controllers for trajectory "
                "tracking tasks across several aerial vehicle platforms")
TAIL = ("The desired position represents the end effector waypoint in the world frame and "
        "the desired velocity is obtained from the derivative of the trajectory the tuning")


def block(block_id, text, box):
    return {"id": block_id, "text": text, "bbox": box,
            "translation": "译文", "target": "简体中文"}


def page(number, blocks):
    return {"number": number, "width": 612.0, "height": 792.0, "blocks": blocks}


def two_column_document():
    left = [0.08, 0.0, 0.49, 1.0]
    right = [0.51, 0.0, 0.92, 1.0]
    return {"name": "synthetic.pdf", "pages": [
        page(1, [
            block("p1-l1", LONG, [left[0], 0.07, left[2], 0.30]),
            block("p1-l2", TAIL, [left[0], 0.70, left[2], 0.916]),
            block("p1-r1", CONTINUATION, [right[0], 0.074, right[2], 0.105]),
            block("p1-r2", LONG, [right[0], 0.11, right[2], 0.60]),
        ]),
        page(2, [
            block("p2-l1", "of a model-based controller is often a much more heuristic manual "
                           "procedure to achieve a good enough configuration", [left[0], 0.074, left[2], 0.12]),
            block("p2-l2", LONG, [left[0], 0.13, left[2], 0.55]),
        ]),
    ]}


class ContinuationDetectionTests(unittest.TestCase):
    def test_detects_column_and_page_continuations(self):
        pairs = continuation_pairs(two_column_document())
        found = {(item["block"], item["next_block"]) for item in pairs}
        self.assertIn(("p1-l2", "p1-r1"), found)
        self.assertIn(("p1-r2", "p2-l1"), found)

    def test_terminal_punctuation_or_capital_start_is_not_a_continuation(self):
        document = two_column_document()
        document["pages"][0]["blocks"][1]["text"] = TAIL + "."
        document["pages"][0]["blocks"][2]["text"] = CONTINUATION[0].upper() + CONTINUATION[1:]
        document["pages"][0]["blocks"][3]["text"] = LONG + "."
        pairs = continuation_pairs(document)
        found = {(item["block"], item["next_block"]) for item in pairs}
        self.assertNotIn(("p1-l2", "p1-r1"), found)
        self.assertNotIn(("p1-r2", "p2-l1"), found)

    def test_caption_and_author_blocks_do_not_start_a_pair(self):
        document = two_column_document()
        # A caption at the top of the right column must not become its first
        # running-text block, so the left column tail cannot pair with it.
        document["pages"][0]["blocks"][2] = block(
            "p1-caption", "Fig. 1: Trajectory tracking results for the controllers",
            [0.51, 0.074, 0.92, 0.16])
        document["pages"][0]["blocks"].append(block(
            "p1-authors", "Jane Doe\nUniversity of Example\njane@example.org",
            [0.08, 0.93, 0.49, 0.99]))
        pairs = continuation_pairs(document)
        found = {(item["block"], item["next_block"]) for item in pairs}
        self.assertNotIn(("p1-l2", "p1-caption"), found)
        self.assertFalse(any(item["block"] == "p1-authors" for item in pairs))
        from pdf_continuation import _prose_block
        self.assertFalse(_prose_block(document["pages"][0]["blocks"][2]))
        self.assertFalse(_prose_block(document["pages"][0]["blocks"][-1]))

    def test_hints_mark_head_and_tail(self):
        hints = continuation_map(two_column_document())
        self.assertTrue(hints["p1-l2"]["continues"])
        self.assertEqual(hints["p1-r1"]["continues_from"], "p1-l2")
        self.assertEqual(hints["p1-l2"]["continues_to"], "p1-r1")

    def test_page_continuation_can_resume_below_a_float_but_not_a_new_heading(self):
        document = {"pages": [page(1, [block("head", LONG, [.1, .7, .9, .92])]),
                              page(2, [block("plot", "0 1 2 3", [.1, .06, .9, .25]),
                                       block("caption", "Fig. 2. Measured response.", [.1, .27, .9, .32]),
                                       block("tail", CONTINUATION, [.1, .34, .9, .5])])]}
        self.assertEqual(continuation_map(document)["tail"]["continues_from"], "head")
        document["pages"][1]["blocks"].insert(2, block("heading", "A new section", [.1, .325, .9, .34]))
        self.assertNotIn("tail", continuation_map(document))

    def test_no_pair_across_a_page_without_prose_or_an_unexplained_top_gap(self):
        document = {"pages": [page(1, [block("head", LONG, [.1, .7, .9, .92])]),
                              page(2, []), page(3, [block("tail", CONTINUATION, [.1, .07, .9, .3])])]}
        self.assertEqual(continuation_pairs(document), [])
        document["pages"].pop(1)
        document["pages"][1]["blocks"].insert(0, block("unrelated", "Page header", [.1, .07, .9, .09]))
        document["pages"][1]["blocks"][1]["bbox"] = [.1, .4, .9, .6]
        self.assertEqual(continuation_pairs(document), [])

    def test_legacy_reference_block_with_an_embedded_number_is_not_prose(self):
        from pdf_continuation import _prose_block
        item = block("legacy", LONG + '\n[27] A. Example, "Another title', [.1, .7, .5, .9])
        self.assertFalse(_prose_block(item))
        item['text'] = LONG + '\n[27]. The evidence is discussed in the following paragraph.'
        self.assertTrue(_prose_block(item))

    def test_ligature_at_the_start_of_a_page_continuation_is_comparison_only(self):
        document = {"pages": [page(1, [block("head", LONG, [.1, .7, .9, .92])]),
                              page(2, [block("tail", 'ﬁles contain inertial properties and are used by the simulator to describe the vehicles',
                                             [.1, .07, .9, .2])])]}
        before = copy.deepcopy(document)
        self.assertEqual(continuation_map(document)["tail"]["continues_from"], "head")
        self.assertEqual(document, before)

    def test_context_exposes_both_boundaries_without_foreign_language_translation(self):
        document = two_column_document()
        request = service.TranslateRequest(agent=service.AgentConfig(), target="简体中文")
        blocks = service.all_blocks(document)
        head = next(i for i, item in enumerate(blocks) if item["id"] == "p1-l2")
        tail = next(i for i, item in enumerate(blocks) if item["id"] == "p1-r1")
        context = service.continuation_context(document, head, request)
        self.assertTrue(context["continues"])
        self.assertEqual(context["next_source_head"], blocks[tail]["text"])
        self.assertEqual(context["next_block_id"], blocks[tail]["id"])
        blocks[head].update(translation="ancienne traduction", target="Français")
        self.assertEqual(service.continuation_context(document, tail, request)["previous_translation_tail"], "")
        before = copy.deepcopy(document)
        snapshot = service.document_snapshot(document)
        self.assertEqual(document, before)
        self.assertNotIn("continuations", document)
        self.assertEqual(snapshot["continuations"]["p1-r1"]["continues_from"], "p1-l2")

    def test_saved_predecessor_result_is_used_by_the_successor_request(self):
        document = two_column_document()
        document["id"] = "a" * 32
        agent = AsyncMock(side_effect=["此项依赖于调节", "控制器参数来完成。"])
        request = service.TranslateRequest(agent=service.AgentConfig())
        with patch.object(service, "load_doc", return_value=document), patch.object(service, "doc_dir", return_value=Path('.')), \
                patch.object(service, "save_doc"), patch.object(service, "invoke_agent", agent):
            asyncio.run(service.translate(document["id"], "p1-l2", request))
            asyncio.run(service.translate(document["id"], "p1-r1", request))
        prompt = agent.await_args_list[1].args[1]
        context = json.loads(prompt.split('以下 JSON 为待翻译内容与参考资料：\n')[1])
        self.assertEqual(context["previous_translation_tail"], "此项依赖于调节")
        self.assertEqual(context["previous_block_id"], "p1-l2")

    def test_batch_context_keeps_fragment_boundaries_on_each_item(self):
        document = two_column_document()
        document['id'] = 'a' * 32
        ids = ['p1-l2', 'p1-r1']
        agent = AsyncMock(return_value=json.dumps({'blocks': [
            {'id': key, 'translation': '片段译文'} for key in ids]}))
        with patch.object(service, 'load_doc', return_value=document), patch.object(service, 'doc_dir', return_value=Path('.')), \
                patch.object(service, 'save_doc'), patch.object(service, 'invoke_agent', agent):
            asyncio.run(service.translate_batch(document['id'], service.BatchTranslateRequest(
                agent=service.AgentConfig(), block_ids=ids)))
        context = json.loads(agent.await_args.args[1].split('参考资料与本次待翻译段落：\n')[1])
        self.assertNotIn('continues', context)
        self.assertNotIn('next_source_head', context)
        first, second = context['current_blocks']
        self.assertTrue(first['continues'])
        self.assertEqual(first['next_block_id'], second['id'])
        self.assertTrue(second['continuation'])
        self.assertEqual(second['previous_block_id'], first['id'])
        self.assertEqual(second['previous_translation_tail'], '译文')

    def test_prompt_context_carries_previous_source_and_translation(self):
        document = two_column_document()
        document["pages"][0]["blocks"][1]["translation"] = "涉及调参的结尾"
        request = service.TranslateRequest(agent=service.AgentConfig(), target="简体中文")
        blocks = service.all_blocks(document)
        index = next(i for i, item in enumerate(blocks) if item["id"] == "p1-r1")
        context = service.continuation_context(document, index, request)
        self.assertTrue(context["continuation"])
        self.assertTrue(context["previous_source_tail"].endswith("the tuning"))
        self.assertTrue(context["previous_translation_tail"].endswith("涉及调参的结尾"))
        self.assertNotIn("continuation", service.context_for(
            document, next(i for i, item in enumerate(blocks) if item["id"] == "p1-l1"), request))

    def test_ellipsis_added_only_when_source_has_none(self):
        self.assertTrue(service.introduces_ellipsis("sampled across", "在……中被随机采样"))
        self.assertTrue(service.introduces_ellipsis("sampled across", "在...中被随机采样"))
        self.assertFalse(service.introduces_ellipsis("sampled across …", "在……中被随机采样"))
        self.assertFalse(service.introduces_ellipsis("sampled across", "被随机采样"))


if __name__ == "__main__":
    unittest.main()
