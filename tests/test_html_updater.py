"""
Tests for outputs/html_updater.py — HTMLUpdater
================================================
Covers: timestamp updates, card insertion, deduplication,
        BFSI vs HC color logic, offer suggestion.
"""
import re
import pytest
from outputs.html_updater import HTMLUpdater


# ── Initialization ────────────────────────────────────────────

class TestInit:
    """Tests for HTMLUpdater initialization."""

    def test_hc_not_bfsi(self, hc_config):
        u = HTMLUpdater(hc_config)
        assert u.is_bfsi is False

    def test_bfsi_detected(self, bfsi_config):
        u = HTMLUpdater(bfsi_config)
        assert u.is_bfsi is True

    def test_html_path_set(self, hc_config):
        u = HTMLUpdater(hc_config)
        assert u.html_path == hc_config['output']['html_file']


# ── Timestamp Banner ─────────────────────────────────────────

class TestTimestampBanner:
    """Tests for record_scan and _update_timestamp."""

    def test_record_scan_updates_banner(self, tmp_html):
        config, html_file = tmp_html
        u = HTMLUpdater(config)
        assert u.record_scan(prospect_count=0) is True

        with open(html_file) as f:
            html = f.read()
        assert 'Last scanned:' in html
        assert 'No new prospects' in html

    def test_record_scan_with_prospects(self, tmp_html):
        config, html_file = tmp_html
        u = HTMLUpdater(config)
        u.record_scan(prospect_count=3)

        with open(html_file) as f:
            html = f.read()
        assert '3 new prospects added' in html

    def test_record_scan_missing_file(self, hc_config):
        config = hc_config.copy()
        config['output'] = hc_config['output'].copy()
        config['output']['html_file'] = '/nonexistent/path.html'
        u = HTMLUpdater(config)
        assert u.record_scan() is False


# ── Card Insertion ────────────────────────────────────────────

class TestCardInsertion:
    """Tests for update() card insertion."""

    def _make_prospect(self, org='Test Health System', score=75):
        return {
            'organization': org,
            'signal': 'Cloud migration announced',
            'source_url': 'https://example.com',
            'source_date': '2026-02-01',
            'source_name': 'Healthcare IT News',
            'qualification_score': score,
            'rackspace_wedge': 'Managed private cloud',
            'ai_agent_use_case': 'Patient flow optimization',
            'category': 'Health System',
            'priority': 'High',
        }

    def test_inserts_card(self, tmp_html):
        config, html_file = tmp_html
        u = HTMLUpdater(config)
        prospect = self._make_prospect()
        assert u.update([prospect]) is True

        with open(html_file) as f:
            html = f.read()
        assert 'Test Health System' in html
        assert '<!-- NEW PROSPECT: Test Health System' in html

    def test_inserts_without_dedup(self, tmp_html):
        """Dedup is handled by IdempotencyManifest upstream.
        html_updater trusts its input — calling update() twice
        should produce two cards (manifest prevents this in practice)."""
        config, html_file = tmp_html
        u = HTMLUpdater(config)
        prospect = self._make_prospect()

        u.update([prospect])
        u.update([prospect])  # would be blocked by manifest in real pipeline

        with open(html_file) as f:
            html = f.read()
        count = html.count('<!-- NEW PROSPECT: Test Health System')
        assert count == 2, f"Expected 2 cards (no HTML dedup), found {count}"

    def test_multiple_unique_prospects(self, tmp_html):
        config, html_file = tmp_html
        u = HTMLUpdater(config)
        prospects = [
            self._make_prospect('Org A'),
            self._make_prospect('Org B'),
        ]
        u.update(prospects)

        with open(html_file) as f:
            html = f.read()
        assert '<!-- NEW PROSPECT: Org A' in html
        assert '<!-- NEW PROSPECT: Org B' in html


# ── Card Content ──────────────────────────────────────────────

class TestCardContent:
    """Tests for _generate_single_card HTML structure."""

    def _make_prospect(self, **overrides):
        base = {
            'organization': 'TestOrg',
            'signal': 'Test signal',
            'source_url': 'https://example.com',
            'source_date': '2026-02-01',
            'source_name': 'Test Source',
            'qualification_score': 80,
            'rackspace_wedge': 'HIPAA-compliant hosting',
            'ai_agent_use_case': 'Patient flow optimization',
            'category': 'Health System',
            'priority': 'High',
        }
        base.update(overrides)
        return base

    def test_card_has_required_sections(self, hc_config):
        u = HTMLUpdater(hc_config)
        card = u._generate_single_card(self._make_prospect())
        assert 'card-header' in card
        assert 'info-grid' in card
        assert 'intelligence-section' in card
        assert 'score-badge' in card

    def test_hc_uses_plum_color(self, hc_config):
        u = HTMLUpdater(hc_config)
        card = u._generate_single_card(self._make_prospect())
        assert 'var(--plum)' in card

    def test_bfsi_uses_blue_color(self, bfsi_config):
        u = HTMLUpdater(bfsi_config)
        card = u._generate_single_card(self._make_prospect())
        assert 'var(--blue-primary)' in card


# ── Offer Suggestion ─────────────────────────────────────────

class TestOfferSuggestion:
    """Tests for _suggest_offer."""

    def test_migration_offer(self, hc_config):
        u = HTMLUpdater(hc_config)
        p = {'rackspace_wedge': 'Post-migration optimization', 'ai_agent_use_case': ''}
        assert 'Migration' in u._suggest_offer(p)

    def test_compliance_offer(self, hc_config):
        u = HTMLUpdater(hc_config)
        p = {'rackspace_wedge': 'HIPAA-compliant hosting', 'ai_agent_use_case': ''}
        assert 'Compliance' in u._suggest_offer(p)

    def test_ai_offer(self, hc_config):
        u = HTMLUpdater(hc_config)
        p = {'rackspace_wedge': '', 'ai_agent_use_case': 'AI fraud detection'}
        assert 'AI' in u._suggest_offer(p)
