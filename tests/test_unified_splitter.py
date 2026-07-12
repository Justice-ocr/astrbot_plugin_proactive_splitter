import asyncio
import sys
import types


class Plain:
    def __init__(self, text=""):
        self.text = text


class Image:
    def __init__(self, file=None, **kwargs):
        self.file = file

    @staticmethod
    def fromFileSystem(path):
        return Image(file=f"file://{path}")


class Reply:
    def __init__(self, id=""):
        self.id = id


class Record:
    def __init__(self, file=None, **kwargs):
        self.file = file


class MessageChain:
    def __init__(self, components=None):
        self.chain = list(components or [])


class FakeLogger:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class FakeRenderer:
    def __init__(self):
        self.calls = []
        self.fail = False

    async def render(self, text, settings):
        self.calls.append(text)
        if self.fail:
            raise RuntimeError("render failed")
        return f"C:/tmp/render-{len(self.calls)}.png"

    async def close(self):
        return None


renderer = FakeRenderer()
api = types.ModuleType("astrbot.api")
api.logger = FakeLogger()
components = types.ModuleType("astrbot.api.message_components")
components.Image = Image
components.Plain = Plain
components.Record = Record
components.Reply = Reply
provider = types.ModuleType("astrbot.api.provider")
provider.ProviderRequest = object
event_result = types.ModuleType("astrbot.core.message.message_event_result")
event_result.MessageChain = MessageChain
session_manager = types.ModuleType("astrbot.core.star.session_llm_manager")
session_manager.SessionServiceManager = type(
    "SessionServiceManager",
    (),
    {"should_process_tts_request": staticmethod(lambda event: False)},
)

sys.modules.setdefault("astrbot", types.ModuleType("astrbot"))
sys.modules["astrbot.api"] = api
sys.modules["astrbot.api.message_components"] = components
sys.modules["astrbot.api.provider"] = provider
sys.modules.setdefault("astrbot.core", types.ModuleType("astrbot.core"))
sys.modules.setdefault("astrbot.core.message", types.ModuleType("astrbot.core.message"))
sys.modules["astrbot.core.message.message_event_result"] = event_result
sys.modules.setdefault("astrbot.core.star", types.ModuleType("astrbot.core.star"))
sys.modules["astrbot.core.star.session_llm_manager"] = session_manager

from core.unified_splitter import UnifiedSplitterMixin  # noqa: E402


class FakeResult:
    def __init__(self, chain):
        self.chain = chain

    def is_model_result(self):
        return True


class FakeEvent:
    unified_msg_origin = "test:FriendMessage:1"

    def __init__(self, text):
        self.message_obj = types.SimpleNamespace(message_id="", group_id=None)
        self.result = FakeResult([Plain(text=text)])

    def get_result(self):
        return self.result


class FakeContext:
    def __init__(self):
        self.sent = []

    async def send_message(self, session_id, chain):
        self.sent.append((session_id, chain.chain))

    def get_config(self, session_id):
        return {}


class Plugin(UnifiedSplitterMixin):
    def __init__(self):
        self.context = FakeContext()
        self._math_renderer = renderer
        self._table_renderer = renderer
        self.config = {
            "unified_splitter_settings": {
                "enable": True,
                "enable_split": True,
                "enable_rich_render": True,
                "rich_render_full_reply_math_ratio": 0,
                "split_scope": "llm_only",
                "split_mode": "simple",
                "split_chars": ["。"],
                "max_segments": 7,
                "min_segment_length": 1,
                "balanced_split_mode": False,
                "delay_strategy": "fixed",
                "fixed_delay": 0,
                "enable_tts_for_segments": False,
            }
        }


def test_rich_blocks_are_images_before_text_splitting():
    renderer.calls.clear()
    renderer.fail = False
    plugin = Plugin()
    event = FakeEvent(
        "第一句。\n| 名称 | 值 |\n| --- | --- |\n| A | 1 |\n"
        "公式：$x + y = z$。\n最后一句。"
    )
    asyncio.run(plugin.unified_on_decorating_result(event))

    all_units = [components for _, components in plugin.context.sent]
    all_units.append(event.result.chain)
    images = [item for unit in all_units for item in unit if isinstance(item, Image)]
    assert len(renderer.calls) == 2
    assert len(images) == 2
    assert all(len(unit) == 1 for unit in all_units)
    diagnostics = plugin.get_unified_splitter_diagnostics()
    assert diagnostics["render_attempts"] == 2
    assert diagnostics["render_successes"] == 2
    assert diagnostics["render_failures"] == 0
    assert diagnostics["last_result"] == "success"
    assert diagnostics["last_segments_count"] == len(all_units)


def test_render_failure_keeps_formula_as_one_plain_block():
    renderer.calls.clear()
    renderer.fail = True
    plugin = Plugin()
    event = FakeEvent("$$\nE = mc^2\n$$")
    asyncio.run(plugin.unified_on_decorating_result(event))

    assert not plugin.context.sent
    assert len(event.result.chain) == 1
    assert isinstance(event.result.chain[0], Plain)
    assert event.result.chain[0].text == "$$\nE = mc^2\n$$"
    diagnostics = plugin.get_unified_splitter_diagnostics()
    assert diagnostics["render_attempts"] == 1
    assert diagnostics["render_failures"] == 1
    assert diagnostics["last_result"] == "failure"
    assert diagnostics["last_error"] == "render failed"
    renderer.fail = False


def test_disabled_rich_render_is_counted_as_skipped():
    renderer.calls.clear()
    plugin = Plugin()
    plugin.config["unified_splitter_settings"]["enable_rich_render"] = False
    event = FakeEvent("$x + y = z$")
    asyncio.run(plugin.unified_on_decorating_result(event))

    diagnostics = plugin.get_unified_splitter_diagnostics()
    assert not renderer.calls
    assert diagnostics["render_attempts"] == 0
    assert diagnostics["render_skipped"] == 1
    assert diagnostics["last_result"] == "disabled"


def test_proactive_legacy_split_settings_cannot_override_global_rules():
    renderer.calls.clear()
    plugin = Plugin()
    event = FakeEvent("第一句。第二句。")
    event.__proactive_chat_event = True
    event.__proactive_segmented_settings = {
        "enable": False,
        "split_mode": "regex",
        "regex": r".+$",
    }

    settings = plugin._get_unified_splitter_config(event)
    assert settings["enable_split"] is True
    assert "proactive_legacy_settings" not in settings

    asyncio.run(plugin.unified_on_decorating_result(event))
    all_units = [components for _, components in plugin.context.sent]
    all_units.append(event.result.chain)
    assert [component.text for unit in all_units for component in unit if isinstance(component, Plain)] == [
        "第一句。",
        "第二句。",
    ]


def test_formula_heavy_reply_is_rendered_as_one_complete_image():
    renderer.calls.clear()
    plugin = Plugin()
    plugin.config["unified_splitter_settings"].update(
        {
            "rich_render_full_reply_math_ratio": 35,
            "rich_render_full_reply_max_chars": 1600,
        }
    )
    event = FakeEvent("推导如下。\n$$\\frac{1}{a}+\\frac{1}{b}=1$$\n因此结论成立。")
    asyncio.run(plugin.unified_on_decorating_result(event))

    assert len(renderer.calls) == 1
    assert "推导如下" in renderer.calls[0]
    assert "\\frac{1}{a}" in renderer.calls[0]
    assert len(event.result.chain) == 1
    assert isinstance(event.result.chain[0], Image)
    diagnostics = plugin.get_unified_splitter_diagnostics()
    assert diagnostics["last_full_reply_rendered"] is True
    assert diagnostics["last_full_reply_images"] == 1
    assert diagnostics["last_math_ratio"] >= 0.35


def test_long_formula_heavy_reply_is_split_into_multiple_images():
    renderer.calls.clear()
    plugin = Plugin()
    plugin.config["unified_splitter_settings"].update(
        {
            "rich_render_full_reply_math_ratio": 20,
            "rich_render_full_reply_max_chars": 200,
        }
    )
    paragraphs = [
        f"第 {index} 步推导：$\\frac{{{index}}}{{n}} + \\sqrt{{x_{index}^2+y_{index}^2}} = z_{index}$。"
        + "补充说明。" * 12
        for index in range(1, 5)
    ]
    event = FakeEvent("\n\n".join(paragraphs))
    asyncio.run(plugin.unified_on_decorating_result(event))

    all_units = [components for _, components in plugin.context.sent]
    all_units.append(event.result.chain)
    assert len(renderer.calls) > 1
    assert all(any(isinstance(item, Image) for item in unit) for unit in all_units)
    diagnostics = plugin.get_unified_splitter_diagnostics()
    assert diagnostics["last_full_reply_images"] == len(renderer.calls)


def test_reverse_replace_is_applied_to_user_prompt():
    plugin = Plugin()
    plugin.config["unified_splitter_settings"].update(
        {
            "reverse_replace": True,
            "replace_rules": [{"find": "原词", "replace": "显示词"}],
        }
    )
    request = types.SimpleNamespace(system_prompt="", prompt="用户输入显示词")
    asyncio.run(plugin.unified_on_llm_request(FakeEvent(""), request))
    assert request.prompt == "用户输入原词"
