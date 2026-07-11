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
    r"\\(?:frac|sqrt|sum|prod|int|lim|log|sin|cos|tan|alpha|beta|gamma|"
    r"theta|lambda|mu|pi|sigma|phi|omega|begin|left|right)\b"
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
