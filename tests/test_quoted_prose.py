import pytest

from core.rich_content import build_split_pattern, smart_split_text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("第一句。第二句。第三句。", ["第一句。", "第二句。", "第三句。"]),
        ("“第一句。第二句。第三句。”", ["“第一句。", "第二句。", "第三句。”"]),
        ("‘第一句。第二句。’", ["‘第一句。", "第二句。’"]),
        ("“第一句。‘第二句。’第三句。”", ["“第一句。", "‘第二句。’", "第三句。”"]),
        ("“第一句。”“第二句。”", ["“第一句。”", "“第二句。”"]),
        ('"第一句。第二句。"', ['"第一句。', '第二句。"']),
        ("'第一句。第二句。'", ["'第一句。", "第二句。'"]),
        ("“只有一句。”", ["“只有一句。”"]),
        ("don't 第一句。第二句。", ["don't 第一句。", "第二句。"]),
        ('"don\'t 第一句。第二句。"', ["\"don't 第一句。", '第二句。"']),
        ("don’t 第一句。第二句。", ["don’t 第一句。", "第二句。"]),
        ("(o'ω'o) 第一句。第二句。", ["(o'ω'o) 第一句。", "第二句。"]),
        ("“第一句。第二句。", ["“第一句。", "第二句。"]),
        ("'第一句。第二句。", ["'第一句。", "第二句。"]),
        (
            "（括号里。不能切。）第一句。第二句。",
            ["（括号里。不能切。）第一句。", "第二句。"],
        ),
        (
            "“第一句（括号里。不能切）。第二句。”",
            ["“第一句（括号里。不能切）。", "第二句。”"],
        ),
        ("`代码。不能切。`第一句。第二句。", ["`代码。不能切。`第一句。", "第二句。"]),
        (
            "```python\nprint('代码。不能切。')\n```第一句。第二句。",
            ["```python\nprint('代码。不能切。')\n```第一句。", "第二句。"],
        ),
        (
            "<think>思考。不能切。</think>第一句。第二句。",
            ["<think>思考。不能切。</think>第一句。", "第二句。"],
        ),
        ("```未闭合代码。保持完整。", ["```未闭合代码。保持完整。"]),
        (
            '{"text":"内容。保持完整。"}第一句。第二句。',
            ['{"text":"内容。保持完整。"}第一句。', "第二句。"],
        ),
        ("", []),
    ],
)
def test_quoted_prose_splits_without_losing_characters(text, expected):
    pieces = smart_split_text(
        text, r"[。]+", max_segments=20, min_segment_length=10, balanced=False
    )
    assert pieces == expected
    assert "".join(pieces) == text


@pytest.mark.parametrize("mode", ["simple", "regex"])
@pytest.mark.parametrize("regex", [r"[。？！?!\n…]+", r"[。？！?!\n…]+[”’\"]*"])
def test_quote_splitting_uses_both_configuration_modes(mode, regex):
    pattern = build_split_pattern(mode, ["。", "？", "！", r"\n"], regex)
    text = "“第一句。第二句。第三句。”"
    assert smart_split_text(text, pattern, balanced=False) == [
        "“第一句。",
        "第二句。",
        "第三句。”",
    ]


def test_quoted_prose_respects_segment_cap_and_keeps_closing_quote():
    pieces = smart_split_text(
        "“第一句。第二句。第三句。”", r"[。]+", max_segments=2, balanced=False
    )
    assert pieces == ["“第一句。", "第二句。第三句。”"]


def test_zero_width_regex_does_not_stop_scanner_progress():
    text = "第一句。第二句。"
    assert smart_split_text(text, r"(?=。)", balanced=False) == [text]


def test_escaped_quotes_do_not_close_the_surrounding_quote():
    text = '"第一句包含\\"转义引号。第二句。"'
    pieces = smart_split_text(text, r"[。]+", balanced=False)
    assert pieces == ['"第一句包含\\"转义引号。', '第二句。"']
    assert "".join(pieces) == text
