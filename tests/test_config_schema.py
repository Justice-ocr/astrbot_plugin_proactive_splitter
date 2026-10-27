import json
from pathlib import Path


def test_legacy_session_split_settings_are_not_exposed():
    schema_path = Path(__file__).resolve().parents[1] / "_conf_schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert "segmented_reply_settings" not in schema["friend_settings"]["items"]
    assert "segmented_reply_settings" not in schema["group_settings"]["items"]


def test_output_filter_template_exposes_both_modes_in_one_dropdown():
    schema_path = Path(__file__).resolve().parents[1] / "_conf_schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    templates = schema["unified_splitter_settings"]["items"]["output_filter_rules"]["templates"]
    assert len(templates) == 1
    items = next(iter(templates.values()))["items"]
    mode = items["rule_type"]
    assert mode["options"] == ["prefix_suffix", "suffix_only"]
    assert len(mode["labels"]) == len(mode["options"])
    assert mode["default"] == "prefix_suffix"
    assert {"prefix", "suffix", "match_scope", "unclosed_action"} <= items.keys()
