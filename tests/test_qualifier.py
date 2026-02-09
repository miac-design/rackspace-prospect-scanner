"""
Tests for reasoning/qualifier.py — ProspectQualifier
=====================================================
Covers: domain scoping, scoring, org extraction, wedge generation,
        AI use case mapping, determinism, category formatting.
"""
import pytest
from reasoning.qualifier import ProspectQualifier


# ── Domain Relevance ──────────────────────────────────────────

class TestDomainRelevance:
    """Tests for _is_domain_relevant scoping."""

    def test_hc_article_passes_hc_qualifier(self, hc_config, strong_hc_article):
        q = ProspectQualifier(hc_config)
        text = f"{strong_hc_article['title']} {strong_hc_article['summary']}".lower()
        assert q._is_domain_relevant(text) is True

    def test_bfsi_article_rejected_by_hc_qualifier(self, hc_config, strong_bfsi_article):
        q = ProspectQualifier(hc_config)
        text = f"{strong_bfsi_article['title']} {strong_bfsi_article['summary']}".lower()
        assert q._is_domain_relevant(text) is False

    def test_bfsi_article_passes_bfsi_qualifier(self, bfsi_config, strong_bfsi_article):
        q = ProspectQualifier(bfsi_config)
        text = f"{strong_bfsi_article['title']} {strong_bfsi_article['summary']}".lower()
        assert q._is_domain_relevant(text) is True

    def test_hc_article_rejected_by_bfsi_qualifier(self, bfsi_config):
        q = ProspectQualifier(bfsi_config)
        text = 'mayo clinic hospital expanding telehealth patient care for physicians'
        assert q._is_domain_relevant(text) is False

    def test_offtopic_rejected(self, hc_config, offtopic_article):
        q = ProspectQualifier(hc_config)
        text = f"{offtopic_article['title']} {offtopic_article['summary']}".lower()
        assert q._is_domain_relevant(text) is False


# ── Scoring ───────────────────────────────────────────────────

class TestScoring:
    """Tests for _calculate_scores."""

    def test_strong_article_scores_above_threshold(self, hc_config, strong_hc_article):
        q = ProspectQualifier(hc_config)
        text = f"{strong_hc_article['title']} {strong_hc_article['summary']}".lower()
        scores = q._calculate_scores(text)
        total = sum(scores.values())
        assert total >= 50, f"Strong article scored only {total}"

    def test_empty_text_scores_zero(self, hc_config):
        q = ProspectQualifier(hc_config)
        scores = q._calculate_scores('')
        assert sum(scores.values()) == 0

    def test_score_capped_at_100(self, hc_config, strong_hc_article):
        q = ProspectQualifier(hc_config)
        result = q.qualify(strong_hc_article)
        if result:
            assert result['qualification_score'] <= 100

    def test_single_criterion_does_not_exceed_weight(self, hc_config):
        q = ProspectQualifier(hc_config)
        for name, cfg in hc_config['qualification_criteria'].items():
            # Stuff all keywords into text
            text = ' '.join(kw.lower() for kw in cfg['keywords'])
            scores = q._calculate_scores(text)
            assert scores.get(name, 0) <= cfg['weight'], \
                f"{name} scored {scores[name]} but max weight is {cfg['weight']}"


# ── Organization Extraction ───────────────────────────────────

class TestOrgExtraction:
    """Tests for _extract_organization and _extract_fallback_org."""

    def test_extracts_health_system(self, hc_config):
        q = ProspectQualifier(hc_config)
        org = q._extract_organization('WellSpan Health Announces Cloud Plan', '')
        assert org is not None
        assert 'WellSpan' in org

    def test_returns_none_for_no_org(self, hc_config):
        q = ProspectQualifier(hc_config)
        org = q._extract_organization('cloud migration trends rising', '')
        assert org is None

    def test_fallback_rejects_garbage(self, hc_config):
        q = ProspectQualifier(hc_config)
        assert q._extract_fallback_org('The System Is Changing') is None
        assert q._extract_fallback_org('How AI Works') is None
        assert q._extract_fallback_org('st India Proposes') is None

    def test_fallback_accepts_proper_nouns(self, hc_config):
        q = ProspectQualifier(hc_config)
        result = q._extract_fallback_org('Accenture Federal Services Wins Contract')
        assert result is not None
        assert '(Industry Signal)' in result


# ── Wedge Generation ─────────────────────────────────────────

class TestWedgeGeneration:
    """Tests for _generate_wedge including BFSI vs HC compliance text."""

    def test_hc_wedge_uses_hipaa(self, hc_config):
        q = ProspectQualifier(hc_config)
        scores = {'cloud_migration': 15, 'managed_services_gap': 0,
                  'ai_infrastructure': 0, 'compliance_sensitivity': 12,
                  'timing_urgency': 0}
        text = 'hospital health system patient hipaa clinical'
        wedge = q._generate_wedge(scores, text)
        assert 'HIPAA' in wedge

    def test_bfsi_wedge_uses_pci(self, bfsi_config):
        q = ProspectQualifier(bfsi_config)
        scores = {'cloud_migration': 15, 'managed_services_gap': 0,
                  'ai_infrastructure': 0, 'compliance_sensitivity': 12,
                  'timing_urgency': 0}
        text = 'bank financial payment insurance trading pci'
        wedge = q._generate_wedge(scores, text)
        assert 'PCI' in wedge or 'SOX' in wedge

    def test_wedge_limited_to_3(self, hc_config):
        q = ProspectQualifier(hc_config)
        scores = {'cloud_migration': 20, 'managed_services_gap': 20,
                  'ai_infrastructure': 20, 'compliance_sensitivity': 15,
                  'timing_urgency': 15}
        text = 'hospital patient health hipaa'
        wedge = q._generate_wedge(scores, text)
        assert wedge.count(',') <= 2  # At most 3 items = 2 commas


# ── AI Use Case Mapping ──────────────────────────────────────

class TestAIUseCaseMapping:
    """Tests for _suggest_ai_use_case with HC and BFSI triggers."""

    def test_hc_trigger_ehr(self, hc_config):
        q = ProspectQualifier(hc_config)
        assert 'EHR' in q._suggest_ai_use_case('ehr migration plan')

    def test_bfsi_trigger_fraud(self, bfsi_config):
        q = ProspectQualifier(bfsi_config)
        assert 'fraud' in q._suggest_ai_use_case('fraud detection system').lower()

    def test_bfsi_trigger_kyc(self, bfsi_config):
        q = ProspectQualifier(bfsi_config)
        assert 'KYC' in q._suggest_ai_use_case('kyc automation')

    def test_fallback_is_deterministic(self, hc_config):
        q = ProspectQualifier(hc_config)
        r1 = q._suggest_ai_use_case('nothing relevant here')
        r2 = q._suggest_ai_use_case('nothing relevant here')
        assert r1 == r2


# ── Determinism ───────────────────────────────────────────────

class TestDeterminism:
    """Same input → same output, no randomness."""

    def test_qualify_deterministic(self, hc_config, strong_hc_article):
        q = ProspectQualifier(hc_config)
        r1 = q.qualify(strong_hc_article)
        r2 = q.qualify(strong_hc_article)
        assert r1 is not None
        assert r1['qualification_score'] == r2['qualification_score']
        assert r1['rackspace_wedge'] == r2['rackspace_wedge']
        assert r1['ai_agent_use_case'] == r2['ai_agent_use_case']


# ── Category Formatting ──────────────────────────────────────

class TestCategoryFormatting:
    """Tests for _format_category config-aware fallback."""

    def test_hc_fallback(self, hc_config):
        q = ProspectQualifier(hc_config)
        assert q._format_category('unknown') == 'Healthcare'

    def test_bfsi_fallback(self, bfsi_config):
        q = ProspectQualifier(bfsi_config)
        assert q._format_category('unknown') == 'BFSI'

    def test_known_category(self, hc_config):
        q = ProspectQualifier(hc_config)
        assert q._format_category('health_system') == 'Health System'
        assert q._format_category('medtech') == 'MedTech'


# ── End-to-End Qualify ────────────────────────────────────────

class TestEndToEndQualify:
    """Full qualify() integration tests."""

    def test_strong_hc_qualifies(self, hc_config, strong_hc_article):
        q = ProspectQualifier(hc_config)
        result = q.qualify(strong_hc_article)
        assert result is not None
        assert result['qualification_score'] >= 65

    def test_strong_bfsi_qualifies(self, bfsi_config, strong_bfsi_article):
        q = ProspectQualifier(bfsi_config)
        result = q.qualify(strong_bfsi_article)
        assert result is not None
        assert result['qualification_score'] >= 65

    def test_offtopic_rejected(self, hc_config, offtopic_article):
        q = ProspectQualifier(hc_config)
        assert q.qualify(offtopic_article) is None

    def test_result_has_required_keys(self, hc_config, strong_hc_article):
        q = ProspectQualifier(hc_config)
        result = q.qualify(strong_hc_article)
        assert result is not None
        required = ['organization', 'signal', 'source_url', 'qualification_score',
                    'rackspace_wedge', 'ai_agent_use_case', 'category', 'priority']
        for key in required:
            assert key in result, f"Missing key: {key}"
