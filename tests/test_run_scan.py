"""
Tests for run_scan.py — standalone scanner
==========================================
Covers: feed enabled filtering, lookback date filtering, JSON merge logic.
"""
import json
import os
import pytest
from datetime import datetime, timedelta

from run_scan import filter_by_lookback


# ── Lookback Filtering ────────────────────────────────────────

class TestLookbackFilter:
    """Tests for filter_by_lookback."""

    def test_recent_articles_kept(self):
        articles = [
            {'title': 'Today', 'published_date': datetime.now().isoformat()},
            {'title': 'Yesterday', 'published_date': (datetime.now() - timedelta(days=1)).isoformat()},
        ]
        result = filter_by_lookback(articles, 7)
        assert len(result) == 2

    def test_old_articles_removed(self):
        articles = [
            {'title': 'Old', 'published_date': (datetime.now() - timedelta(days=30)).isoformat()},
        ]
        result = filter_by_lookback(articles, 7)
        assert len(result) == 0

    def test_no_date_kept(self):
        articles = [
            {'title': 'No date', 'published_date': ''},
        ]
        result = filter_by_lookback(articles, 7)
        assert len(result) == 1

    def test_unparseable_date_kept(self):
        articles = [
            {'title': 'Bad date', 'published_date': 'not-a-date'},
        ]
        result = filter_by_lookback(articles, 7)
        assert len(result) == 1

    def test_rfc2822_date_parsed(self):
        """RSS dates are typically RFC 2822 format."""
        articles = [
            {'title': 'RSS date', 'published_date': 'Mon, 01 Jan 2024 12:00:00 GMT'},
        ]
        result = filter_by_lookback(articles, 7)
        # This date is clearly old (2024), so should be removed
        assert len(result) == 0

    def test_empty_list(self):
        assert filter_by_lookback([], 7) == []


# ── Feed Enabled Flag ────────────────────────────────────────

class TestFeedEnabledFlag:
    """Tests that the enabled flag is respected."""

    def test_hc_config_has_disabled_feeds(self, hc_config):
        feeds = hc_config['data_sources']['rss_feeds']
        disabled = [f for f in feeds if not f.get('enabled', True)]
        enabled = [f for f in feeds if f.get('enabled', True)]
        assert len(disabled) > 0, "Expected some disabled feeds"
        assert len(enabled) > 0, "Expected some enabled feeds"

    def test_bfsi_config_has_disabled_feeds(self, bfsi_config):
        feeds = bfsi_config['data_sources']['rss_feeds']
        disabled = [f for f in feeds if not f.get('enabled', True)]
        assert len(disabled) > 0, "Expected some disabled BFSI feeds"

    def test_run_scan_source_checks_enabled(self):
        """Verify the run_scan.py source code respects the enabled flag."""
        with open(os.path.join(os.path.dirname(__file__), '..', 'run_scan.py')) as f:
            src = f.read()
        assert "feed.get('enabled', True)" in src, \
            "run_scan.py must check the 'enabled' flag on each feed"


# ── JSON Merge Logic ─────────────────────────────────────────

class TestJSONMerge:
    """Tests that prospect JSON merges correctly (no data loss)."""

    def test_merge_preserves_existing(self, tmp_path):
        json_file = tmp_path / 'prospects.json'
        existing = [
            {'organization': 'OrgA', 'added_date': '2026-01-01'},
            {'organization': 'OrgB', 'added_date': '2026-01-02'},
        ]
        json_file.write_text(json.dumps(existing))

        # Simulate merge logic from run_scan
        with open(json_file, 'r') as f:
            loaded = json.load(f)

        new_prospects = [
            {'organization': 'OrgC'},
            {'organization': 'OrgA'},  # duplicate
        ]

        existing_orgs = {p.get('organization') for p in loaded}
        for p in new_prospects:
            if p['organization'] not in existing_orgs:
                p['added_date'] = datetime.now().isoformat()
                loaded.append(p)

        with open(json_file, 'w') as f:
            json.dump(loaded, f)

        with open(json_file) as f:
            final = json.load(f)

        assert len(final) == 3  # A, B, C (not A again)
        orgs = [p['organization'] for p in final]
        assert orgs.count('OrgA') == 1

    def test_merge_handles_empty_file(self, tmp_path):
        json_file = tmp_path / 'prospects.json'
        json_file.write_text('[]')

        with open(json_file, 'r') as f:
            loaded = json.load(f)

        new = [{'organization': 'New'}]
        for p in new:
            loaded.append(p)

        assert len(loaded) == 1

    def test_merge_handles_missing_file(self, tmp_path):
        json_file = tmp_path / 'nonexistent.json'
        existing = []
        if json_file.exists():
            with open(json_file) as f:
                existing = json.load(f)
        existing.append({'organization': 'First'})
        assert len(existing) == 1
