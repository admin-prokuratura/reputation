import unittest

from datetime import datetime
from types import SimpleNamespace

from bot.services.reputation_detector import build_entries_from_message, extract_reputation


class ExtractReputationTests(unittest.TestCase):
    def test_negative_rep_applies_to_each_mentioned_user(self):
        text = "-rep @UserOne @UserTwo"
        result = extract_reputation(text)
        sentiments = {item.target: item.sentiment for item in result}
        self.assertEqual(sentiments, {"userone": "negative", "usertwo": "negative"})

    def test_positive_rep_applies_to_each_mentioned_user(self):
        text = "+rep @UserOne @UserTwo"
        result = extract_reputation(text)
        sentiments = {item.target: item.sentiment for item in result}
        self.assertEqual(sentiments, {"userone": "positive", "usertwo": "positive"})

    def test_negative_rep_when_sign_after_mentions(self):
        text = "@UserOne @UserTwo -rep"
        result = extract_reputation(text)
        sentiments = {item.target: item.sentiment for item in result}
        self.assertEqual(sentiments, {"userone": "negative", "usertwo": "negative"})

    def test_positive_and_negative_mentions_are_separated(self):
        text = "+rep @UserOne @UserTwo -rep @UserThree"
        result = extract_reputation(text)
        sentiments = {item.target: item.sentiment for item in result}
        self.assertEqual(sentiments, {"userone": "positive", "usertwo": "positive", "userthree": "negative"})

    def test_rep_variation_with_target_before_sign(self):
        text = "@UserOne + репутацию"
        result = extract_reputation(text)
        sentiments = {item.target: item.sentiment for item in result}
        self.assertEqual(sentiments, {"userone": "positive"})


class BuildEntriesFromMessageTests(unittest.TestCase):
    def _make_message(self, text: str, reply_user: SimpleNamespace | None = None):
        chat = SimpleNamespace(id=-100)
        author = SimpleNamespace(id=1, username="author", is_bot=False)
        reply = None
        if reply_user is not None:
            reply = SimpleNamespace(from_user=reply_user)
        return SimpleNamespace(
            text=text,
            caption=None,
            photo=[],
            video=None,
            document=None,
            animation=None,
            chat=chat,
            message_id=10,
            from_user=author,
            date=datetime.utcnow(),
            reply_to_message=reply,
        )

    def test_reply_with_positive_sign_only(self):
        reply_user = SimpleNamespace(id=99, username="TargetUser", is_bot=False)
        message = self._make_message("+реп", reply_user=reply_user)
        entries = build_entries_from_message(message)
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry.target, "targetuser")
        self.assertEqual(entry.sentiment, "positive")

    def test_reply_with_negative_sign_only_without_username(self):
        reply_user = SimpleNamespace(id=77, username=None, is_bot=False)
        message = self._make_message("- реп", reply_user=reply_user)
        entries = build_entries_from_message(message)
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry.target, "77")
        self.assertEqual(entry.sentiment, "negative")

    def test_skip_when_reply_user_is_bot(self):
        reply_user = SimpleNamespace(id=55, username="BotUser", is_bot=True)
        message = self._make_message("+реп", reply_user=reply_user)
        entries = build_entries_from_message(message)
        self.assertEqual(entries, [])


if __name__ == "__main__":
    unittest.main()
