import unittest

from bot.services.reputation_detector import extract_reputation


class ExtractReputationTests(unittest.TestCase):
    def test_negative_rep_applies_to_each_mentioned_user(self):
        text = "-rep @UserOne @UserTwo"
        result = extract_reputation(text)
        sentiments = {item.target: item.sentiment for item in result}
        self.assertEqual(sentiments, {"userone": "negative", "usertwo": "negative"})

    def test_does_not_add_extra_when_positive(self):
        text = "+rep @UserOne @UserTwo"
        result = extract_reputation(text)
        sentiments = [item.sentiment for item in result]
        targets = [item.target for item in result]
        self.assertEqual(sentiments, ["positive"])
        self.assertEqual(targets, ["userone"])

    def test_negative_rep_when_sign_after_mentions(self):
        text = "@UserOne @UserTwo -rep"
        result = extract_reputation(text)
        sentiments = {item.target: item.sentiment for item in result}
        self.assertEqual(sentiments, {"userone": "negative", "usertwo": "negative"})


if __name__ == "__main__":
    unittest.main()
