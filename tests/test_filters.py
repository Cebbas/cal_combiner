"""Unit tests for per-source filtering and rename-rule logic in calendar.py.

These are pure functions (plain dicts in, dict/bool out) so they're tested
directly without a running Home Assistant instance.
"""
from custom_components.cal_combiner.calendar import (
    _apply_rename,
    _extract_field_text,
    _matches_filter,
    _parse_merged_uid,
)

EVENT = {
    "summary": "Fotboll // FC Zoo",
    "description": "Ta med vattenflaska",
    "location": "Zoo-planen",
}


# ---- _extract_field_text ----


def test_extract_field_any_joins_all_fields():
    text = _extract_field_text(EVENT, "any")
    assert "Fotboll" in text and "vattenflaska" in text and "Zoo-planen" in text


def test_extract_field_missing_returns_empty_string():
    assert _extract_field_text({}, "summary") == ""


# ---- _matches_filter ----


def test_no_rule_always_matches():
    assert _matches_filter(EVENT, None) is True
    assert _matches_filter(EVENT, {}) is True


def test_include_keyword_match():
    assert _matches_filter(EVENT, {"include": ["zoo"]}) is True


def test_include_keyword_no_match_excludes():
    assert _matches_filter(EVENT, {"include": ["hockey"]}) is False


def test_exclude_keyword_match_excludes():
    assert _matches_filter(EVENT, {"exclude": ["zoo"]}) is False


def test_include_and_exclude_combined():
    rule = {"include": ["fotboll"], "exclude": ["zoo"]}
    assert _matches_filter(EVENT, rule) is False


def test_case_insensitive_by_default():
    assert _matches_filter(EVENT, {"include": ["FOTBOLL"]}) is True


def test_case_sensitive_mismatch_fails():
    rule = {"include": ["FOTBOLL"], "case_sensitive": True}
    assert _matches_filter(EVENT, rule) is False


def test_case_sensitive_match_succeeds():
    rule = {"include": ["Fotboll"], "case_sensitive": True}
    assert _matches_filter(EVENT, rule) is True


def test_field_targets_only_that_field():
    rule = {"field": "location", "include": ["fotboll"]}
    assert _matches_filter(EVENT, rule) is False
    rule = {"field": "location", "include": ["zoo-planen"]}
    assert _matches_filter(EVENT, rule) is True


def test_regex_mode_matches_pattern():
    rule = {"use_regex": True, "include": [r"^Fotboll \/\/"]}
    assert _matches_filter(EVENT, rule) is True


def test_regex_invalid_pattern_treated_as_no_match():
    rule = {"use_regex": True, "include": ["("]}
    assert _matches_filter(EVENT, rule) is False


# ---- _apply_rename ----


def test_no_rules_leaves_fields_unchanged():
    result = _apply_rename(EVENT, None)
    assert result == {
        "summary": "Fotboll // FC Zoo",
        "description": "Ta med vattenflaska",
        "location": "Zoo-planen",
    }


def test_empty_pattern_rule_is_skipped():
    rules = [{"pattern": "", "replacement": "x"}]
    result = _apply_rename(EVENT, rules)
    assert result["summary"] == "Fotboll // FC Zoo"


def test_strips_suffix_then_renames_remainder():
    rules = [
        {"pattern": r" // .*$", "replacement": ""},
        {"pattern": r"^Fotboll$", "replacement": "Fotbolls Träning"},
    ]
    result = _apply_rename(EVENT, rules)
    assert result["summary"] == "Fotbolls Träning"


def test_capture_group_backreference():
    rules = [{"pattern": r"^(\w+) // (.+)$", "replacement": r"\2: \1"}]
    result = _apply_rename(EVENT, rules)
    assert result["summary"] == "FC Zoo: Fotboll"


def test_rule_can_target_description_field():
    rules = [{"field": "description", "pattern": "vattenflaska", "replacement": "boll"}]
    result = _apply_rename(EVENT, rules)
    assert result["description"] == "Ta med boll"
    assert result["summary"] == "Fotboll // FC Zoo"


def test_rule_targeting_unset_field_is_skipped():
    item = {"summary": "Fotboll"}
    rules = [{"field": "description", "pattern": "x", "replacement": "y"}]
    result = _apply_rename(item, rules)
    assert result["description"] is None


def test_invalid_regex_pattern_leaves_field_unchanged():
    rules = [{"pattern": "(", "replacement": "x"}]
    result = _apply_rename(EVENT, rules)
    assert result["summary"] == "Fotboll // FC Zoo"


def test_missing_summary_defaults_to_empty_string():
    result = _apply_rename({}, None)
    assert result["summary"] == ""


# ---- _parse_merged_uid ----


def test_parse_merged_uid_splits_on_separator():
    assert _parse_merged_uid("calendar.school::abc-123") == ("calendar.school", "abc-123")


def test_parse_merged_uid_keeps_only_first_split():
    assert _parse_merged_uid("calendar.school::abc::123") == ("calendar.school", "abc::123")


def test_parse_merged_uid_returns_none_without_separator():
    assert _parse_merged_uid("plain-uid") is None
