import unittest

from flow_automation import _mapear_cards_para_takes


class VideoDownloadMappingTests(unittest.TestCase):
    def test_maps_any_batch_size_from_reverse_gallery_order(self):
        for count in (1, 2, 8, 25, 60):
            old = [{"id": f"old-{i}"} for i in range(7)]
            new = [{"id": f"take-{i}"} for i in range(count, 0, -1)]
            mapped = _mapear_cards_para_takes(new + old, {c["id"] for c in old}, count)
            self.assertEqual(
                {take: card["id"] for take, card in mapped.items()},
                {take: f"take-{take}" for take in range(1, count + 1)},
            )

    def test_ignores_preexisting_cards(self):
        cards = [
            {"id": "take-3"}, {"id": "take-2"}, {"id": "take-1"},
            {"id": "unrelated-newer-test"}, {"id": "old-project-video"},
        ]
        mapped = _mapear_cards_para_takes(
            cards,
            {"unrelated-newer-test", "old-project-video"},
            3,
        )
        self.assertEqual([mapped[i]["id"] for i in (1, 2, 3)], ["take-1", "take-2", "take-3"])

    def test_refuses_to_guess_when_cards_are_missing(self):
        with self.assertRaisesRegex(RuntimeError, "Nenhum download foi iniciado"):
            _mapear_cards_para_takes([{"id": "take-1"}], set(), 2)

    def test_refuses_extra_new_cards_instead_of_guessing_latest_batch(self):
        cards = [
            {"id": "take-3"}, {"id": "take-2"}, {"id": "take-1"},
            {"id": "stale-retry"},
        ]
        with self.assertRaisesRegex(RuntimeError, "gerações extras"):
            _mapear_cards_para_takes(cards, set(), 3)


if __name__ == "__main__":
    unittest.main()
