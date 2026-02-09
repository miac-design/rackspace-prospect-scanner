"""
Tests for config_validator.py
==============================
Covers: schema validation, type checking, range validation,
        cross-contamination detection, feed structure validation.
"""
import json
import pytest
from config_validator import validate_config, validate_type


class TestSchemaValidation:
    """Tests for validate_type recursive schema checker."""

    def test_valid_simple_type(self):
        assert validate_type('hello', str, 'test') == []

    def test_invalid_simple_type(self):
        errors = validate_type(123, str, 'test')
        assert len(errors) == 1
        assert 'Expected str' in errors[0]

    def test_missing_nested_key(self):
        schema = {'name': str, 'age': int}
        value = {'name': 'Alice'}
        errors = validate_type(value, schema, 'config')
        assert len(errors) == 1
        assert 'MISSING' in errors[0]

    def test_valid_nested(self):
        schema = {'output': {'html_file': str}}
        value = {'output': {'html_file': 'test.html'}}
        assert validate_type(value, schema, 'config') == []


class TestConfigValidation:
    """Tests for validate_config against real configs."""

    def test_hc_config_valid(self):
        errors = validate_config('agent_config.json')
        assert errors == [], f"HC config has errors: {errors}"

    def test_bfsi_config_valid(self):
        errors = validate_config('bfsi_agent_config.json')
        assert errors == [], f"BFSI config has errors: {errors}"

    def test_missing_file(self):
        errors = validate_config('nonexistent.json')
        assert len(errors) == 1
        assert 'File not found' in errors[0]

    def test_invalid_json(self, tmp_path):
        bad_file = tmp_path / 'bad.json'
        bad_file.write_text('{not valid json}}}')
        errors = validate_config(str(bad_file))
        assert len(errors) == 1
        assert 'Invalid JSON' in errors[0]


class TestRangeValidation:
    """Tests for threshold and lookback range checks."""

    def test_threshold_out_of_range(self, tmp_path):
        cfg = _make_minimal_config()
        cfg['qualification_threshold'] = 999
        path = tmp_path / 'test.json'
        path.write_text(json.dumps(cfg))
        errors = validate_config(str(path))
        assert any('out of range' in e for e in errors)

    def test_lookback_out_of_range(self, tmp_path):
        cfg = _make_minimal_config()
        cfg['data_sources']['lookback_days'] = 200
        path = tmp_path / 'test.json'
        path.write_text(json.dumps(cfg))
        errors = validate_config(str(path))
        assert any('out of range' in e for e in errors)


class TestCrossContamination:
    """Tests for cross-contamination detection."""

    def test_hc_with_bfsi_category_flagged(self, tmp_path):
        cfg = _make_minimal_config()
        cfg['agent_name'] = 'Healthcare Prospect Agent'
        cfg['categories']['bfsi'] = {'keywords': ['bank']}
        path = tmp_path / 'test.json'
        path.write_text(json.dumps(cfg))
        errors = validate_config(str(path))
        assert any('cross-contamination' in e.lower() for e in errors)

    def test_bfsi_with_health_system_flagged(self, tmp_path):
        cfg = _make_minimal_config()
        cfg['agent_name'] = 'BFSI Prospect Agent'
        cfg['categories']['health_system'] = {'keywords': ['hospital']}
        path = tmp_path / 'test.json'
        path.write_text(json.dumps(cfg))
        errors = validate_config(str(path))
        assert any('cross-contamination' in e.lower() for e in errors)


class TestFeedValidation:
    """Tests for feed structure validation."""

    def test_feed_missing_url(self, tmp_path):
        cfg = _make_minimal_config()
        cfg['data_sources']['rss_feeds'] = [{'name': 'Test Feed'}]
        path = tmp_path / 'test.json'
        path.write_text(json.dumps(cfg))
        errors = validate_config(str(path))
        assert any("Missing 'url'" in e for e in errors)

    def test_feed_missing_name(self, tmp_path):
        cfg = _make_minimal_config()
        cfg['data_sources']['rss_feeds'] = [{'url': 'https://example.com/rss'}]
        path = tmp_path / 'test.json'
        path.write_text(json.dumps(cfg))
        errors = validate_config(str(path))
        assert any("Missing 'name'" in e for e in errors)

    def test_criteria_missing_weight(self, tmp_path):
        cfg = _make_minimal_config()
        cfg['qualification_criteria'] = {'test': {'keywords': ['a']}}
        path = tmp_path / 'test.json'
        path.write_text(json.dumps(cfg))
        errors = validate_config(str(path))
        assert any("Missing 'weight'" in e for e in errors)


# ── Helper ────────────────────────────────────────────────────

def _make_minimal_config() -> dict:
    """Create a minimal valid config for testing."""
    return {
        'agent_name': 'Test Agent',
        'data_sources': {
            'rss_feeds': [{'name': 'Test', 'url': 'https://test.com/rss'}],
            'lookback_days': 7,
        },
        'qualification_criteria': {
            'test_criterion': {'weight': 20, 'keywords': ['test']},
        },
        'qualification_threshold': 65,
        'rackspace_value_propositions': ['test'],
        'ai_agent_use_cases': ['test'],
        'categories': {
            'general': {'keywords': ['general']},
        },
        'output': {
            'html_file': 'test.html',
            'prospects_json': 'test.json',
            'log_file': 'test.log',
        },
    }
