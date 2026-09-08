import unittest

from trader.news import NewsSignal


class NewsTests(unittest.TestCase):
    def test_two_negative_headlines_can_block_entries(self):
        self.assertTrue(NewsSignal(-0.5, 1, 3, 4).blocks_new_positions)

    def test_one_negative_headline_does_not_block_entries(self):
        self.assertFalse(NewsSignal(-1.0, 0, 1, 1).blocks_new_positions)


if __name__ == "__main__":
    unittest.main()
