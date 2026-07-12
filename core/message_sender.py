"""发送与装饰钩子模块。"""

from __future__ import annotations

import asyncio
import traceback
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.core.message.components import Plain, Record
from astrbot.core.message.message_event_result import MessageChain, MessageEventResult
from astrbot.core.platform.astrbot_message import AstrBotMessage, Group, MessageMember
from astrbot.core.platform.message_type import MessageType
from astrbot.core.platform.platform import PlatformStatus
from astrbot.core.star.star_handler import EventType, star_handlers_registry

try:
    from astrbot.api.event import AstrMessageEvent as AstrBotMessageEvent
except ImportError:
    AstrBotMessageEvent = None

try:
    from astrbot.core.platform.astr_message_event import MessageSession as MS
except ImportError:
    from astrbot.core.platform.message_session import MessageSession as MS

try:
    from astrbot.core.platform.sources.webchat.message_parts_helper import (
        message_chain_to_storage_message_parts,
    )
except ImportError:
    message_chain_to_storage_message_parts = None


class SenderMixin:
    """发送与装饰钩子混入类。"""

    context: Any
    session_data: dict
    telemetry: Any
    data_dir: Any

    async def _trigger_decorating_hooks(
        self,
        session_id: str,
        chain: list,
    ) -> list:
        """触发 OnDecoratingResultEvent 钩子。"""
        parsed = self._parse_session_id(session_id)
        if not parsed:
            return chain

        # 解析出平台、消息类型、目标 ID，用于构造事件上下文
        platform_name, msg_type_str, target_id = parsed
        platform_inst = None
        for p in self.context.platform_manager.platform_insts:
            if p.meta().id == platform_name:
                platform_inst = p
                break

        # 兼容按平台显示名匹配（部分平台可能用 name 进行标识）
        if not platform_inst:
            for p in self.context.platform_manager.platform_insts:
                if p.meta().name == platform_name:
                    platform_inst = p
                    break

        if not platform_inst:
            return chain

        # 构造伪造的消息对象以触发装饰链
        message_obj = AstrBotMessage()
        if "Friend" in msg_type_str:
            message_obj.type = MessageType.FRIEND_MESSAGE
        elif "Group" in msg_type_str:
            message_obj.type = MessageType.GROUP_MESSAGE
            message_obj.group = Group(group_id=target_id)
        else:
            message_obj.type = MessageType.FRIEND_MESSAGE

        # 构造最小可用消息对象，让装饰器可在统一事件结构上改写链
        message_obj.session_id = target_id
        message_obj.message = chain
        message_obj.self_id = self.session_data.get(session_id, {}).get(
            "self_id", "bot"
        )
        message_obj.sender = MessageMember(user_id=target_id)
        message_obj.message_str = ""
        message_obj.raw_message = None
        message_obj.message_id = ""

        # 旧版本若无事件类则跳过装饰阶段，直接返回原链
        if not AstrBotMessageEvent:
            return chain

        event = AstrBotMessageEvent(
            message_str="",
            message_obj=message_obj,
            platform_meta=platform_inst.meta(),
            session_id=target_id,
        )
        # 让统一分段器识别这是主动消息；分段规则统一读取全局 Pro 配置。
        setattr(event, "__proactive_chat_event", True)

        # 注入结果链以便装饰器修改
        res = MessageEventResult()
        res.chain = chain
        event.set_result(res)

        # 顺序执行所有 OnDecoratingResultEvent 处理器
        handlers = star_handlers_registry.get_handlers_by_event_type(
            EventType.OnDecoratingResultEvent
        )
        for handler in handlers:
            try:
                logger.debug(
                    f"[主动消息] 正在执行装饰钩子: {handler.handler_full_name} ({handler.handler_module_path}) 喵"
                )
                await handler.handler(event)
            except Exception as e:
                error_type = type(e).__name__
                logger.error(
                    f"[主动消息] 执行装饰钩子失败喵！来源: {handler.handler_full_name}, "
                    f"错误类型: {error_type}, 错误详情: {e}"
                )
                if self.telemetry and self.telemetry.enabled:
                    # 装饰钩子属于外围扩展链路，单独上报便于定位是否为第三方装饰器导致的问题。
                    self._track_task(
                        asyncio.create_task(
                            self.telemetry.track_error(
                                e,
                                module="core.message_sender._trigger_decorating_hooks",
                            )
                        )
                    )
                if "Available" in error_type:
                    logger.error(
                        f"[主动消息] 抓到可能导致 ApiNotAvailable 的嫌疑人喵！模块: {handler.handler_module_path}"
                    )

        res = event.get_result()
        if res is not None:
            return res.chain if res.chain is not None else []
        return chain

    async def _persist_proactive_message_to_platform_history(
        self,
        session_id: str,
        chain: MessageChain,
    ) -> None:
        """将主动消息补写入平台消息流水，弥补部分适配器不会自动持久化的问题。"""
        try:
            parsed = self._parse_session_id(session_id)
        except Exception as e:
            logger.warning(
                f"[主动消息] 解析会话标识失败，跳过平台流水补写喵: {e}",
                exc_info=True,
            )
            return

        if not parsed:
            return

        platform_id, _message_type, target_id = parsed
        history_mgr = getattr(self.context, "message_history_manager", None)
        if not history_mgr or message_chain_to_storage_message_parts is None:
            return

        try:
            db = getattr(history_mgr, "db", None)
            insert_attachment = getattr(db, "insert_attachment", None)
            if not callable(insert_attachment):
                return

            attachments_dir = Path(self.data_dir) / "attachments"
            attachments_dir.mkdir(parents=True, exist_ok=True)
            message_parts = await message_chain_to_storage_message_parts(
                chain,
                insert_attachment=insert_attachment,
                attachments_dir=attachments_dir,
            )
            if not message_parts:
                return

            await history_mgr.insert(
                platform_id=platform_id,
                user_id=target_id,
                content={"type": "bot", "message": message_parts},
                sender_id="bot",
                sender_name="bot",
            )
            logger.debug(
                f"[主动消息] 已将主动消息补写入平台 ({platform_id}) 的流水喵，会话标识为 {target_id}。"
            )
        except Exception as e:
            logger.warning(f"[主动消息] 补写平台流水失败喵: {e}", exc_info=True)

    async def _send_chain_with_hooks(
        self,
        session_id: str,
        components: list,
    ) -> None:
        """发送消息链（含装饰钩子）。"""
        processed_chain_list = await self._trigger_decorating_hooks(
            session_id,
            components,
        )
        if not processed_chain_list:
            return

        await self._send_processed_chain(session_id, processed_chain_list)

    async def _send_processed_chain(self, session_id: str, components: list) -> None:
        """直接发送已经完成装饰处理的消息链，不再次触发装饰钩子。"""

        # 将处理后的组件列表封装为统一消息链对象
        chain = MessageChain(components)
        parsed = self._parse_session_id(session_id)
        if not parsed:
            # 无法解析则使用核心 API 兜底
            await self.context.send_message(session_id, chain)
            await self._persist_proactive_message_to_platform_history(session_id, chain)
            return

        p_id, m_type_str, t_id = parsed
        m_type = (
            MessageType.GROUP_MESSAGE
            if "Group" in m_type_str
            else MessageType.FRIEND_MESSAGE
        )

        # 精确匹配平台实例：避免将消息发往错误平台
        platforms = self.context.platform_manager.get_insts()
        target_platform = next((p for p in platforms if p.meta().id == p_id), None)

        if not target_platform:
            logger.warning(
                f"[主动消息] 找不到指定的平台 {p_id} 喵，尝试使用核心 API 兜底喵。"
            )
            await self.context.send_message(session_id, chain)
            await self._persist_proactive_message_to_platform_history(session_id, chain)
            return

        if target_platform.status != PlatformStatus.RUNNING:
            logger.warning(f"[主动消息] 平台 {p_id} 未运行喵，跳过主动消息喵。")
            return

        try:
            session_obj = MS(platform_name=p_id, message_type=m_type, session_id=t_id)
            await target_platform.send_by_session(session_obj, chain)
            logger.debug(f"[主动消息] 消息将通过平台 {p_id} 送达喵")
            if p_id != "webchat":
                await self._persist_proactive_message_to_platform_history(
                    session_id, chain
                )
        except Exception as e:
            logger.error(f"[主动消息] 通过平台 {p_id} 发送失败喵: {e}")
            logger.debug(traceback.format_exc())
            if self.telemetry and self.telemetry.enabled:
                # 平台发送失败是实际送达链路的问题，与 LLM 生成失败应在遥测上分开统计。
                self._track_task(
                    asyncio.create_task(
                        self.telemetry.track_error(
                            e,
                            module="core.message_sender._send_chain_with_hooks",
                        )
                    )
                )

    async def _send_proactive_message(self, session_id: str, text: str) -> None:
        """发送主动消息（支持TTS与分段）。"""
        session_config = self._get_session_config(session_id)
        if not session_config:
            logger.info(
                f"[主动消息] 无法获取会话配置，跳过 {self._get_session_log_str(session_id)} 的消息发送喵。"
            )
            return

        logger.info(
            f"[主动消息] 开始发送 {self._get_session_log_str(session_id, session_config)} 的主动消息喵。"
        )

        tts_conf = session_config.get("tts_settings", {})
        # 先尝试 TTS：成功后是否继续发文本由 always_send_text 控制
        is_tts_sent = False
        if tts_conf.get("enable_tts", True):
            try:
                logger.info("[主动消息] 尝试进行手动TTS喵。")
                tts_provider = self.context.get_using_tts_provider(umo=session_id)
                if tts_provider:
                    audio_path = await tts_provider.get_audio(text)
                    if audio_path:
                        await self._send_chain_with_hooks(
                            session_id, [Record(file=audio_path)]
                        )
                        is_tts_sent = True
                        await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"[主动消息] 手动TTS流程发生异常喵: {e}")
                if self.telemetry and self.telemetry.enabled:
                    # TTS 失败不一定意味着文本发送失败，因此单独挂到 tts 子模块下记录。
                    self._track_task(
                        asyncio.create_task(
                            self.telemetry.track_error(
                                e,
                                module="core.message_sender._send_proactive_message.tts",
                            )
                        )
                    )

        # 是否继续发送文本：未发出 TTS 或配置要求始终发文本
        should_send_text = not is_tts_sent or tts_conf.get("always_send_text", True)

        if should_send_text:
            # 必须把完整文本交给统一装饰链。表格、公式和普通文本均按全局 Pro 规则处理。
            await self._send_chain_with_hooks(
                session_id,
                [Plain(text=text)],
            )
            if self.telemetry and self.telemetry.enabled:
                self._track_task(
                    asyncio.create_task(
                        self.telemetry.track_feature(
                            "message_send_result",
                            {
                                "session_type": session_config.get(
                                    "_session_type", "unknown"
                                ),
                                "tts_enabled": bool(tts_conf.get("enable_tts", True)),
                                "tts_sent": is_tts_sent,
                                "segmented_enabled": bool(
                                    self._get_unified_splitter_config().get(
                                        "enable_split", True
                                    )
                                ),
                                "text_length": len(text),
                                "success": True,
                            },
                        )
                    )
                )

        # Bot 在群聊发言后需要重置沉默计时
        if "group" in session_id.lower():
            await self._reset_group_silence_timer(session_id)
            logger.info(
                f"[主动消息] Bot主动消息已发送，已重置 {self._get_session_log_str(session_id, session_config)} 的沉默倒计时喵。"
            )
