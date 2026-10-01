import unittest

from src.pronuncia import normalizar_pronuncia


class PronunciaTests(unittest.TestCase):
    def test_ciot_is_pronounced_as_a_word(self):
        self.assertEqual(normalizar_pronuncia("O CIOT foi emitido."), "O cioti foi emitido.")

    def test_spelled_acronyms_remain_uppercase(self):
        texto = normalizar_pronuncia("Consulte ANTT, RNTRC, IBS e CBS.")
        self.assertEqual(texto, "Consulte ANTT, RNTRC, IBS e CBS.")

    def test_longer_acronym_is_not_partially_replaced(self):
        self.assertEqual(normalizar_pronuncia("RNTRC"), "RNTRC")

    def test_only_word_like_acronym_is_adapted_in_mixed_sentence(self):
        texto = normalizar_pronuncia("Emitir o CIOT, ANTT, RNTRC, IBS e CBS.")
        self.assertEqual(texto, "Emitir o cioti, ANTT, RNTRC, IBS e CBS.")

    def test_unknown_acronym_is_preserved(self):
        self.assertEqual(normalizar_pronuncia("A sigla ABC permanece."), "A sigla ABC permanece.")

    def test_does_not_replace_inside_another_word(self):
        self.assertEqual(normalizar_pronuncia("CIOTização"), "CIOTização")


if __name__ == "__main__":
    unittest.main()
