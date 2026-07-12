import json
from pathlib import Path


def test_legacy_session_split_settings_are_not_exposed():
    schema_path = Path(__file__).resolve().parents[1] / "_conf_schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert "segmented_reply_settings" not in schema["friend_settings"]["items"]
    assert "segmented_reply_settings" not in schema["group_settings"]["items"]
