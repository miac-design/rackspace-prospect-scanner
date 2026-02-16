"""
Website Scanner Module
======================
Enriches prospect data by scanning company websites for additional signals.
Uses stdlib only (urllib) to match run_scan.py philosophy — no external deps.

Madhavi feedback #2: "Website data integration alongside LinkedIn"
"""

import re
import logging
import urllib.request
import urllib.error
from typing import Dict, Optional, List
from urllib.parse import urlparse, urljoin

logger = logging.getLogger('WebsiteScanner')

# Common pages that contain useful company intelligence
PAGES_TO_CHECK = [
    '/',                    # Homepage
    '/about',               # About page
    '/about-us',
    '/technology',          # Tech stack info
    '/press',               # Recent press releases
    '/press-releases',
    '/newsroom',
    '/careers',             # Hiring signals
    '/investors',           # Financial signals
]

# Tech stack keywords that indicate infrastructure needs
TECH_SIGNALS = {
    'cloud_mentions': [
        'aws', 'amazon web services', 'azure', 'google cloud', 'gcp',
        'hybrid cloud', 'multi-cloud', 'private cloud', 'data center',
        'cloud-native', 'kubernetes', 'docker', 'openstack',
    ],
    'ai_mentions': [
        'artificial intelligence', 'machine learning', 'deep learning',
        'generative ai', 'llm', 'large language model', 'mlops',
        'data science', 'predictive analytics', 'neural network',
    ],
    'legacy_signals': [
        'mainframe', 'legacy systems', 'on-premise', 'on-premises',
        'cobol', 'as/400', 'legacy infrastructure', 'technical debt',
    ],
    'hiring_signals': [
        'hiring', 'open positions', 'join our team', 'careers',
        'cloud engineer', 'devops', 'site reliability', 'infrastructure',
        'we\'re growing', 'now hiring',
    ],
}


class WebsiteScanner:
    """Scans company websites to enrich prospect data with additional signals."""
    
    def __init__(self, timeout: int = 10):
        """Initialize with request timeout."""
        self.timeout = timeout
        self._headers = {
            'User-Agent': 'Mozilla/5.0 (Rackspace Prospect Scanner; +https://rackspace.com)',
            'Accept': 'text/html,application/xhtml+xml',
        }
    
    def enrich_prospect(self, prospect: Dict) -> Dict:
        """
        Enrich a prospect dictionary with website data.
        
        Tries to find the company website from the organization name,
        then scans key pages for infrastructure and technology signals.
        
        Args:
            prospect: Qualified prospect dictionary
            
        Returns:
            Updated prospect dict with 'website_data' field added
        """
        org_name = prospect.get('organization', '')
        source_url = prospect.get('source_url', '')
        
        # Try to find the company's website from the source article domain
        company_domain = self._guess_company_domain(org_name, source_url)
        
        if not company_domain:
            prospect['website_data'] = {
                'status': 'no_domain_found',
                'signals': [],
                'enrichment_note': 'Could not determine company website from available data',
            }
            return prospect
        
        # Scan the company website
        website_data = self._scan_website(company_domain)
        prospect['website_data'] = website_data
        
        return prospect
    
    def _guess_company_domain(self, org_name: str, source_url: str) -> Optional[str]:
        """
        Try to determine the company's website URL.
        Uses heuristics based on organization name.
        """
        if not org_name:
            return None
        
        # Clean org name for domain guessing
        clean_name = org_name.lower().strip()
        clean_name = re.sub(r'\s+(health|healthcare|hospital|medical|system|group|corp|inc|llc|ltd)s?\.?$', '', clean_name)
        clean_name = re.sub(r'[^a-z0-9]', '', clean_name)
        
        if not clean_name or len(clean_name) < 3:
            return None
        
        # Try common domain patterns
        candidates = [
            f'https://www.{clean_name}.com',
            f'https://www.{clean_name}.org',
            f'https://{clean_name}.com',
        ]
        
        for url in candidates:
            if self._url_reachable(url):
                return url
        
        return None
    
    def _url_reachable(self, url: str) -> bool:
        """Quick check if a URL is reachable (HEAD request)."""
        try:
            req = urllib.request.Request(url, method='HEAD', headers=self._headers)
            response = urllib.request.urlopen(req, timeout=5)
            return response.status < 400
        except Exception:
            return False
    
    def _scan_website(self, base_url: str) -> Dict:
        """
        Scan key pages of a company website for intelligence signals.
        
        Returns:
            Dictionary with website scan results
        """
        signals = []
        pages_scanned = 0
        tech_stack_hints = []
        hiring_detected = False
        
        for page_path in PAGES_TO_CHECK:
            full_url = urljoin(base_url, page_path)
            content = self._fetch_page(full_url)
            
            if not content:
                continue
            
            pages_scanned += 1
            content_lower = content.lower()
            
            # Check each signal category
            for category, keywords in TECH_SIGNALS.items():
                matched_keywords = [kw for kw in keywords if kw in content_lower]
                if matched_keywords:
                    signal = {
                        'category': category,
                        'page': page_path,
                        'matched': matched_keywords[:5],  # Cap at 5 matches per category
                    }
                    signals.append(signal)
                    
                    if category == 'cloud_mentions':
                        tech_stack_hints.extend(matched_keywords[:3])
                    elif category == 'hiring_signals':
                        hiring_detected = True
            
            # Stop after 3 successful pages to avoid throttling
            if pages_scanned >= 3:
                break
        
        # Build enrichment summary
        enrichment_note = self._summarize_signals(signals, hiring_detected)
        
        return {
            'status': 'scanned' if pages_scanned > 0 else 'unreachable',
            'domain': base_url,
            'pages_scanned': pages_scanned,
            'signals': signals,
            'tech_stack_hints': list(set(tech_stack_hints)),
            'hiring_detected': hiring_detected,
            'enrichment_note': enrichment_note,
        }
    
    def _fetch_page(self, url: str) -> Optional[str]:
        """Fetch a web page and return its text content (HTML tags stripped)."""
        try:
            req = urllib.request.Request(url, headers=self._headers)
            response = urllib.request.urlopen(req, timeout=self.timeout)
            
            if response.status != 200:
                return None
            
            html = response.read().decode('utf-8', errors='ignore')
            
            # Strip HTML tags for text analysis
            text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text)
            
            return text[:50000]  # Cap at 50K chars to avoid memory issues
            
        except Exception as e:
            logger.debug(f"Could not fetch {url}: {e}")
            return None
    
    def _summarize_signals(self, signals: List[Dict], hiring: bool) -> str:
        """Generate a one-line summary of website findings."""
        parts = []
        
        categories_found = set(s['category'] for s in signals)
        
        if 'cloud_mentions' in categories_found:
            parts.append('Cloud infrastructure references found')
        if 'ai_mentions' in categories_found:
            parts.append('AI/ML initiatives mentioned')
        if 'legacy_signals' in categories_found:
            parts.append('Legacy system indicators detected')
        if hiring:
            parts.append('Active tech hiring')
        
        if parts:
            return '; '.join(parts)
        return 'No significant technology signals detected on website'
