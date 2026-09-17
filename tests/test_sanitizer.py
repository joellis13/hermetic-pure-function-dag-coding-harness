"""Tests for hermetic.data.sanitizer — JSON cleaning for raw LLM output."""
import json
import pytest

from hermetic.data.sanitizer import sanitize_json, SanitizationError


def _parsed(raw: str) -> dict | list:
    result = sanitize_json(raw)
    assert isinstance(result, str), f"Expected str, got SanitizationError: {result}"
    return json.loads(result)


class TestMarkdownFenceStripping:
    def test_json_fence(self):
        raw = '```json\n{"key": "value"}\n```'
        assert _parsed(raw) == {"key": "value"}

    def test_bare_fence(self):
        raw = '```\n{"key": "value"}\n```'
        assert _parsed(raw) == {"key": "value"}

    def test_fence_with_preamble(self):
        raw = 'Here is the plan:\n```json\n{"key": "value"}\n```\nDone.'
        assert _parsed(raw) == {"key": "value"}

    def test_no_fence_plain_json(self):
        raw = '{"key": "value"}'
        assert _parsed(raw) == {"key": "value"}


class TestProseStripping:
    def test_leading_prose(self):
        raw = 'Sure! Here is the JSON output:\n{"key": "value"}'
        assert _parsed(raw) == {"key": "value"}

    def test_trailing_prose(self):
        raw = '{"key": "value"}\nI hope this helps!'
        assert _parsed(raw) == {"key": "value"}

    def test_prose_with_array_of_objects(self):
        raw = 'Here is the list:\n[{"a": 1}, {"b": 2}]\nHope this helps!'
        assert _parsed(raw) == [{"a": 1}, {"b": 2}]

    def test_prose_with_single_item_array(self):
        raw = 'Here is the list:\n[{"a": 1}]\nHope this helps!'
        assert _parsed(raw) == [{"a": 1}]

    def test_prose_with_bracket_in_prose_before_object(self):
        raw = 'See note [1] for details:\n{"key": "value"}\nDone'
        assert _parsed(raw) == {"key": "value"}

    def test_prose_with_brace_in_prose_before_array(self):
        raw = 'Using {placeholder} pattern:\n[1, 2, 3]\nDone'
        assert _parsed(raw) == [1, 2, 3]

    def test_prose_inside_markdown_fence(self):
        raw = '```json\nHere is the plan:\n{"key": "value"}\nDone\n```'
        assert _parsed(raw) == {"key": "value"}

    def test_nested_array_of_objects_with_trailing_comma_and_prose(self):
        raw = 'Here is the result:\n[{"a": 1,}, {"b": 2,},]\nHope this helps!'
        assert _parsed(raw) == [{"a": 1}, {"b": 2}]


class TestTrailingCommaRemoval:
    def test_trailing_comma_in_object(self):
        raw = '{"a": 1, "b": 2,}'
        assert _parsed(raw) == {"a": 1, "b": 2}

    def test_trailing_comma_in_array(self):
        raw = '[1, 2, 3,]'
        assert _parsed(raw) == [1, 2, 3]

    def test_trailing_comma_nested(self):
        raw = '{"a": [1, 2,], "b": {"c": 3,}}'
        assert _parsed(raw) == {"a": [1, 2], "b": {"c": 3}}

    def test_fence_plus_trailing_comma(self):
        raw = '```json\n{"a": 1,}\n```'
        assert _parsed(raw) == {"a": 1}


class TestSanitizationError:
    def test_truly_broken_json_returns_error(self):
        raw = "this is not json at all"
        result = sanitize_json(raw)
        assert isinstance(result, SanitizationError)
        assert result.raw_text == raw
        assert len(result.error_message) > 0

    def test_error_has_repaired_text(self):
        raw = "```json\n{broken\n```"
        result = sanitize_json(raw)
        assert isinstance(result, SanitizationError)
        # repaired_text should at least be the fence-stripped version
        assert "```" not in result.repaired_text

    def test_valid_json_never_returns_error(self):
        valid_inputs = [
            '{}',
            '[]',
            '{"a": null}',
            '[1, "two", true, null]',
        ]
        for raw in valid_inputs:
            result = sanitize_json(raw)
            assert isinstance(result, str), f"Unexpectedly got error for: {raw!r}"
