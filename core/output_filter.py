"""Literal output-block filtering; independent of AstrBot and regex syntax."""
from __future__ import annotations


def filter_output(text: str, settings: dict) -> str:
    if not settings.get("output_filter_enabled", False):
        return text
    rules = settings.get("output_filter_rules", [])
    if not isinstance(rules, list):
        return text
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        prefix, suffix = rule.get("prefix"), rule.get("suffix")
        if not isinstance(prefix, str) or not prefix or not isinstance(suffix, str) or not suffix:
            continue
        cursor = 0
        parts = []
        while cursor < len(text):
            start = text.find(prefix, cursor)
            if start < 0:
                break
            if rule.get("match_scope", "start") == "start" and ("".join(parts) + text[cursor:start]).strip():
                break
            end = text.find(suffix, start + len(prefix))
            if end < 0:
                if rule.get("unclosed_action", "remove_suffix") == "remove_suffix":
                    parts.append(text[cursor:start])
                    cursor = len(text)
                break
            parts.append(text[cursor:start])
            cursor = end + len(suffix)
        parts.append(text[cursor:])
        text = "".join(parts)
    return text
