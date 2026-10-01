import unittest

import flow_automation as flow
from flow_automation import _prompt_com_regras_visuais, _variacao_prompt


class PromptVisualRulesTests(unittest.TestCase):
    def test_vertical_entrypoint_normalizes_ratio_in_prompt(self):
        original_ratio = flow.ASPECT_RATIO
        try:
            flow.ASPECT_RATIO = "9:16"
            prompt = _prompt_com_regras_visuais("Educational illustration, 16:9.")
            self.assertIn("9:16", prompt)
            self.assertNotIn("16:9", prompt)
        finally:
            flow.ASPECT_RATIO = original_ratio

    def test_pure_white_coringa_is_a_color_field_not_a_board(self):
        prompt = _prompt_com_regras_visuais(
            "Pure solid white background filling the entire frame, #FFFFFF.",
            coringa=True,
        )
        self.assertIn("filling every pixel", prompt)
        self.assertIn("not a board", prompt)
        self.assertIn("No frame", prompt)

    def test_regular_image_requires_visible_text_in_portuguese(self):
        prompt = _prompt_com_regras_visuais("Draw BUY and SELL order cards.")
        self.assertIn("Brazilian Portuguese", prompt)
        self.assertIn("Translate every English label", prompt)

    def test_white_retry_never_requests_canvas_or_slide_object(self):
        original = "Pure solid white background, completely blank empty canvas."
        for tentativa in (1, 2, 3):
            retry = _variacao_prompt(original, tentativa).lower()
            self.assertNotIn("presentation slide", retry)
            self.assertNotIn("art canvas", retry)
            self.assertIn("uniform", retry)


if __name__ == "__main__":
    unittest.main()
