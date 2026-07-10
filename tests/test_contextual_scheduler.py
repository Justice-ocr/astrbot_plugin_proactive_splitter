import asyncio
import sys
import types
from datetime import timezone


class FakeLogger:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


api = sys.modules.get("astrbot.api") or types.ModuleType("astrbot.api")
api.logger = getattr(api, "logger", FakeLogger())
sys.modules.setdefault("astrbot", types.ModuleType("astrbot"))
sys.modules["astrbot.api"] = api

from core.contextual_scheduler import ContextualSchedulePlanner


class Plugin:
    def __init__(self, last_text=""):
        self.timezone = timezone.utc
        self.context = None
        self.data_lock = asyncio.Lock()
        self.session_temp_state = {
            "test:FriendMessage:1": {"last_user_text": last_text}
        }


class FakeContext:
    async def get_current_chat_provider_id(self, session_id):
        return "test-provider"

    async def llm_generate(self, **kwargs):
        return types.SimpleNamespace(
            completion_text=(
                '{"delay_minutes": 75, "reason": "用户稍后回来", '
                '"confidence": 0.9}'
            )
        )


def test_explicit_delay_is_detected_and_clamped():
    planner = ContextualSchedulePlanner(Plugin())
    prediction = planner._predict_from_text("2 小时后再聊", 30 * 60, 180 * 60)
    assert prediction["rule"] == "explicit_delay"
    assert prediction["interval_seconds"] == 120 * 60


def test_llm_json_prediction_is_parsed():
    planner = ContextualSchedulePlanner(Plugin())
    prediction = planner._parse_llm_result(
        '```json\n{"delay_minutes": 90, "reason": "用户在开会", "confidence": 0.8}\n```',
        30 * 60,
        180 * 60,
    )
    assert prediction["interval_seconds"] == 90 * 60
    assert prediction["rule"] == "llm_context"


def test_plan_falls_back_to_recent_text_rule_when_llm_unavailable():
    plugin = Plugin("我先开会，2 小时后再聊")
    planner = ContextualSchedulePlanner(plugin)
    plan = asyncio.run(
        planner.build_plan(
            "test:FriendMessage:1",
            {
                "schedule_settings": {
                    "min_interval_minutes": 30,
                    "max_interval_minutes": 180,
                    "enable_contextual_timing": True,
                }
            },
        )
    )
    assert plan["interval_seconds"] == 120 * 60
    assert plan["source"] == "recent_context_fallback"
    assert plan["next_trigger_time"] > plan["scheduled_at"]


def test_plan_prefers_llm_prediction_when_available():
    plugin = Plugin("我晚点回来")
    plugin.context = FakeContext()
    planner = ContextualSchedulePlanner(plugin)
    plan = asyncio.run(
        planner.build_plan(
            "test:FriendMessage:1",
            {
                "schedule_settings": {
                    "min_interval_minutes": 30,
                    "max_interval_minutes": 180,
                    "enable_contextual_timing": True,
                }
            },
        )
    )
    assert plan["interval_seconds"] == 75 * 60
    assert plan["source"] == "llm_context"
