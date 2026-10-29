import unittest

from speech.serving.text_segments import split_tts_text


class SplitTtsTextTests(unittest.TestCase):
    def test_splits_at_each_period(self):
        self.assertEqual(split_tts_text("Xin chào chị. Em tư vấn nhé."), ["Xin chào chị.", "Em tư vấn nhé."])

    def test_caps_each_segment_at_twenty_words(self):
        words = [f"từ{i}" for i in range(1, 46)]
        self.assertEqual(split_tts_text(" ".join(words) + "."), [" ".join(words[:20]), " ".join(words[20:40]), " ".join(words[40:]) + "."])

    def test_collapses_whitespace_and_repeated_periods(self):
        self.assertEqual(split_tts_text("  AirPure X...\n Mẫu  Y.  "), ["AirPure X.", "Mẫu Y."])

    def test_short_text_without_period_stays_single_segment(self):
        self.assertEqual(split_tts_text("Chị muốn nghe thêm không?"), ["Chị muốn nghe thêm không?"])


if __name__ == "__main__":
    unittest.main()
