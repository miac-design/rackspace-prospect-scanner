"""
Shared fixtures for all test modules.
"""
import json
import os
import sys
import pytest
import tempfile
import shutil

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), '..')


@pytest.fixture
def hc_config():
    """Load healthcare config."""
    with open(os.path.join(PROJECT_ROOT, 'agent_config.json'), 'r') as f:
        return json.load(f)


@pytest.fixture
def bfsi_config():
    """Load BFSI config."""
    with open(os.path.join(PROJECT_ROOT, 'bfsi_agent_config.json'), 'r') as f:
        return json.load(f)


@pytest.fixture
def strong_hc_article():
    """A healthcare article that should qualify."""
    return {
        'title': 'WellSpan Health Announces Cloud Migration and AI Infrastructure Initiative',
        'summary': (
            'WellSpan Health, a major hospital health system, announced plans to '
            'migrate its clinical infrastructure to cloud by Q3 deadline. The health '
            'system is seeking managed services partners for HIPAA-compliant operations, '
            'artificial intelligence analytics, machine learning platform, and ongoing '
            'cloud management support.'
        ),
        'content': '',
        'url': 'https://example.com/wellspan',
        'source': 'Healthcare IT News',
        'published_date': '2026-02-01',
    }


@pytest.fixture
def strong_bfsi_article():
    """A BFSI article that should qualify."""
    return {
        'title': 'First National Bank Cloud Migration for Core Banking Infrastructure',
        'summary': (
            'First National Bank financial institution migrating core banking to cloud '
            'with managed services by Q2 deadline. PCI-compliant hosting, artificial '
            'intelligence fraud detection, machine learning for payment processing compliance.'
        ),
        'content': '',
        'url': 'https://example.com/fnb',
        'source': 'American Banker',
        'published_date': '2026-02-01',
    }


@pytest.fixture
def offtopic_article():
    """An article that should never qualify."""
    return {
        'title': 'Apple Releases New iPhone Model',
        'summary': 'Apple sold more phones with improved camera and battery.',
        'content': '',
        'url': 'https://example.com/apple',
        'source': 'TechCrunch',
    }


@pytest.fixture
def tmp_html(hc_config, tmp_path):
    """Create a temporary HTML file with Pipeline Status banner for testing."""
    html_content = """<!DOCTYPE html>
<html>
<head><title>Test Prospects</title></head>
<body>
    <div class="pipeline-status">
        <p id="scan-timestamp">🕐 <strong>Last scanned:</strong> Never</p>
        <p id="scan-result">No scans run yet</p>
    </div>
    <section class="section tier-2">
        <div class="section-content">
            <div class="prospect-card">
                <div class="company-name">Existing Corp</div>
            </div>
        </div>
    </section>
    <footer></footer>
</body>
</html>"""
    html_file = tmp_path / 'test_prospects.html'
    html_file.write_text(html_content)
    
    # Override config to use temp file
    config = hc_config.copy()
    config['output'] = hc_config['output'].copy()
    config['output']['html_file'] = str(html_file)
    return config, str(html_file)
