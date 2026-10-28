"""External delivery contract, shared by the decorating hook and peer plugins."""

from __future__ import annotations

import asyncio
import copy
import inspect
import time
from typing import Any

from astrbot.api import logger
from astrbot.api.message_components import Plain, Record, Reply
from astrbot.core.message.message_event_result import MessageChain

from .output_filter import filter_output

PLUGIN_NAME = "astrbot_plugin_proactive_splitter"


class ExternalReplyMixin:
    def external_reply_policy(self, event: Any, result: Any) -> dict:
        """Side-effect-free v1 probe; rechecked at delivery time."""
        settings = self._get_unified_splitter_config(event)
        reason = ""
        if getattr(self, "_unified_splitter_closing", False):
            reason = "closing"
        elif not result or not getattr(result, "chain", None):
            reason = "empty"
        elif not settings.get("enable", True):
            reason = "disabled"
        else:
            plugins = getattr(event, "plugins_name", None)
            if plugins is not None and plugins != ["*"] and PLUGIN_NAME not in plugins:
                reason = "plugin_scope"
            umo = str(getattr(event, "unified_msg_origin", "") or "")
            blacklist = settings.get("conversation_blacklist", []) or []
            whitelist = settings.get("conversation_whitelist", []) or []
            if umo in blacklist or (whitelist and umo not in whitelist):
                reason = "conversation_scope"
            group = getattr(getattr(event, "message_obj", None), "group_id", None)
            if (group or ":GroupMessage:" in umo) and not settings.get("enable_group_split", True):
                reason = "group_disabled"
            if settings.get("split_scope", "llm_only") == "llm_only" and not self._is_model_result(event, result):
                reason = "result_scope"
        return {"api_version": 1, "accepted": not bool(reason), "reason": reason or "applicable"}

    async def _prepare_unified_segments(
        self, event: Any, result: Any, settings: dict, *, apply_filter: bool = True
    ) -> list[list]:
        chain = [copy.copy(item) for item in result.chain]
        if apply_filter and settings.get("output_filter_enabled", False) and self._is_model_result(event, result):
            filtered = []
            for component in self._merge_adjacent_plain(chain):
                if isinstance(component, Plain):
                    component.text = filter_output(component.text, settings)
                if not isinstance(component, Plain) or component.text.strip():
                    filtered.append(component)
            chain = filtered
        segments = await self._build_unified_segments(event, chain, settings)
        self._post_clean_segments(segments, settings)
        segments = [segment for segment in segments if self._segment_has_content(segment)]
        source_id = str(getattr(getattr(event, "message_obj", None), "message_id", "") or "")
        if segments and settings.get("enable_reply", True) and source_id:
            if not any(isinstance(component, Reply) for component in segments[0]):
                segments[0].insert(0, Reply(id=source_id))
        self._record_unified_splitter_diagnostic(
            last_segments_count=len(segments), last_processed_at=time.time(),
        )
        return segments

    @staticmethod
    def _delivery_receipt(status: str, count: int, total: int, reason: str) -> dict:
        return {"status": status, "sent_count": count, "segment_count": total, "reason": reason}

    def _log_delivery_receipt(self, receipt: dict) -> None:
        self._record_unified_splitter_diagnostic(last_delivery=dict(receipt))
        logger.info(
            "[Proactive Splitter] owner=unified_splitter "
            f"status={receipt['status']} segments={receipt['segment_count']} "
            f"sent={receipt['sent_count']} reason={receipt['reason']}"
        )

    async def _deliver_unified_segments(
        self, event: Any, result: Any, segments: list[list], *, send: Any,
        is_current: Any, on_sent: Any = None, allow_tts: bool = False,
    ) -> dict:
        count = 0
        attempted = False
        receipt = self._delivery_receipt("handled", 0, len(segments), "complete")
        try:
            for index, segment in enumerate(segments):
                if not is_current() or not self.external_reply_policy(event, result)["accepted"]:
                    receipt = self._delivery_receipt("cancelled", count, len(segments), "stale_or_disabled")
                    break
                if index:
                    delay = self._unified_delay(segment, self._get_unified_splitter_config(event), event)
                    if delay > 0:
                        await asyncio.sleep(delay)
                if not is_current() or not self.external_reply_policy(event, result)["accepted"]:
                    receipt = self._delivery_receipt("cancelled", count, len(segments), "stale_or_disabled")
                    break
                outgoing = segment
                if allow_tts and not any(isinstance(c, Record) for c in result.chain):
                    outgoing = await self._unified_process_tts(event, segment, self._get_unified_splitter_config(event))
                if not is_current():
                    receipt = self._delivery_receipt("cancelled", count, len(segments), "stale_after_tts")
                    break
                message = MessageChain()
                message.chain = outgoing
                attempted = True
                delivered = await send(message)
                if delivered is False:
                    raise RuntimeError("delivery refused")
                count += 1
                receipt = self._delivery_receipt("handled", count, len(segments), "complete")
                if on_sent is not None:
                    noted = on_sent(message)
                    if inspect.isawaitable(noted):
                        await noted
        except asyncio.CancelledError:
            receipt = self._delivery_receipt("cancelled", count, len(segments), "task_cancelled")
            raise
        except Exception:
            # An ambiguous first-send error is consumed too: never replay it.
            receipt = self._delivery_receipt(
                "partial" if count else "failed", count, len(segments),
                "send_or_receipt_failed" if attempted else "preparation_failed",
            )
        finally:
            setattr(result, "__unified_splitter_delivery", receipt)
            self._log_delivery_receipt(receipt)
        return receipt

    async def process_external_reply(
        self, event: Any, result: Any, *, send: Any, is_current: Any,
        on_sent: Any = None, allow_tts: bool = False,
    ) -> dict:
        """Deliver ALL units. Only not_handled permits caller fallback.

        send(message) may return False to refuse delivery. on_sent runs after
        each successful send. Cancellation propagates; other failures return
        receipts, including ambiguous first-send failures. TTS is opt-in.
        """
        previous = getattr(result, "__unified_splitter_delivery", None)
        if isinstance(previous, dict):
            return dict(previous)
        if getattr(result, "__unified_splitter_processed", False):
            return self._delivery_receipt("handled", 0, 0, "already_processed")
        policy = self.external_reply_policy(event, result)
        if not policy["accepted"]:
            return self._delivery_receipt("not_handled", 0, 0, policy["reason"])
        setattr(result, "__unified_splitter_processed", True)
        try:
            segments = await self._prepare_unified_segments(event, result, self._get_unified_splitter_config(event))
        except asyncio.CancelledError:
            raise
        except Exception:
            receipt = self._delivery_receipt("failed", 0, 0, "preparation_failed")
            setattr(result, "__unified_splitter_delivery", receipt)
            self._log_delivery_receipt(receipt)
            return receipt
        return await self._deliver_unified_segments(
            event, result, segments, send=send, is_current=is_current,
            on_sent=on_sent, allow_tts=allow_tts,
        )
