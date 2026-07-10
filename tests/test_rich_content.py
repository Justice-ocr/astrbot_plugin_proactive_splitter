from core.rich_content import extract_content_blocks, smart_split_text


def test_markdown_table_is_one_rich_block():
    text = "前言。\n| 名称 | 值 |\n| --- | ---: |\n| A | 1 |\n结尾。"
    blocks = extract_content_blocks(text)
    assert [block.kind for block in blocks] == ["text", "table", "text"]
    assert "| A | 1 |" in blocks[1].content


def test_display_and_inline_math_are_promoted():
    text = "普通说明。\n$$\nE = mc^2\n$$\n因此 $x^2 + y^2 = z^2$。\n"
    blocks = extract_content_blocks(text)
    assert [block.kind for block in blocks] == ["text", "math"]
    assert "E = mc^2" in blocks[1].content
    assert "$x^2 + y^2 = z^2$" in blocks[1].content


def test_unicode_formula_line_is_promoted():
    blocks = extract_content_blocks("结论如下：\n∫_0^1 x dx = 1/2\n结束。")
    assert [block.kind for block in blocks] == ["text", "math", "text"]


def test_common_pi_and_superscript_formula_is_promoted():
    blocks = extract_content_blocks("圆面积：A = πr²\n")
    assert len(blocks) == 1
    assert blocks[0].kind == "math"


def test_code_fence_does_not_trigger_math_detection():
    blocks = extract_content_blocks("```python\nprice = '$5'\n```\n普通文本。")
    assert len(blocks) == 1
    assert blocks[0].kind == "text"


def test_smart_split_preserves_parenthesized_text():
    pieces = smart_split_text(
        "第一句（括号里有。不能切）。第二句。第三句。",
        r"[。]+",
        max_segments=3,
        min_segment_length=2,
        balanced=False,
    )
    assert "括号里有。不能切" in pieces[0]
    assert len(pieces) == 3


def test_smart_split_respects_protected_next_word():
    pieces = smart_split_text(
        "第一句。 Provider 仍属于上一段。第二句。",
        r"[。]+",
        max_segments=5,
        min_segment_length=1,
        balanced=False,
        no_split_around=["Provider"],
    )
    assert pieces[0].startswith("第一句。 Provider")
