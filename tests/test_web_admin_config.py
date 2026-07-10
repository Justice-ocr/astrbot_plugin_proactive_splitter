import asyncio
import sys
import types
from pathlib import Path


class FakeLogger:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


astrbot = sys.modules.setdefault("astrbot", types.ModuleType("astrbot"))
api = sys.modules.setdefault("astrbot.api", types.ModuleType("astrbot.api"))
api.logger = FakeLogger()
astrbot.api = api

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from astrbot_plugin_proactive_splitter.core.web_admin_server import (  # noqa: E402
    WebAdminServer,
)


class FakeTelemetry:
    def __init__(self):
        self.updated_config = None

    def update_config(self, config):
        self.updated_config = config


class FakePlugin:
    def __init__(self, config):
        self.config = config
        self.context = None
        self.telemetry = FakeTelemetry()


def build_server(config):
    server = WebAdminServer.__new__(WebAdminServer)
    server.plugin = FakePlugin(config)
    server.config = config
    server._native_config = None
    server._auth_enabled = True
    server._save_plugin_config = lambda: (True, None)

    async def broadcast_update(_kind):
        return None

    server._broadcast_update = broadcast_update
    return server


def test_config_payload_exposes_all_sections_without_password():
    config = {
        "friend_settings": {"enable": True},
        "group_settings": {"enable": False},
        "web_admin": {"enabled": True, "password": "secret"},
        "notification_settings": {"enabled": True},
        "unified_splitter_settings": {"enable_rich_render": True},
        "telemetry_config": {"enabled": False},
    }
    payload = build_server(config)._build_config_payload()

    assert tuple(payload) == WebAdminServer.CONFIG_SECTION_KEYS
    assert "password" not in payload["web_admin"]
    assert payload["unified_splitter_settings"]["enable_rich_render"] is True
    assert payload["telemetry_config"]["enabled"] is False


def test_config_update_persists_all_sections_and_refreshes_telemetry():
    config = {
        "web_admin": {"enabled": True, "password": "secret"},
        "telemetry_config": {"enabled": True},
    }
    server = build_server(config)
    payload = {
        "friend_settings": {"enable": True},
        "group_settings": {"enable": True},
        "web_admin": {"enabled": False},
        "notification_settings": {"enabled": True},
        "unified_splitter_settings": {
            "enable_rich_render": True,
            "replace_rules": [{"find": "A", "replace": "B"}],
        },
        "telemetry_config": {"enabled": False},
    }

    result = asyncio.run(server._apply_config_payload(payload))

    assert result["ok"] is True
    assert config["web_admin"]["password"] == "secret"
    assert config["unified_splitter_settings"] == payload["unified_splitter_settings"]
    assert config["telemetry_config"]["enabled"] is False
    assert (
        server.plugin.telemetry.updated_config["telemetry_config"]["enabled"] is False
    )


def test_unanswered_limit_session_remains_visible_as_paused_job():
    server = build_server({"friend_settings": {}, "web_admin": {}})
    session_id = "default:FriendMessage:123"
    session_config = {
        "enable": True,
        "schedule_settings": {"max_unanswered_times": 4},
        "context_settings": {"source_mode": "conversation_history"},
    }
    plugin = server.plugin
    plugin.scheduler = None
    plugin.session_data = {session_id: {"unanswered_count": 4}}
    plugin.manual_trigger_sessions = set()
    plugin.timezone = None
    plugin._normalize_session_id = lambda value: value
    plugin._parse_session_id = lambda _value: ("default", "FriendMessage", "123")
    plugin._get_session_config = lambda _session: session_config
    plugin._is_unanswered_limit_reached = lambda _session, _config, unanswered: (
        unanswered >= 4
    )
    plugin._get_max_unanswered_count = lambda _config: 4
    plugin._get_session_name = lambda _session, _config: "测试会话"
    plugin._get_session_display_name = lambda _session, _config: "测试会话"
    server._list_known_sessions = lambda: [session_id]

    jobs = server._collect_jobs()

    assert len(jobs) == 1
    assert jobs[0]["status"] == "paused_unanswered"
    assert jobs[0]["paused"] is True
    assert jobs[0]["has_scheduler_job"] is False
    assert "等待用户回复" in jobs[0]["inactive_reason"]
