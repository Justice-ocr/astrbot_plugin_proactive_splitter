"""Pure helpers for recognizing rich Markdown and splitting ordinary text."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ContentBlock:
    kind: str
    content: str


_TABLE_SEPARATOR_RE = re.compile(
    r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$"
)
_INLINE_MATH_RE = re.compile(
    r"(?<!\\)\$(?!\s|\$).+?(?<!\s|\\)\$|\\\(.+?\\\)", re.DOTALL
)
_LATEX_COMMAND_RE = re.compile(
    r"\\(?:d?frac|tfrac|sqrt|sum|prod|int|lim|log|sin|cos|tan|alpha|beta|"
    r"gamma|theta|lambda|mu|pi|sigma|phi|omega|begin|end|left|right|cdot|"
    r"times|div|pm|leq?|geq?|neq?|to|infty|overline|underline|vec|hat|bar|"
    r"text|mathrm)\b"
)
_CJK_OR_PUNCT_RE = re.compile(r"[\u3400-\u9fff，。；：！？、]")
_NON_CJK_SEGMENT_RE = re.compile(r"[^\u3400-\u9fff，。；：！？、]+")
_EXPLICIT_MATH_SPAN_RE = re.compile(
    r"(?<!\\)\$\$.+?(?<!\\)\$\$|"
    r"(?<![\\$])\$(?!\$).+?(?<![\\$])\$(?!\$)|"
    r"\\\(.+?\\\)|\\\[.+?\\\]|"
    r"\\begin\{([^}]+)\}.+?\\end\{\1\}",
    re.DOTALL,
)


def _is_table_start(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    header = lines[index].strip()
    separator = lines[index + 1].strip()
    return "|" in header and bool(_TABLE_SEPARATOR_RE.match(separator))


def _is_table_row(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and "|" in stripped


def _display_math_end(stripped: str) -> str | None:
    if stripped.startswith("$$"):
        return "$$"
    if stripped.startswith(r"\["):
        return r"\]"
    match = re.match(r"\\begin\{([^}]+)\}", stripped)
    if match:
        return rf"\end{{{match.group(1)}}}"
    return None


def contains_math(text: str) -> bool:
    """Return whether text contains explicit LaTeX that QQ cannot render."""
    stripped = text.strip()
    if not stripped:
        return False
    if _INLINE_MATH_RE.search(text):
        return True
    return bool(_LATEX_COMMAND_RE.search(text))


def normalize_math_markdown(text: str) -> str:
    """Add delimiters to explicit but unwrapped LaTeX before MathJax rendering."""
    stripped = text.strip()
    if not stripped:
        return text
    stripped = re.sub(
        r"\\\[(.+?)\\\]",
        lambda match: f"$$\n{match.group(1).strip()}\n$$",
        stripped,
        flags=re.DOTALL,
    )
    stripped = re.sub(
        r"\\\((.+?)\\\)",
        lambda match: f"${match.group(1).strip()}$",
        stripped,
        flags=re.DOTALL,
    )
    if _INLINE_MATH_RE.search(stripped) or stripped.startswith("$$"):
        return stripped
    if re.match(r"\\begin\{[^}]+\}", stripped):
        return f"$$\n{stripped}\n$$"
    if not _LATEX_COMMAND_RE.search(stripped):
        return stripped

    if not _CJK_OR_PUNCT_RE.search(stripped):
        return f"$$\n{stripped}\n$$"

    def wrap_latex_segment(match: re.Match[str]) -> str:
        segment = match.group(0)
        if not _LATEX_COMMAND_RE.search(segment):
            return segment
        leading = segment[: len(segment) - len(segment.lstrip())]
        trailing = segment[len(segment.rstrip()) :]
        content = segment.strip()
        return f"{leading}${content}${trailing}"

    return _NON_CJK_SEGMENT_RE.sub(wrap_latex_segment, stripped)


def calculate_math_ratio(text: str) -> float:
    """Return the share of non-whitespace reply characters in math blocks."""
    total = sum(1 for char in text if not char.isspace())
    if total == 0:
        return 0.0
    math_weight = 0
    for block in extract_content_blocks(text):
        if block.kind != "math":
            continue
        matches = list(_EXPLICIT_MATH_SPAN_RE.finditer(block.content))
        if matches:
            math_weight += sum(
                sum(1 for char in match.group(0) if not char.isspace())
                for match in matches
            )
            continue
        segments = [
            match.group(0)
            for match in _NON_CJK_SEGMENT_RE.finditer(block.content)
            if _LATEX_COMMAND_RE.search(match.group(0))
        ]
        math_weight += sum(
            sum(1 for char in segment if not char.isspace()) for segment in segments
        )
    return min(1.0, math_weight / total)


def _split_oversized_text(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    pieces: list[str] = []
    remaining = text
    while len(remaining) > max_chars:
        window = remaining[: max_chars + 1]
        candidates = [
            window.rfind(separator)
            for separator in ("\n\n", "\n", "。", "！", "？", ";", "；", ". ")
        ]
        split_at = max(candidates)
        if split_at < max_chars // 3:
            split_at = max_chars
        else:
            split_at += 2 if window[split_at : split_at + 2] in {"\n\n", ". "} else 1
        pieces.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].lstrip()
    if remaining.strip():
        pieces.append(remaining.strip())
    return pieces


def split_rich_markdown_for_render(text: str, max_chars: int) -> list[str]:
    """Split rich Markdown at semantic boundaries without breaking math or tables."""
    max_chars = max(200, int(max_chars or 1600))
    units: list[str] = []
    for block in extract_content_blocks(text):
        if block.kind == "math":
            units.append(normalize_math_markdown(block.content))
            continue
        if block.kind == "table":
            units.append(block.content.strip())
            continue
        paragraphs = re.split(r"(\n\s*\n)", block.content)
        for paragraph in paragraphs:
            if not paragraph.strip():
                continue
            units.extend(_split_oversized_text(paragraph.strip(), max_chars))

    chunks: list[str] = []
    current = ""
    for unit in units:
        separator = "\n\n" if current else ""
        if current and len(current) + len(separator) + len(unit) > max_chars:
            chunks.append(current.strip())
            current = unit
        else:
            current += separator + unit
    if current.strip():
        chunks.append(current.strip())
    return chunks


def _append_block(blocks: list[ContentBlock], kind: str, content: str) -> None:
    if not content:
        return
    if blocks and blocks[-1].kind == kind:
        previous = blocks[-1]
        blocks[-1] = ContentBlock(kind, previous.content + content)
    else:
        blocks.append(ContentBlock(kind, content))


def _split_text_math_lines(text: str, blocks: list[ContentBlock]) -> None:
    """Promote formula-bearing lines while leaving normal prose as text."""
    pending: list[str] = []
    for line in text.splitlines(keepends=True):
        if contains_math(line):
            if pending:
                _append_block(blocks, "text", "".join(pending))
                pending.clear()
            _append_block(blocks, "math", line)
        else:
            pending.append(line)
    if pending:
        _append_block(blocks, "text", "".join(pending))


def extract_content_blocks(text: str) -> list[ContentBlock]:
    """Extract tables and formulas before any ordinary reply splitting occurs."""
    if not text:
        return []

    lines = text.splitlines(keepends=True)
    blocks: list[ContentBlock] = []
    pending: list[str] = []
    index = 0

    def flush_pending() -> None:
        if pending:
            _split_text_math_lines("".join(pending), blocks)
            pending.clear()

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        fence_match = re.match(r"^\s*(```+|~~~+)", line)
        if fence_match:
            flush_pending()
            fence = fence_match.group(1)
            code_lines = [line]
            index += 1
            while index < len(lines):
                code_lines.append(lines[index])
                if lines[index].lstrip().startswith(fence):
                    index += 1
                    break
                index += 1
            _append_block(blocks, "text", "".join(code_lines))
            continue

        if _is_table_start(lines, index):
            flush_pending()
            table_lines = [line, lines[index + 1]]
            index += 2
            while index < len(lines) and _is_table_row(lines[index]):
                table_lines.append(lines[index])
                index += 1
            _append_block(blocks, "table", "".join(table_lines))
            continue

        if stripped == "[":
            closing_index = index + 1
            while closing_index < len(lines) and lines[closing_index].strip() != "]":
                closing_index += 1
            if closing_index < len(lines):
                inner = "".join(lines[index + 1 : closing_index])
                if contains_math(inner):
                    flush_pending()
                    _append_block(blocks, "math", inner)
                    index = closing_index + 1
                    continue

        math_end = _display_math_end(stripped)
        if math_end:
            flush_pending()
            math_lines = [line]
            index += 1
            if stripped.count(math_end) < 2 and not (
                math_end != "$$" and math_end in stripped
            ):
                while index < len(lines):
                    math_lines.append(lines[index])
                    if math_end in lines[index]:
                        index += 1
                        break
                    index += 1
            _append_block(blocks, "math", "".join(math_lines))
            continue

        pending.append(line)
        index += 1

    flush_pending()
    return blocks


def build_split_pattern(split_mode: str, split_chars: list[str], regex: str) -> str:
    if split_mode == "regex":
        return regex or r"[。？！?!\n…]+"
    escaped = [re.escape(str(item).replace(r"\n", "\n")) for item in split_chars if item]
    escaped.sort(key=len, reverse=True)
    return rf"(?:{'|'.join(escaped)})+" if escaped else r"[\n]+"


def smart_split_text(
    text: str,
    pattern: str,
    *,
    max_segments: int = 7,
    min_segment_length: int = 10,
    balanced: bool = True,
    no_split_around: list[str] | None = None,
) -> list[str]:
    """Split prose while protecting brackets, quotes, code blocks and think blocks."""
    if not text:
        return []

    try:
        compiled = re.compile(pattern)
    except re.error:
        compiled = re.compile(r"[。？！?!\n…]+")

    pair_map = {
        "“": "”",
        "‘": "’",
        "《": "》",
        "（": "）",
        "(": ")",
        "[": "]",
        "{": "}",
        "<": ">",
    }
    quote_chars = {'"', "'", "`"}
    text_weight = sum(1 for char in text if not char.isspace())
    ideal = max(min_segment_length, (text_weight + max_segments - 1) // max_segments) if balanced and max_segments > 0 else 0

    segments: list[str] = []
    stack: list[str] = []
    chunk: list[str] = []
    weight = 0
    index = 0

    while index < len(text):
        for opener, closer in (("```", "```"), ("<think>", "</think>")):
            if text.startswith(opener, index):
                end = text.find(closer, index + len(opener))
                if end == -1:
                    protected = text[index:]
                    chunk.append(protected)
                    index = len(text)
                else:
                    end += len(closer)
                    protected = text[index:end]
                    chunk.append(protected)
                    index = end
                weight += sum(1 for char in protected if not char.isspace())
                break
        else:
            match = compiled.match(text, index)
            if match:
                delimiter = match.group(0)
                should_split = not stack
                if should_split and no_split_around:
                    following = text[match.end() :].lstrip(" \t")
                    if any(
                        following.startswith(word)
                        for word in no_split_around
                        if word
                    ):
                        should_split = False
                if should_split and ideal and weight < max(min_segment_length, int(ideal * 0.4)):
                    should_split = False
                chunk.append(delimiter)
                index += len(delimiter)
                weight += sum(1 for char in delimiter if not char.isspace())
                if should_split:
                    value = "".join(chunk).strip("\r\n")
                    if value:
                        segments.append(value)
                    chunk.clear()
                    weight = 0
                continue

            char = text[index]
            if char in quote_chars:
                if stack and stack[-1] == char:
                    stack.pop()
                else:
                    stack.append(char)
            elif char in pair_map:
                stack.append(char)
            elif stack and pair_map.get(stack[-1]) == char:
                stack.pop()
            chunk.append(char)
            if not char.isspace():
                weight += 1
            index += 1
            continue
        continue

    tail = "".join(chunk).strip("\r\n")
    if tail:
        segments.append(tail)
    if not segments:
        return [text]

    if max_segments > 0 and len(segments) > max_segments:
        head = segments[: max_segments - 1]
        head.append("".join(segments[max_segments - 1 :]))
        segments = head
    return segments
