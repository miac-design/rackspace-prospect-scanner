"""
Structural integrity tests for the deployed HTML documents.

These exist because the dist HTML files were once truncated (no </body>,
no <script>) for ~3 months without anything noticing: every JS handler was
dead and card insertion silently failed while the banner claimed prospects
were added. These tests fail CI the moment the documents regress.
"""
import re
import os
import pytest

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), '..')
DIST_FILES = [
    os.path.join(PROJECT_ROOT, 'dist_prospects', 'healthcare.html'),
    os.path.join(PROJECT_ROOT, 'dist_prospects', 'bfsi.html'),
    os.path.join(PROJECT_ROOT, 'dist_prospects', 'index.html'),
]

ANCHOR = '<!-- MIRA:INSERT-NEW-PROSPECTS -->'


@pytest.fixture(params=DIST_FILES, ids=lambda p: os.path.basename(p))
def html(request):
    with open(request.param, encoding='utf-8') as f:
        return f.read()


class TestDocumentStructure:
    def test_document_is_complete(self, html):
        assert '</body>' in html, "document truncated: missing </body>"
        assert '</html>' in html, "document truncated: missing </html>"

    def test_divs_balanced(self, html):
        opens = len(re.findall(r'<div\b', html))
        closes = len(re.findall(r'</div\s*>', html))
        assert opens == closes, f"unbalanced divs: {opens} open / {closes} close"

    def test_insertion_anchor_present(self, html):
        assert ANCHOR in html, "card insertion anchor missing"

    def test_anchor_is_before_footer(self, html):
        """The anchor must sit inside the visible list, not after the footer."""
        assert html.index(ANCHOR) < html.index('<footer')


class TestJavaScriptHandlers:
    def test_script_block_exists(self, html):
        assert '<script' in html, "page has no <script> — all buttons dead"

    def test_every_onclick_handler_is_defined(self, html):
        """Every function referenced by on* attributes must be defined,
        except browser built-ins (e.g. window.print)."""
        referenced = set(re.findall(r'on\w+="(\w+)\(', html))
        referenced.discard('window')  # window.print()
        defined = set(re.findall(r'function\s+(\w+)\s*\(', html))
        missing = referenced - defined
        assert not missing, f"handlers referenced but never defined: {missing}"

    def test_search_input_is_wired(self, html):
        if 'id="searchInput"' in html:
            assert "getElementById('searchInput')" in html, \
                "search box exists but no JS wires it"


class TestFilterWiring:
    """The filter buttons regressed once (section-based logic that did
    nothing on BFSI). Lock the unified per-card engine in place."""

    def test_unified_filter_engine_present(self, html):
        assert 'MiraFilter' in html, "unified filter engine missing"
        assert 'MiraFilter.apply' in html

    def test_no_stale_section_based_filter(self, html):
        # The old broken implementation toggled section display and defined
        # filterByUseCase; neither should remain.
        assert 'function filterByUseCase' not in html
        assert "s.style.display = s.classList.contains('tier-partners')" not in html

    def test_filter_buttons_have_data_filter(self, html):
        buttons = re.findall(r'<button class="filter-btn[^"]*"[^>]*data-filter="([^"]+)"', html)
        assert len(buttons) >= 2, "expected filter buttons with data-filter"
        assert 'all' in buttons
