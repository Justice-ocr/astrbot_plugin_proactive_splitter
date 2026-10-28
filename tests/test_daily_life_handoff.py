import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest
import test_unified_splitter as splitter_tests
from core.unified_splitter import UnifiedSplitterMixin


# Load the production handoff module without importing daily_life's generic `core`
# package into this plugin's test process.
class DailyResultChain:
    def __init__(self):
        self.chain = []

    def message(self, text):
        self.chain.append(splitter_tests.Plain(text=text))
        return self


api_event = types.ModuleType("astrbot.api.event")
api_event.MessageChain = DailyResultChain
sys.modules["astrbot.api.event"] = api_event
api = sys.modules["astrbot.api"]
api.event = api_event

_daily_root = Path(__file__).resolve().parents[2] / "astrbot_plugin_daily_life"
if not (_daily_root / "core" / "runtime" / "textdelivery.py").is_file():
    pytest.skip("daily_life sibling checkout not present", allow_module_level=True)
_spec = importlib.util.spec_from_file_location(
    "daily_life_textdelivery", _daily_root / "core" / "runtime" / "textdelivery.py"
)
daily_delivery = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = daily_delivery
_spec.loader.exec_module(daily_delivery)


class FakeDailyRuntime:
    def __init__(self, peer):
        self.peer = peer
        self.context = types.SimpleNamespace(
            get_registered_star=lambda name: types.SimpleNamespace(
                activated=True, star_cls=self.peer
            ) if name == "astrbot_plugin_proactive_splitter" else None,
            get_config=lambda scope: {"plugin_set": ["*"]},
        )
        self.sent = []
        self.notes = []
        self._semantic_segment_revisions = {}
        self._semantic_segment_epochs = {}

    def _semantic_segment_init_state(self):
        self._semantic_segment_revisions = {}
        self._semantic_segment_epochs = {}

    def _semantic_segment_revision(self, scope):
        return self._semantic_segment_revisions.get(scope, 0)

    def _semantic_segment_epoch(self, scope):
        return self._semantic_segment_epochs.get(scope, 0)

    async def send_message_if_not_recalled(self, scope, message, **kwargs):
        self.sent.append((scope, message))
        return True

    def note_structured_bot_message(self, scope, text, **kwargs):
        self.notes.append((scope, text))

    @staticmethod
    def _semantic_segment_text(component):
        return getattr(component, "text", "")


def make_handoff(text, *, plugins=None):
    peer = splitter_tests.Plugin()
    peer.config["unified_splitter_settings"].update(
        {"split_chars": ["。", "？", "！", r"\n"], "max_segments": 30}
    )
    runtime = FakeDailyRuntime(peer)
    scope = "test:FriendMessage:1"
    source = types.SimpleNamespace(
        unified_msg_origin=scope,
        plugins_name=["*"] if plugins is None else plugins,
        message_obj=types.SimpleNamespace(message_id="42", group_id=None),
        is_stopped=lambda: False,
    )
    source._daily_life_reply_is_current = lambda: True
    result = splitter_tests.FakeResult([splitter_tests.Plain(text=text)])
    sent = asyncio.run(daily_delivery.try_send_background(
        runtime, scope, text, source_event=source, source_message_id="42"
    ))
    return peer, runtime, source, result, sent


def test_daily_background_handoff_uses_real_splitter_after_foreground_clear():
    peer = splitter_tests.Plugin()
    peer.config["unified_splitter_settings"].update(
        {"split_chars": ["。"], "max_segments": 30}
    )
    runtime = FakeDailyRuntime(peer)
    scope = "test:FriendMessage:1"
    source = types.SimpleNamespace(
        unified_msg_origin=scope,
        plugins_name=["astrbot_plugin_daily_life"],
        message_obj=types.SimpleNamespace(message_id="42", group_id=None),
        is_stopped=lambda: False,
        get_result=lambda: None,
    )
    source._daily_life_reply_is_current = lambda: True
    original = "“第一句。第二句。第三句。” don't (QAQ)"
    outcome = asyncio.run(daily_delivery.try_send_background(
        runtime, scope, original, source_event=source, source_message_id="42"
    ))
    texts = [
        component.text
        for _, message in runtime.sent
        for component in message.chain
        if isinstance(component, splitter_tests.Plain)
    ]
    assert outcome is True
    assert len(texts) >= 3
    assert "".join(texts) == original
    assert len(runtime.sent) == len(texts)
    assert len(runtime.notes) == len(texts)
    assert getattr(source, "get_result")() is None
    receipt = peer.get_unified_splitter_diagnostics()["last_delivery"]
    assert receipt["status"] == "handled"
    assert receipt["sent_count"] == receipt["segment_count"] == len(texts)


def test_proactive_daily_message_uses_same_external_splitter():
    peer = splitter_tests.Plugin()
    peer.config["unified_splitter_settings"]["split_chars"] = ["。"]
    runtime = FakeDailyRuntime(peer)
    runtime._proactive_send_is_current = lambda event: True
    scope = "test:FriendMessage:1"
    event = types.SimpleNamespace(
        unified_msg_origin=scope, plugins_name=["*"],
        message_obj=types.SimpleNamespace(message_id="", group_id=None),
        is_stopped=lambda: False,
    )
    text = "主动联系第一句。主动联系第二句。"
    result = asyncio.run(daily_delivery.try_send_background(
        runtime, scope, text, source_event=event, source="proactive"
    ))
    actual = "".join(
        item.text for _, message in runtime.sent for item in message.chain
        if isinstance(item, splitter_tests.Plain)
    )
    assert result is True
    assert actual == text
    assert len(runtime.sent) == 2


def test_daily_handoff_handles_long_text_without_local_length_cutoff():
    text = "第一段内容。\n" + ("后续解释仍然完整。\n" * 35)
    peer = splitter_tests.Plugin()
    peer.config["unified_splitter_settings"].update(
        {"split_chars": ["。", r"\n"], "max_segments": 60}
    )
    runtime = FakeDailyRuntime(peer)
    scope = "test:FriendMessage:1"
    source = types.SimpleNamespace(
        unified_msg_origin=scope, plugins_name=["*"],
        message_obj=types.SimpleNamespace(message_id="", group_id=None),
        is_stopped=lambda: False,
    )
    source._daily_life_reply_is_current = lambda: True
    outcome = asyncio.run(daily_delivery.try_send_background(
        runtime, scope, text, source_event=source
    ))
    actual = "".join(
        component.text for _, message in runtime.sent
        for component in message.chain if isinstance(component, splitter_tests.Plain)
    )
    assert outcome is True
    assert "".join(actual.split()) == "".join(text.split())
    assert len(runtime.sent) > 1


def test_handoff_falls_back_only_when_peer_declines_before_processing():
    peer = splitter_tests.Plugin()
    peer.config["unified_splitter_settings"]["enable"] = False
    runtime = FakeDailyRuntime(peer)
    event = types.SimpleNamespace(
        unified_msg_origin="test:FriendMessage:1", plugins_name=["*"],
        message_obj=types.SimpleNamespace(message_id="", group_id=None),
    )
    result = splitter_tests.FakeResult([splitter_tests.Plain("普通回复。")])
    outcome = asyncio.run(daily_delivery.handoff_reply(
        runtime, event, result, send=lambda message: asyncio.sleep(0), is_current=lambda: True
    ))
    assert outcome["status"] == "not_handled"
    assert runtime.sent == []


def test_handoff_partial_failure_never_replays_whole_reply():
    peer = splitter_tests.Plugin()
    peer.config["unified_splitter_settings"]["split_chars"] = ["。"]
    runtime = FakeDailyRuntime(peer)
    attempts = []
    async def send(message):
        attempts.append(message)
        if len(attempts) == 2:
            raise RuntimeError("platform failure")
    event = types.SimpleNamespace(
        unified_msg_origin="test:FriendMessage:1", plugins_name=["*"],
        message_obj=types.SimpleNamespace(message_id="", group_id=None),
    )
    result = splitter_tests.FakeResult([splitter_tests.Plain("第一句。第二句。第三句。")])
    outcome = asyncio.run(daily_delivery.handoff_reply(
        runtime, event, result, send=send, is_current=lambda: True
    ))
    assert outcome["status"] == "partial"
    assert outcome["sent_count"] == 1
    assert len(attempts) == 2
    assert len(runtime.sent) == 0


def test_recall_or_new_turn_cancels_remaining_units_without_replay():
    peer = splitter_tests.Plugin()
    peer.config["unified_splitter_settings"]["split_chars"] = ["。"]
    runtime = FakeDailyRuntime(peer)
    scope = "test:FriendMessage:1"
    event = types.SimpleNamespace(
        unified_msg_origin=scope, plugins_name=["*"],
        message_obj=types.SimpleNamespace(message_id="", group_id=None),
    )
    result = splitter_tests.FakeResult([splitter_tests.Plain("第一句。第二句。第三句。")])
    current = {"ok": True}

    async def send(message):
        runtime.sent.append((scope, message))
        current["ok"] = False
        return True

    outcome = asyncio.run(daily_delivery.handoff_reply(
        runtime, event, result, send=send, is_current=lambda: current["ok"]
    ))
    assert outcome["status"] == "cancelled"
    assert outcome["sent_count"] == 1
    assert len(runtime.sent) == 1


def test_preparation_failure_declines_before_sending_so_caller_can_fallback():
    peer = splitter_tests.Plugin()
    runtime = FakeDailyRuntime(peer)
    event = splitter_tests.FakeEvent("合成回复")
    calls = []

    async def fail_prepare(*args, **kwargs):
        raise RuntimeError("synthetic preparation failure")

    peer._prepare_unified_segments = fail_prepare

    async def send(message):
        calls.append(message)

    outcome = asyncio.run(peer.process_external_reply(
        event, event.result, send=send, is_current=lambda: True
    ))
    assert outcome["status"] == "not_handled"
    assert outcome["reason"] == "preparation_failed"
    assert calls == []


def test_peer_scope_exclusion_is_non_claim_and_preserves_one_fallback():
    peer = splitter_tests.Plugin()
    peer.config["unified_splitter_settings"]["conversation_blacklist"] = [
        "test:FriendMessage:1"
    ]
    runtime = FakeDailyRuntime(peer)
    event = types.SimpleNamespace(
        unified_msg_origin="test:FriendMessage:1", plugins_name=["some_other_plugin"],
        message_obj=types.SimpleNamespace(message_id="", group_id=None),
    )
    result = splitter_tests.FakeResult([splitter_tests.Plain("不要丢掉。")])
    outcome = asyncio.run(daily_delivery.handoff_reply(
        runtime, event, result, send=lambda message: asyncio.sleep(0), is_current=lambda: True
    ))
    assert outcome["status"] == "not_handled"
    assert runtime.sent == []


def test_peer_reload_after_first_segment_cancels_remaining_without_replay():
    peer = splitter_tests.Plugin()
    peer.config["unified_splitter_settings"]["split_chars"] = ["。"]
    runtime = FakeDailyRuntime(peer)
    scope = "test:FriendMessage:1"
    event = types.SimpleNamespace(
        unified_msg_origin=scope, plugins_name=["*"],
        message_obj=types.SimpleNamespace(message_id="", group_id=None),
    )
    result = splitter_tests.FakeResult([splitter_tests.Plain("第一句。第二句。第三句。")])

    async def send(message):
        runtime.sent.append((scope, message))
        runtime.peer = splitter_tests.Plugin()
        return True

    outcome = asyncio.run(daily_delivery.handoff_reply(
        runtime, event, result, send=send, is_current=lambda: True
    ))
    assert outcome["status"] == "cancelled"
    assert outcome["sent_count"] == 1
    assert len(runtime.sent) == 1


def test_handoff_does_not_repeat_tts_for_existing_record_components():
    peer = splitter_tests.Plugin()
    runtime = FakeDailyRuntime(peer)
    runtime.context.get_using_tts_provider = lambda scope: types.SimpleNamespace(
        get_audio=lambda text: (_ for _ in ()).throw(AssertionError("TTS must not rerun"))
    )
    runtime.context.get_config = lambda scope: {"provider_tts_settings": {"enable": True}}
    event = types.SimpleNamespace(
        unified_msg_origin="test:FriendMessage:1", plugins_name=["*"],
        message_obj=types.SimpleNamespace(message_id="", group_id=None),
    )
    result = splitter_tests.FakeResult([
        splitter_tests.Plain("语音前文本"),
        splitter_tests.Record(file="voice.wav"),
        splitter_tests.Plain("语音后文本"),
    ])
    outcome = asyncio.run(daily_delivery.handoff_reply(
        runtime, event, result,
        send=lambda message: asyncio.sleep(0), is_current=lambda: True,
    ))
    assert outcome["status"] == "handled"
    assert outcome["sent_count"] == 2
    delivered = [item for message in outcome["messages"] for item in message.chain]
    assert any(isinstance(item, splitter_tests.Record) for item in delivered)
    assert "语音前文本" in "".join(
        item.text for item in delivered if isinstance(item, splitter_tests.Plain)
    )
    assert "语音后文本" in "".join(
        item.text for item in delivered if isinstance(item, splitter_tests.Plain)
    )


def test_external_delivery_preserves_code_table_and_formula_boundaries():
    splitter_tests.renderer.calls.clear()
    splitter_tests.renderer.fail = False
    plugin = splitter_tests.Plugin()
    plugin.config["unified_splitter_settings"].update({
        "rich_render_full_reply_math_ratio": 0,
        "split_chars": ["。", r"\n"],
    })
    text = (
        "说明：先保留代码。\n```python\nprint('x。y')\n```\n"
        "| 名称 | 值 |\n| --- | --- |\n| A | 1 |\n"
        "公式：$$x + y = z$$\n结尾。"
    )
    event = splitter_tests.FakeEvent(text)
    sent = []

    async def send(message):
        sent.append(message)

    result = asyncio.run(plugin.process_external_reply(
        event, event.result, send=send, is_current=lambda: True
    ))
    all_units = sent + [types.SimpleNamespace(chain=event.result.chain)]
    images = [item for unit in all_units for item in unit.chain if isinstance(item, splitter_tests.Image)]
    assert result["status"] == "handled"
    assert len(images) == 2
    delivered_text = "".join(
        component.text for unit in all_units for component in unit.chain
        if isinstance(component, splitter_tests.Plain)
    )
    assert "print('x。y')" in delivered_text
    assert "x + y = z" in " ".join(splitter_tests.renderer.calls)


def test_normal_hook_preserves_output_filter_when_splitter_is_disabled():
    peer = splitter_tests.Plugin()
    peer.config["unified_splitter_settings"].update({
        "enable": False,
        "output_filter_enabled": True,
        "output_filter_rules": [{"prefix": "<think", "suffix": "</think>"}],
    })
    event = splitter_tests.FakeEvent("<think>hidden</think>visible。")
    asyncio.run(peer.unified_on_decorating_result(event))
    assert [item.text for item in event.result.chain] == ["visible。"]
    assert peer.context.sent == []
