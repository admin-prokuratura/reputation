from bot.utils.parsing import parse_rep_arguments


def test_parse_rep_arguments_without_inline_mode():
    assert parse_rep_arguments("/r @target") == ("@target", None)


def test_parse_rep_arguments_with_bot_mention():
    assert parse_rep_arguments("/r@mybot target") == ("target", None)


def test_parse_rep_arguments_full_command_with_chat():
    assert parse_rep_arguments('/rep@mybot target "Some Chat"') == (
        "target",
        "Some Chat",
    )
