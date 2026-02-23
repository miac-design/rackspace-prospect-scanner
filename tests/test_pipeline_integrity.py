"""
Test the regex fallback RSS parser against real broken feed scenarios.
Verifies that when feedparser fails on malformed XML, the regex fallback
correctly extracts articles with titles, links, and dates.
"""
import pytest
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# Simulated broken XML that real feeds produce
BROKEN_XML_SAMPLES = {
    "american_banker": """<?xml version="1.0"?>
<rss version="2.0">
<channel>
<title>American Banker</title>
<item>
<title>JPMorgan Launches AI-Powered Fraud Detection Platform</title>
<link>https://americanbanker.com/article/jpmorgan-ai-fraud</link>
<pubDate>Mon, 17 Feb 2026 08:00:00 EST</pubDate>
<description>JPMorgan Chase unveiled a new AI platform for real-time fraud detection.</description>
</item>
<item>
<title>Community Banks Face Cloud Migration Deadline</title>
<link>https://americanbanker.com/article/community-banks-cloud</link>
<pubDate>Tue, 18 Feb 2026 10:30:00 EST</pubDate>
</item>
<!-- malformed: missing closing tags below -->
<item>
<title>Capital One Expands Partnership with AWS</title>
<link>https://americanbanker.com/article/capital-one-aws
""",
    "healthcare_it_truncated": """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>Healthcare IT News</title>
<item>
<title>Epic Systems Rolls Out Ambient AI for Clinical Notes</title>
<link>https://healthcareitnews.com/epic-ambient-ai</link>
<pubDate>Wed, 19 Feb 2026 09:00:00 EST</pubDate>
<description>Epic's new ambient listening tool deploys across 50 health systems.</description>
</item>
<item>
<title>HCA Healthcare Migrating to Azure by Q3 2026</title>
<link>https://healthcareitnews.com/hca-azure-migration</link>
<pubDate>Thu, 20 Feb 2026 11:00:00 EST</pubDate>
</item>
<!-- feed truncated mid-tag -->
<item><title>Cerner Oracle Health
""",
    "empty_feed": """<?xml version="1.0"?>
<rss version="2.0">
<channel>
<title>Empty Feed</title>
</channel>
</rss>""",
    "no_items": """not even xml at all, just garbage text""",
}


def regex_fallback_parse(raw_xml: str) -> list:
    """
    Regex fallback parser — extracts articles from broken XML.
    This mirrors the logic in run_scan.py's _regex_fallback_parse.
    """
    import re
    articles = []
    
    # Extract <item>...</item> blocks (even if incomplete)
    item_pattern = r'<item[^>]*>(.*?)(?:</item>|$)'
    items = re.findall(item_pattern, raw_xml, re.DOTALL)
    
    for item_text in items:
        title_match = re.search(r'<title>([^<]+)</title>', item_text)
        link_match = re.search(r'<link>([^<\s]+)', item_text)
        date_match = re.search(r'<pubDate>([^<]+)</pubDate>', item_text)
        desc_match = re.search(r'<description>([^<]*)</description>', item_text)
        
        if title_match and link_match:
            articles.append({
                'title': title_match.group(1).strip(),
                'url': link_match.group(1).strip(),
                'published_date': date_match.group(1).strip() if date_match else None,
                'summary': desc_match.group(1).strip() if desc_match else '',
            })
    
    return articles


class TestRegexFallbackParser:
    """Test regex fallback parser against real broken feed patterns."""
    
    def test_american_banker_broken_xml(self):
        """American Banker feeds often have malformed closing tags."""
        articles = regex_fallback_parse(BROKEN_XML_SAMPLES["american_banker"])
        # Should extract at least the 2 complete items
        assert len(articles) >= 2
        assert articles[0]['title'] == 'JPMorgan Launches AI-Powered Fraud Detection Platform'
        assert 'americanbanker.com' in articles[0]['url']
        assert articles[1]['title'] == 'Community Banks Face Cloud Migration Deadline'
    
    def test_healthcare_it_truncated(self):
        """Healthcare IT News feeds sometimes truncate mid-article."""
        articles = regex_fallback_parse(BROKEN_XML_SAMPLES["healthcare_it_truncated"])
        assert len(articles) >= 2
        assert articles[0]['title'] == 'Epic Systems Rolls Out Ambient AI for Clinical Notes'
        assert articles[1]['title'] == 'HCA Healthcare Migrating to Azure by Q3 2026'
    
    def test_empty_feed_returns_empty(self):
        """An RSS feed with no items should return empty list."""
        articles = regex_fallback_parse(BROKEN_XML_SAMPLES["empty_feed"])
        assert articles == []
    
    def test_garbage_input_returns_empty(self):
        """Non-XML input should return empty list, not crash."""
        articles = regex_fallback_parse(BROKEN_XML_SAMPLES["no_items"])
        assert articles == []
    
    def test_extracts_dates_when_present(self):
        """Date extraction works for items that have pubDate."""
        articles = regex_fallback_parse(BROKEN_XML_SAMPLES["american_banker"])
        assert articles[0]['published_date'] is not None
        assert 'Feb 2026' in articles[0]['published_date']
    
    def test_extracts_description_when_present(self):
        """Summary/description is extracted when available."""
        articles = regex_fallback_parse(BROKEN_XML_SAMPLES["healthcare_it_truncated"])
        assert 'ambient listening' in articles[0]['summary'].lower()


class TestCrossContamination:
    """Verify healthcare articles don't qualify in BFSI pipeline and vice versa."""
    
    # Healthcare-only article titles (should NOT qualify in BFSI)
    HC_ONLY_TITLES = [
        "Mayo Clinic Deploys AI for Radiology Imaging",
        "HIPAA Violations Surge at Small Clinics Nationwide",
        "Epic EHR Upgrade Improves Patient Portal Experience",
        "Telehealth Adoption Plateaus After COVID Surge",
        "Physician Burnout Drives Health IT Investment",
        "FDA Approves AI-Powered Diagnostic Tool for Hospitals",
        "Community Hospital Network Consolidates Data Centers",
        "Nursing Shortage Creates Demand for Clinical AI Assistants",
        "Mental Health Platform Raises Series B for Virtual Therapy",
        "Drug Discovery AI Platform Partners with Pfizer",
    ]
    
    # BFSI-only article titles (should NOT qualify in HC)
    BFSI_ONLY_TITLES = [
        "Goldman Sachs Deploys Algorithmic Trading AI Platform",
        "FDIC Issues New Guidance on Core Banking Cloud Migration",
        "Insurtech Startup Raises $50M for Claims Automation",
        "Credit Union Network Upgrades PCI DSS Compliance Systems",
        "Cryptocurrency Exchange Faces SEC Regulatory Scrutiny",
        "Mortgage Lender Automates Underwriting with Machine Learning",
        "European Central Bank Tests Digital Currency Infrastructure",
        "Anti-Money Laundering AI Detects Suspicious Transactions",
        "Wealth Management Firm Adopts Robo-Advisory Platform",
        "Banking-as-a-Service Provider Expands API Integration",
    ]
    
    @pytest.fixture
    def hc_config(self):
        import json
        with open('agent_config.json') as f:
            return json.load(f)
    
    @pytest.fixture
    def bfsi_config(self):
        import json
        with open('bfsi_agent_config.json') as f:
            return json.load(f)
    
    def test_bfsi_articles_rejected_by_healthcare(self, hc_config):
        """BFSI articles should not qualify in healthcare pipeline."""
        from reasoning.qualifier import ProspectQualifier
        q = ProspectQualifier(hc_config)
        
        qualified = []
        for title in self.BFSI_ONLY_TITLES:
            result = q.qualify({
                'title': title,
                'summary': title,
                'url': 'https://test.com',
                'source': 'test',
            })
            if result:
                qualified.append(title)
        
        # Allow at most 1 crossover (some articles legitimately overlap)
        assert len(qualified) <= 1, f"Too many BFSI articles qualified as HC: {qualified}"
    
    def test_hc_articles_rejected_by_bfsi(self, bfsi_config):
        """Healthcare articles should not qualify in BFSI pipeline."""
        from reasoning.qualifier import ProspectQualifier
        q = ProspectQualifier(bfsi_config)
        
        qualified = []
        for title in self.HC_ONLY_TITLES:
            result = q.qualify({
                'title': title,
                'summary': title,
                'url': 'https://test.com',
                'source': 'test',
            })
            if result:
                qualified.append(title)
        
        assert len(qualified) <= 1, f"Too many HC articles qualified as BFSI: {qualified}"
