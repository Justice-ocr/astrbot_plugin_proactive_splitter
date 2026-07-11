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


def test_qq_safe_unicode_math_stays_as_text():
    blocks = extract_content_blocks("结论如下：\n∫_0^1 x dx = 1/2\n结束。")
    assert len(blocks) == 1
    assert blocks[0].kind == "text"


def test_qq_safe_equations_and_symbols_stay_as_text():
    text = "圆面积：A = πr²\nx <= y\na + b -> c\n温度约为 20±2℃\n"
    blocks = extract_content_blocks(text)
    assert len(blocks) == 1
    assert blocks[0].kind == "text"


def test_hardware_recommendations_stay_as_qq_text():
    lines = [
        "频繁无故重启、报 hardware_ram 类错误 → 优先 RMA/换货",
        "默认：OCCT / Prime95 + AIDA",
        "7×24 开服：优先稳定，别赌体质；到手就做压力测试",
        "5600XT ≈ 5600X 的小幅提频版，对你这种 Fabric 原版主电很合适",
        "首选：DDR5-6000 32GB（16×2）CL30，带 AMD EXPO",
        "主板：B650 / B850 入门板即可，进 BIOS 打开 EXPO",
        "要单核尽量贴 7840HS，且只开服 → Ryzen 5 7500F",
    ]
    for line in lines:
        blocks = extract_content_blocks(line)
        assert len(blocks) == 1
        assert blocks[0].kind == "text"


def test_explicit_latex_command_is_promoted():
    blocks = extract_content_blocks(r"结果：\frac{1}{2}" + "\n")
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
