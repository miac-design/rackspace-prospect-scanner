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


class TestVendorBadges:
    """Tests for Current Vendors chips sourced from website enrichment."""

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

    def test_vendor_badges_rendered_from_website_data(self, hc_config):
        u = HTMLUpdater(hc_config)
        prospect = self._make_prospect(website_data={
            'tech_stack_hints': ['aws', 'google cloud', 'kubernetes'],
        })
        card = u._generate_single_card(prospect)
        assert 'Current Vendors' in card
        assert '<span class="vendor-badge">AWS</span>' in card
        assert '<span class="vendor-badge">Google Cloud</span>' in card
        assert '<span class="vendor-badge">Kubernetes</span>' in card

    def test_vendor_badges_deduped_and_mapped(self, hc_config):
        u = HTMLUpdater(hc_config)
        prospect = self._make_prospect(website_data={
            'tech_stack_hints': ['aws', 'amazon web services', 'gcp', 'google cloud'],
        })
        badges = u._generate_vendor_badges(prospect)
        assert badges.count('AWS') == 1
        assert badges.count('Google Cloud') == 1

    def test_no_website_data_omits_vendor_section(self, hc_config):
        u = HTMLUpdater(hc_config)
        card = u._generate_single_card(self._make_prospect())
        assert 'Current Vendors' not in card

    def test_non_vendor_hints_ignored(self, hc_config):
        u = HTMLUpdater(hc_config)
        prospect = self._make_prospect(website_data={
            'tech_stack_hints': ['hybrid cloud', 'data center', 'cloud-native'],
        })
        assert u._generate_vendor_badges(prospect) == ''


class TestReachOutLayout:
    """Reach-out box must span the full info-grid (no half-empty row)."""

    def test_reach_out_box_spans_full_width(self, hc_config):
        u = HTMLUpdater(hc_config)
        prospect = {
            'organization': 'TestOrg',
            'signal': 'Test signal',
            'source_url': 'https://example.com',
            'qualification_score': 80,
            'rackspace_wedge': 'HIPAA-compliant hosting',
            'ai_agent_use_case': 'Patient flow optimization',
            'category': 'Health System',
            'priority': 'High',
            'reach_out_reason': 'Needs compliant hosting',
        }
        card = u._generate_single_card(prospect)
        assert 'grid-column: 1 / -1' in card


class TestAnchorInsertion:
    """Cards must insert at the stable anchor; updater must fail loudly
    (return False) on malformed documents instead of silently succeeding."""

    def _prospect(self):
        return {
            'organization': 'Anchor Test Org',
            'signal': 'sig', 'source_url': 'https://example.com',
            'qualification_score': 70, 'rackspace_wedge': 'w',
            'ai_agent_use_case': 'a', 'category': 'Health System',
            'priority': 'Medium',
        }

    def _updater(self, hc_config, tmp_path, content):
        import copy
        path = tmp_path / 'page.html'
        path.write_text(content)
        cfg = copy.deepcopy(hc_config)
        cfg['output']['html_file'] = str(path)
        return HTMLUpdater(cfg), path

    def test_inserts_before_anchor(self, hc_config, tmp_path):
        from outputs.html_updater import INSERT_ANCHOR
        content = f'<html><body><div>{INSERT_ANCHOR}</div></body></html>'
        u, path = self._updater(hc_config, tmp_path, content)
        assert u.update([self._prospect()]) is True
        out = path.read_text()
        assert 'Anchor Test Org' in out
        assert INSERT_ANCHOR in out  # anchor survives for next insertion
        assert out.index('Anchor Test Org') < out.index(INSERT_ANCHOR)

    def test_repeated_insertions_accumulate(self, hc_config, tmp_path):
        from outputs.html_updater import INSERT_ANCHOR
        content = f'<html><body><div>{INSERT_ANCHOR}</div></body></html>'
        u, path = self._updater(hc_config, tmp_path, content)
        p1 = self._prospect()
        p2 = dict(self._prospect(), organization='Second Org')
        assert u.update([p1]) is True
        assert u.update([p2]) is True
        out = path.read_text()
        assert 'Anchor Test Org' in out and 'Second Org' in out
        assert out.count(INSERT_ANCHOR) == 1

    def test_falls_back_to_body_without_anchor(self, hc_config, tmp_path):
        u, path = self._updater(hc_config, tmp_path, '<html><body><p>x</p></body></html>')
        assert u.update([self._prospect()]) is True
        assert 'Anchor Test Org' in path.read_text()

    def test_truncated_document_fails_loudly(self, hc_config, tmp_path):
        """The regression that bit us: no anchor, no </body> — update() must
        return False and leave the file untouched."""
        content = '<html><body><div class="prospect-card">old</div>'
        u, path = self._updater(hc_config, tmp_path, content)
        assert u.update([self._prospect()]) is False
        assert path.read_text() == content
