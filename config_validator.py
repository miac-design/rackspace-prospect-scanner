#!/usr/bin/env python3
"""
Config Validator
================
Validates agent_config.json and bfsi_agent_config.json against a strict schema.
Hard-fails on missing keys instead of silently using defaults.

Usage:
    python config_validator.py
"""
import json
import sys


# Required schema definition
REQUIRED_SCHEMA = {
    'agent_name': str,
    'data_sources': {
        'rss_feeds': list,
        'lookback_days': int,
    },
    'qualification_criteria': dict,
    'qualification_threshold': int,
    'rackspace_value_propositions': list,
    'ai_agent_use_cases': list,
    'categories': dict,
    'output': {
        'html_file': str,
        'prospects_json': str,
        'log_file': str,
    },
}

FEED_REQUIRED_KEYS = ['name', 'url']


def validate_type(value, expected, path=''):
    """Validate a value matches the expected type."""
    if isinstance(expected, dict):
        if not isinstance(value, dict):
            return [f"  ❌ {path}: Expected dict, got {type(value).__name__}"]
        errors = []
        for key, sub_expected in expected.items():
            if key not in value:
                errors.append(f"  ❌ {path}.{key}: MISSING (required)")
            else:
                errors.extend(validate_type(value[key], sub_expected, f"{path}.{key}"))
        return errors
    elif isinstance(expected, type):
        if not isinstance(value, expected):
            return [f"  ❌ {path}: Expected {expected.__name__}, got {type(value).__name__}"]
    return []


def validate_config(config_path: str) -> list:
    """Validate a config file against the schema. Returns list of errors."""
    errors = []
    
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        return [f"  ❌ Invalid JSON: {e}"]
    except FileNotFoundError:
        return [f"  ❌ File not found: {config_path}"]
    
    # Validate top-level schema
    errors.extend(validate_type(config, REQUIRED_SCHEMA, 'config'))
    
    # Validate feeds have required keys
    feeds = config.get('data_sources', {}).get('rss_feeds', [])
    for i, feed in enumerate(feeds):
        for key in FEED_REQUIRED_KEYS:
            if key not in feed:
                errors.append(f"  ❌ config.data_sources.rss_feeds[{i}]: Missing '{key}'")
    
    # Validate threshold is reasonable
    threshold = config.get('qualification_threshold', 0)
    if threshold < 1 or threshold > 100:
        errors.append(f"  ❌ qualification_threshold={threshold} out of range [1, 100]")
    
    # Validate lookback_days
    lookback = config.get('data_sources', {}).get('lookback_days', 0)
    if lookback < 1 or lookback > 90:
        errors.append(f"  ❌ lookback_days={lookback} out of range [1, 90]")
    
    # Validate qualification criteria have weight + keywords
    criteria = config.get('qualification_criteria', {})
    for name, criterion in criteria.items():
        if 'weight' not in criterion:
            errors.append(f"  ❌ criteria.{name}: Missing 'weight'")
        if 'keywords' not in criterion:
            errors.append(f"  ❌ criteria.{name}: Missing 'keywords'")
        elif not isinstance(criterion['keywords'], list) or len(criterion['keywords']) == 0:
            errors.append(f"  ❌ criteria.{name}.keywords: Must be non-empty list")
    
    # Validate categories have keywords
    categories = config.get('categories', {})
    for cat_name, cat_config in categories.items():
        if 'keywords' not in cat_config:
            errors.append(f"  ❌ categories.{cat_name}: Missing 'keywords'")
    
    # Cross-contamination check
    agent_name = config.get('agent_name', '').lower()
    cat_names = list(categories.keys())
    if 'healthcare' in agent_name and 'bfsi' in cat_names:
        errors.append(f"  ❌ Healthcare config contains BFSI category (cross-contamination)")
    if 'bfsi' in agent_name and 'health_system' in cat_names:
        errors.append(f"  ❌ BFSI config contains health_system category (cross-contamination)")
    
    return errors


def main():
    """Validate all config files."""
    configs = ['agent_config.json', 'bfsi_agent_config.json']
    total_errors = 0
    
    for config_path in configs:
        print(f"\n📋 Validating {config_path}...")
        errors = validate_config(config_path)
        
        if errors:
            print(f"  ❌ {len(errors)} error(s):")
            for err in errors:
                print(err)
            total_errors += len(errors)
        else:
            # Count feeds
            with open(config_path) as f:
                cfg = json.load(f)
            feeds = cfg['data_sources']['rss_feeds']
            enabled = sum(1 for f in feeds if f.get('enabled', True))
            disabled = len(feeds) - enabled
            criteria_count = len(cfg['qualification_criteria'])
            print(f"  ✅ Valid ({enabled} active feeds, {disabled} disabled, {criteria_count} criteria)")
    
    print()
    if total_errors > 0:
        print(f"❌ VALIDATION FAILED: {total_errors} error(s)")
        sys.exit(1)
    else:
        print("✅ All configs valid")
        sys.exit(0)


if __name__ == '__main__':
    main()
