from core.rich_content import (
    calculate_math_ratio,
    extract_content_blocks,
    normalize_math_markdown,
    split_rich_markdown_for_render,
    smart_split_text,
)


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


def test_plain_square_brackets_around_latex_become_one_math_block():
    text = "因为条件成立，所以\n[\n\\frac{1}{a} > \\frac{1}{b} > 0\n]\n结论成立。"
    blocks = extract_content_blocks(text)
    assert [block.kind for block in blocks] == ["text", "math", "text"]
    assert blocks[1].content.strip() == r"\frac{1}{a} > \frac{1}{b} > 0"


def test_unwrapped_latex_expression_gets_display_delimiters():
    normalized = normalize_math_markdown(r"\frac{1}{a} > \frac{1}{b} > 0")
    assert normalized == "$$\n\\frac{1}{a} > \\frac{1}{b} > 0\n$$"


def test_parenthesis_and_bracket_latex_delimiters_are_normalized_for_pillowmd():
    source = r"行内 \(x^2\)，行间 \[\frac{1}{2}\]"
    normalized = normalize_math_markdown(source)
    assert "$x^2$" in normalized
    assert "$$\n\\frac{1}{2}\n$$" in normalized


def test_latex_environment_gets_display_delimiters():
    source = "\\begin{aligned}\nx &= y\\\\\ny &= z\n\\end{aligned}"
    normalized = normalize_math_markdown(source)
    assert normalized.startswith("$$\n\\begin{aligned}")
    assert normalized.endswith("\\end{aligned}\n$$")


def test_unwrapped_latex_inside_chinese_text_gets_inline_delimiters():
    source = r"由 (0<a<b) 得 (0<\frac{a}{b}<1)，于是 (\left(\frac{a}{b}\right)^n\to 0)。"
    normalized = normalize_math_markdown(source)
    assert "$(0<\\frac{a}{b}<1)$" in normalized
    assert "$(\\left(\\frac{a}{b}\\right)^n\\to 0)$" in normalized


def test_dfrac_sentence_is_recognized_and_normalized():
    source = r"这里较大的是 (\dfrac{1}{a})，故极限为 (\dfrac{1}{a})。"
    blocks = extract_content_blocks(source)
    assert blocks[0].kind == "math"
    normalized = normalize_math_markdown(blocks[0].content)
    assert "$(\\dfrac{1}{a})$" in normalized


def test_math_ratio_ignores_qq_safe_equations():
    assert calculate_math_ratio("型号 i5-12400F，性能约等于 R5 5600X。") == 0


def test_math_ratio_counts_detected_formula_content():
    ratio = calculate_math_ratio("说明文字。\n$$x^2+y^2=z^2$$\n结论。")
    assert 0.5 < ratio < 0.9


def test_math_ratio_does_not_count_the_whole_prose_line():
    ratio = calculate_math_ratio("这是一段较长的普通说明，只有这里是公式 $x^2+y^2=z^2$，后面仍是说明。")
    assert 0.2 < ratio < 0.6


def test_rich_markdown_split_keeps_math_and_table_atomic():
    text = (
        "第一段说明。" * 20
        + "\n\n"
        + "$$\n\\frac{1}{a}+\\frac{1}{b}=1\n$$\n\n"
        + "| 项目 | 值 |\n| --- | --- |\n| A | 1 |\n\n"
        + "最后一段说明文字比较长，需要进入下一张图片。" * 12
    )
    chunks = split_rich_markdown_for_render(text, 200)
    assert len(chunks) >= 3
    assert any("\\frac{1}{a}" in chunk for chunk in chunks)
    assert any("| --- | --- |" in chunk for chunk in chunks)
    assert all("\\frac{1}{a}" not in chunk or "\\frac{1}{b}" in chunk for chunk in chunks)


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
