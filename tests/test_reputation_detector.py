import unittest
from datetime import datetime
from types import SimpleNamespace

from bot.services.reputation_detector import build_entries_from_message, extract_reputation


class ExtractReputationTests(unittest.TestCase):
    def test_negative_rep_applies_to_each_mentioned_user(self) -> None:
        text = "-rep @UserOne @UserTwo"
        sentiments = {item.target: item.sentiment for item in extract_reputation(text)}
        self.assertEqual(sentiments, {"userone": "negative", "usertwo": "negative"})

    def test_positive_rep_applies_to_each_mentioned_user(self) -> None:
        text = "+rep @UserOne @UserTwo"
        sentiments = {item.target: item.sentiment for item in extract_reputation(text)}
        self.assertEqual(sentiments, {"userone": "positive", "usertwo": "positive"})

    def test_negative_rep_when_sign_after_mentions(self) -> None:
        text = "@UserOne @UserTwo -rep"
        sentiments = {item.target: item.sentiment for item in extract_reputation(text)}
        self.assertEqual(sentiments, {"userone": "negative", "usertwo": "negative"})

    def test_positive_and_negative_mentions_are_separated(self) -> None:
        text = "+rep @UserOne @UserTwo -rep @UserThree"
        sentiments = {item.target: item.sentiment for item in extract_reputation(text)}
        self.assertEqual(
            sentiments,
            {"userone": "positive", "usertwo": "positive", "userthree": "negative"},
        )

    def test_rep_variation_with_target_before_sign(self) -> None:
        text = "@UserOne + \u0440\u0435\u043f"
        sentiments = {item.target: item.sentiment for item in extract_reputation(text)}
        self.assertEqual(sentiments, {"userone": "positive"})

    def test_multiple_positive_signs_are_supported(self) -> None:
        text = "++rep @UserOne"
        sentiments = {item.target: item.sentiment for item in extract_reputation(text)}
        self.assertEqual(sentiments, {"userone": "positive"})

    def test_multiple_negative_signs_are_supported(self) -> None:
        text = "--rep @UserOne"
        sentiments = {item.target: item.sentiment for item in extract_reputation(text)}
        self.assertEqual(sentiments, {"userone": "negative"})

    def test_mixed_signs_resolve_to_majority(self) -> None:
        text = "+--rep @UserOne @UserTwo"
        sentiments = {item.target: item.sentiment for item in extract_reputation(text)}
        self.assertEqual(sentiments, {"userone": "negative", "usertwo": "negative"})


class BuildEntriesFromMessageTests(unittest.TestCase):
    def _make_message(
        self,
        text: str,
        reply_user: SimpleNamespace | None = None,
    ) -> SimpleNamespace:
        chat = SimpleNamespace(id=-100)
        author = SimpleNamespace(id=1, username="author", is_bot=False)
        reply = SimpleNamespace(from_user=reply_user) if reply_user else None
        return SimpleNamespace(
            text=text,
            caption=None,
            photo=[],
            video=None,
            document=None,
            animation=None,
            chat=chat,
            message_id=42,
            from_user=author,
            date=datetime.utcnow(),
            reply_to_message=reply,
        )

    def test_reply_with_positive_sign_only(self) -> None:
        reply_user = SimpleNamespace(id=99, username="TargetUser", is_bot=False)
        message = self._make_message("+\u0440\u0435\u043f", reply_user=reply_user)
        entries = build_entries_from_message(message)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].target, "targetuser")
        self.assertEqual(entries[0].sentiment, "positive")

    def test_reply_with_negative_sign_only_without_username(self) -> None:
        reply_user = SimpleNamespace(id=77, username=None, is_bot=False)
        message = self._make_message("- \u0440\u0435\u043f", reply_user=reply_user)
        entries = build_entries_from_message(message)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].target, "77")
        self.assertEqual(entries[0].sentiment, "negative")

    def test_skip_when_reply_user_is_bot(self) -> None:
        reply_user = SimpleNamespace(id=55, username="BotUser", is_bot=True)
        message = self._make_message("+\u0440\u0435\u043f", reply_user=reply_user)
        entries = build_entries_from_message(message)
        self.assertEqual(entries, [])

    def test_reply_with_multiple_positive_signs(self) -> None:
        reply_user = SimpleNamespace(id=101, username="Stacked", is_bot=False)
        message = self._make_message("++rep", reply_user=reply_user)
        entries = build_entries_from_message(message)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].target, "stacked")
        self.assertEqual(entries[0].sentiment, "positive")

    def test_reply_with_multiple_negative_signs(self) -> None:
        reply_user = SimpleNamespace(id=202, username=None, is_bot=False)
        message = self._make_message("--rep", reply_user=reply_user)
        entries = build_entries_from_message(message)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].target, "202")
        self.assertEqual(entries[0].sentiment, "negative")


if __name__ == "__main__":
    unittest.main()
