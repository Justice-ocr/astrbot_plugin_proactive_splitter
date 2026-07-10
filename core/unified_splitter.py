"""Unified reply splitting and rich-content rendering for all plugin messages."""

from __future__ import annotations

import asyncio
import math
import random
import re
import time
from typing import Any

from astrbot.api import html_renderer, logger
from astrbot.api.message_components import Image, Plain, Record, Reply
from astrbot.api.provider import ProviderRequest
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.star.session_llm_manager import SessionServiceManager

from .rich_content import build_split_pattern, extract_content_blocks, smart_split_text


class UnifiedSplitterMixin:
    """One sending pipeline for reactive replies and proactive chat messages."""

    context: Any
    config: Any

    def get_unified_splitter_diagnostics(self) -> dict[str, Any]:
        """Return a JSON-safe snapshot for the Web management surfaces."""
        settings = self._get_unified_splitter_config()
        stats = getattr(self, "_unified_splitter_diagnostics", None)
        if not isinstance(stats, dict):
            stats = {}
        return {
            "enabled": bool(settings.get("enable", True)),
            "split_enabled": bool(settings.get("enable_split", True)),
            "rich_render_enabled": bool(settings.get("enable_rich_render", True)),
            "use_network": bool(settings.get("rich_render_use_network", True)),
            "template_name": settings.get("rich_render_template", "base") or "base",
            "render_attempts": int(stats.get("render_attempts", 0) or 0),
            "render_successes": int(stats.get("render_successes", 0) or 0),
            "render_failures": int(stats.get("render_failures", 0) or 0),
            "render_skipped": int(stats.get("render_skipped", 0) or 0),
            "last_result": stats.get("last_result"),
            "last_kind": stats.get("last_kind"),
            "last_error": stats.get("last_error"),
            "last_render_at": stats.get("last_render_at"),
            "last_segments_count": int(stats.get("last_segments_count", 0) or 0),
            "last_processed_at": stats.get("last_processed_at"),
        }

    def _record_unified_splitter_diagnostic(self, **updates: Any) -> None:
        stats = getattr(self, "_unified_splitter_diagnostics", None)
        if not isinstance(stats, dict):
            stats = {}
            setattr(self, "_unified_splitter_diagnostics", stats)
        stats.update(updates)

    def _get_unified_splitter_config(self, event: Any | None = None) -> dict:
        configured = self.config.get("unified_splitter_settings", {})
        settings = dict(configured) if isinstance(configured, dict) else {}
        proactive = getattr(event, "__proactive_segmented_settings", None)
        if isinstance(proactive, dict):
            settings["enable_split"] = bool(proactive.get("enable", False))
            settings["proactive_legacy_settings"] = proactive
        return settings

    @staticmethod
    def _is_model_result(event: Any, result: Any) -> bool:
        if getattr(event, "__proactive_chat_event", False):
            return True
        checker = getattr(result, "is_model_result", None)
        if callable(checker):
            try:
                return bool(checker())
            except Exception:
                pass
        content_type = getattr(result, "result_content_type", None)
        if content_type is not None:
            return getattr(content_type, "name", "") in {
                "LLM_RESULT",
                "AGENT_RUNNER_ERROR",
                "AGENT_RUNNER_RESULT",
                "TOOL_RESULT",
                "TOOL_CALL",
            }
        return bool(getattr(event, "__unified_splitter_llm_reply", False))

    async def unified_on_llm_request(self, event: Any, req: ProviderRequest) -> None:
        settings = self._get_unified_splitter_config(event)
        if settings.get("enable_rich_render", True) and settings.get("inject_rich_prompt", True):
            req.system_prompt += (
                "\n当回复包含表格或数学公式时，请使用标准 Markdown 表格和 LaTeX "
                "($...$ 或 $$...$$) 格式输出，以便客户端完整渲染为图片。"
            )
        if settings.get("inject_kaomoji_prompt", False):
            req.system_prompt += (
                "\n如果需要输出颜文字（如 (QAQ)），请使用三对反引号包裹，"
                "例如 ```(QAQ)```，避免颜文字被拆分。"
            )
        if settings.get("reverse_replace", False) and getattr(req, "prompt", None):
            reverse_rules: dict[str, str] = {}
            for rule in settings.get("replace_rules", []) or []:
                if not isinstance(rule, dict):
                    continue
                find = self._unescape_text(str(rule.get("find", "")))
                replace = self._unescape_text(str(rule.get("replace", "")))
                if find and replace:
                    reverse_rules[replace] = find
            req.prompt = self._replace_simultaneously(req.prompt, reverse_rules)

    async def unified_on_decorating_result(self, event: Any) -> None:
        result = event.get_result()
        if not result or not result.chain:
            return
        if getattr(result, "__unified_splitter_processed", False):
            return

        settings = self._get_unified_splitter_config(event)
        if not settings.get("enable", True):
            return

        umo = str(getattr(event, "unified_msg_origin", "") or "")
        blacklist = settings.get("conversation_blacklist", []) or []
        whitelist = settings.get("conversation_whitelist", []) or []
        if umo in blacklist or (whitelist and umo not in whitelist):
            return
        group_id = getattr(getattr(event, "message_obj", None), "group_id", None)
        if group_id and not settings.get("enable_group_split", True):
            return
        if settings.get("split_scope", "llm_only") == "llm_only" and not self._is_model_result(event, result):
            return

        setattr(result, "__unified_splitter_processed", True)
        segments = await self._build_unified_segments(event, list(result.chain), settings)
        self._post_clean_segments(segments, settings)
        segments = [segment for segment in segments if self._segment_has_content(segment)]
        self._record_unified_splitter_diagnostic(
            last_segments_count=len(segments),
            last_processed_at=time.time(),
        )
        if not segments:
            result.chain.clear()
            return

        source_id = str(getattr(getattr(event, "message_obj", None), "message_id", "") or "")
        if settings.get("enable_reply", True) and source_id:
            if not any(isinstance(component, Reply) for component in segments[0]):
                segments[0].insert(0, Reply(id=source_id))

        if len(segments) == 1:
            result.chain.clear()
            result.chain.extend(segments[0])
            return

        for index, segment in enumerate(segments[:-1]):
            if not segment:
                continue
            try:
                send_segment = await self._unified_process_tts(event, segment, settings)
                if getattr(event, "__proactive_chat_event", False) and hasattr(
                    self, "_send_processed_chain"
                ):
                    await self._send_processed_chain(
                        event.unified_msg_origin,
                        send_segment,
                    )
                else:
                    chain = MessageChain()
                    chain.chain = send_segment
                    await self.context.send_message(event.unified_msg_origin, chain)
                delay = self._unified_delay(segments[index + 1], settings, event)
                if delay > 0:
                    await asyncio.sleep(delay)
            except Exception as exc:
                logger.error(f"[Proactive Splitter] 发送分段失败: {exc}")

        result.chain.clear()
        result.chain.extend(segments[-1])
        logger.info(f"[Proactive Splitter] 已生成 {len(segments)} 个发送单元。")

    async def _build_unified_segments(self, event: Any, chain: list, settings: dict) -> list[list]:
        chain = self._merge_adjacent_plain(chain)
        segments: list[list] = []
        buffer: list = []

        for component in chain:
            if isinstance(component, Plain):
                text = self._clean_and_replace(component.text, settings)
                for block in extract_content_blocks(text):
                    if block.kind in {"table", "math"}:
                        if buffer:
                            segments.append(buffer)
                            buffer = []
                        rich_component = await self._render_rich_block(block.content, block.kind, settings)
                        segments.append([rich_component])
                        continue

                    pieces = self._split_plain_block(block.content, settings, event)
                    for piece in pieces:
                        if not piece.strip():
                            continue
                        buffer.append(Plain(text=piece))
                        segments.append(buffer)
                        buffer = []
                continue

            component_name = type(component).__name__.lower()
            if "reply" in component_name:
                buffer.append(component)
                continue
            strategy = self._component_strategy(component_name, settings)
            if strategy == "单独":
                if buffer:
                    segments.append(buffer)
                    buffer = []
                segments.append([component])
            elif strategy == "跟随上段":
                if buffer:
                    buffer.append(component)
                elif segments:
                    segments[-1].append(component)
                else:
                    buffer.append(component)
            else:
                buffer.append(component)

        if buffer:
            segments.append(buffer)
        return [segment for segment in segments if segment]

    @staticmethod
    def _merge_adjacent_plain(chain: list) -> list:
        merged: list = []
        for component in chain:
            if merged and isinstance(component, Plain) and isinstance(merged[-1], Plain):
                merged[-1] = Plain(text=merged[-1].text + component.text)
            else:
                merged.append(component)
        return merged

    @staticmethod
    def _component_strategy(component_name: str, settings: dict) -> str:
        if "image" in component_name:
            return settings.get("image_strategy", "单独")
        if "at" in component_name:
            return settings.get("at_strategy", "跟随下段")
        if "face" in component_name:
            return settings.get("face_strategy", "嵌入")
        return settings.get("other_media_strategy", "跟随下段")

    @staticmethod
    def _clean_and_replace(text: str, settings: dict) -> str:
        for item in settings.get("clean_before_items", []) or []:
            if item:
                text = text.replace(str(item), "")
        rules = settings.get("replace_rules", []) or []
        replacements: dict[str, str] = {}
        for rule in rules:
            if isinstance(rule, dict) and rule.get("find"):
                find = UnifiedSplitterMixin._unescape_text(str(rule["find"]))
                replace = UnifiedSplitterMixin._unescape_text(str(rule.get("replace", "")))
                replacements[find] = replace
        return UnifiedSplitterMixin._replace_simultaneously(text, replacements)

    @staticmethod
    def _unescape_text(text: str) -> str:
        return text.replace(r"\n", "\n").replace(r"\t", "\t").replace(r"\s", " ")

    @staticmethod
    def _replace_simultaneously(text: str, replacements: dict[str, str]) -> str:
        if not replacements:
            return text
        pattern = "|".join(
            re.escape(key) for key in sorted(replacements, key=len, reverse=True) if key
        )
        if not pattern:
            return text
        return re.sub(pattern, lambda match: replacements[match.group(0)], text)

    @staticmethod
    def _post_clean_segments(segments: list[list], settings: dict) -> None:
        items = [str(item) for item in settings.get("clean_after_items", []) or [] if item]
        trim = settings.get("trim_segment_edge_blank_lines", True)
        for segment in segments:
            for component in segment:
                if not isinstance(component, Plain):
                    continue
                for item in items:
                    component.text = component.text.replace(item, "")
                if trim:
                    component.text = component.text.strip("\r\n")

    @staticmethod
    def _segment_has_content(segment: list) -> bool:
        return any(
            not isinstance(component, Plain) or bool(component.text.strip())
            for component in segment
        )

    def _split_plain_block(self, text: str, settings: dict, event: Any) -> list[str]:
        if not settings.get("enable_split", True):
            return [text]

        proactive = settings.get("proactive_legacy_settings")
        if isinstance(proactive, dict):
            threshold = int(proactive.get("words_count_threshold", 150) or 0)
            if threshold > 0 and len(text) > threshold:
                return [text]
            return self._legacy_proactive_split(text, proactive)

        min_length = int(settings.get("min_length_to_split", 0) or 0)
        if min_length > 0 and len(text) < min_length:
            return [text]
        max_disable = int(settings.get("max_length_to_disable", 0) or 0)
        if max_disable > 0 and len(text) > max_disable:
            return [text]

        pattern = build_split_pattern(
            settings.get("split_mode", "simple"),
            settings.get("split_chars", ["。", "？", "！", "?", "!", "；", ";", r"\n"]),
            settings.get("split_regex", r"[。？！?!\n…]+"),
        )
        return smart_split_text(
            text,
            pattern,
            max_segments=int(settings.get("max_segments", 7) or 0),
            min_segment_length=int(settings.get("min_segment_length", 10) or 1),
            balanced=bool(settings.get("balanced_split_mode", True)),
            no_split_around=[
                str(item) for item in settings.get("no_split_around", []) or [] if item
            ],
        )

    @staticmethod
    def _legacy_proactive_split(text: str, settings: dict) -> list[str]:
        if settings.get("split_mode", "regex") == "words":
            words = [str(word) for word in settings.get("split_words", []) if word]
            if not words:
                return [text]
            pattern = re.compile(rf"(.*?(?:{'|'.join(re.escape(word) for word in sorted(words, key=len, reverse=True))})|.+$)", re.DOTALL)
            segments = [match.group(0) for match in pattern.finditer(text)]
        else:
            try:
                raw_segments = re.findall(settings.get("regex", r".*?[。？！~…\n]+|.+$"), text, re.DOTALL | re.MULTILINE)
            except re.error:
                raw_segments = re.findall(r".*?[。？！~…\n]+|.+$", text, re.DOTALL | re.MULTILINE)
            segments = [
                next((part for part in segment if part), "")
                if isinstance(segment, tuple)
                else segment
                for segment in raw_segments
            ]
        if settings.get("enable_content_cleanup", False):
            try:
                cleanup = re.compile(settings.get("content_cleanup_rule", ""))
                segments = [cleanup.sub("", segment) for segment in segments]
            except re.error:
                pass
        return [segment for segment in segments if segment.strip()] or [text]

    async def _render_rich_block(self, text: str, kind: str, settings: dict):
        if not settings.get("enable_rich_render", True):
            diagnostics = self.get_unified_splitter_diagnostics()
            self._record_unified_splitter_diagnostic(
                render_skipped=diagnostics["render_skipped"] + 1,
                last_result="disabled",
                last_kind=kind,
                last_error=None,
                last_render_at=time.time(),
            )
            return Plain(text=text)
        diagnostics = self.get_unified_splitter_diagnostics()
        self._record_unified_splitter_diagnostic(
            render_attempts=diagnostics["render_attempts"] + 1,
            last_kind=kind,
            last_render_at=time.time(),
        )
        try:
            path = await html_renderer.render_t2i(
                text,
                use_network=bool(settings.get("rich_render_use_network", True)),
                return_url=False,
                template_name=settings.get("rich_render_template", "base") or "base",
            )
            diagnostics = self.get_unified_splitter_diagnostics()
            self._record_unified_splitter_diagnostic(
                render_successes=diagnostics["render_successes"] + 1,
                last_result="success",
                last_error=None,
                last_render_at=time.time(),
            )
            logger.info(f"[Proactive Splitter] 已将 {kind} 内容渲染为图片。")
            if str(path).startswith(("http://", "https://", "file://", "base64://", "data:")):
                return Image(file=path)
            return Image.fromFileSystem(path)
        except Exception as exc:
            diagnostics = self.get_unified_splitter_diagnostics()
            self._record_unified_splitter_diagnostic(
                render_failures=diagnostics["render_failures"] + 1,
                last_result="failure",
                last_error=str(exc),
                last_render_at=time.time(),
            )
            logger.warning(f"[Proactive Splitter] {kind} 渲染失败，保留完整文本: {exc}")
            return Plain(text=text)

    def _unified_delay(self, next_segment: list, settings: dict, event: Any) -> float:
        text = "".join(component.text for component in next_segment if isinstance(component, Plain))
        proactive = settings.get("proactive_legacy_settings")
        if isinstance(proactive, dict):
            if proactive.get("interval_method", "random") == "log":
                base = max(float(proactive.get("log_base", 1.8)), 1.01)
                count = len(text.split()) if text.isascii() else sum(char.isalnum() for char in text)
                value = math.log(count + 1, base)
                return random.uniform(value, value + 0.5)
            try:
                values = [float(item) for item in str(proactive.get("interval", "1.5, 3.5")).replace(" ", "").split(",")]
                if len(values) == 2:
                    return random.uniform(values[0], values[1])
            except (TypeError, ValueError):
                return 1.5

        strategy = settings.get("delay_strategy", "linear")
        if strategy == "random":
            return random.uniform(float(settings.get("random_min", 1.0)), float(settings.get("random_max", 3.0)))
        if strategy == "log":
            return min(float(settings.get("log_base", 0.5)) + float(settings.get("log_factor", 0.8)) * math.log(len(text) + 1), 5.0)
        if strategy == "fixed":
            return float(settings.get("fixed_delay", 1.5))
        return float(settings.get("linear_base", 0.5)) + len(text) * float(settings.get("linear_factor", 0.1))

    async def _unified_process_tts(self, event: Any, segment: list, settings: dict) -> list:
        if getattr(event, "__proactive_chat_event", False) or not settings.get("enable_tts_for_segments", True):
            return segment
        try:
            all_config = self.context.get_config(event.unified_msg_origin)
            tts_config = all_config.get("provider_tts_settings", {})
            if not tts_config.get("enable", False):
                return segment
            provider = self.context.get_using_tts_provider(event.unified_msg_origin)
            if not provider or not await SessionServiceManager.should_process_tts_request(event):
                return segment
            if random.random() > float(tts_config.get("trigger_probability", 1.0)):
                return segment
            dual_output = tts_config.get("dual_output", False)
            processed: list = []
            for component in segment:
                if isinstance(component, Plain) and len(component.text) > 1:
                    audio_path = await provider.get_audio(component.text)
                    if audio_path:
                        processed.append(Record(file=audio_path, url=audio_path))
                        if dual_output:
                            processed.append(component)
                        continue
                processed.append(component)
            return processed
        except Exception:
            return segment
