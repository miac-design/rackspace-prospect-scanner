"""
LinkedIn Profile Validator Module
==================================
Validates LinkedIn profile URLs in the prospect list.
LinkedIn requires special handling due to auth walls and redirects.
Uses web search as fallback to find correct profile URLs.
"""

import requests
import logging
import re
from pathlib import Path
from typing import List, Dict, Tuple
from bs4 import BeautifulSoup

logger = logging.getLogger('LinkedInValidator')


class LinkedInValidator:
    """Validates and fixes LinkedIn profile URLs in HTML files."""
    
    def __init__(self, html_path: str, timeout: int = 10):
        """
        Initialize the LinkedIn validator.
        
        Args:
            html_path: Path to the HTML file containing LinkedIn links
            timeout: Request timeout in seconds
        """
        self.html_path = Path(html_path)
        self.timeout = timeout
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }
    
    def extract_linkedin_links(self) -> List[Dict]:
        """
        Extract all LinkedIn links from the HTML file.
        
        Returns:
            List of dicts with url, display_text, and context
        """
        with open(self.html_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        soup = BeautifulSoup(content, 'html.parser')
        linkedin_links = []
        
        # Find all links to linkedin.com
        for link in soup.find_all('a', href=re.compile(r'linkedin\.com/in/')):
            url = link.get('href', '')
            text = link.get_text(strip=True)
            
            # Get company context from parent card
            card = link.find_parent(class_='prospect-card')
            company = ''
            if card:
                company_el = card.find(class_='company-name')
                if company_el:
                    company = company_el.get_text(strip=True)
            
            linkedin_links.append({
                'url': url,
                'display_text': text,
                'company': company,
                'username': self._extract_username(url)
            })
        
        logger.info(f"Found {len(linkedin_links)} LinkedIn links")
        return linkedin_links
    
    def _extract_username(self, url: str) -> str:
        """Extract username from LinkedIn URL."""
        match = re.search(r'linkedin\.com/in/([^/\?]+)', url)
        return match.group(1) if match else ''
    
    def check_linkedin_url(self, url: str) -> Dict:
        """
        Check if a LinkedIn profile URL is valid.
        
        LinkedIn returns 200 even for missing profiles (shows auth wall).
        We need to check if we're redirected to auth wall or profile exists.
        
        Args:
            url: LinkedIn profile URL
            
        Returns:
            Dict with validation status
        """
        try:
            response = requests.get(
                url,
                headers=self.headers,
                timeout=self.timeout,
                allow_redirects=True
            )
            
            # Check for auth wall redirect (common for non-existent profiles)
            is_auth_wall = 'authwall' in response.url or 'login' in response.url
            
            # Check for 404 page content
            is_404 = 'Page not found' in response.text or response.status_code == 404
            
            # Check if profile exists (has profile-specific elements)
            has_profile_data = 'og:title' in response.text and 'LinkedIn' in response.text
            
            # A profile is valid if:
            # - Not redirected to auth wall (or if auth wall but URL preserved)
            # - Not a 404
            # - Status code is good
            is_valid = response.status_code == 200 and not is_404
            
            return {
                'url': url,
                'status_code': response.status_code,
                'final_url': response.url,
                'is_valid': is_valid,
                'is_auth_wall': is_auth_wall,
                'needs_verification': is_auth_wall  # Manual check recommended
            }
            
        except requests.RequestException as e:
            logger.warning(f"Failed to check {url}: {e}")
            return {
                'url': url,
                'status_code': 0,
                'is_valid': False,
                'error': str(e)
            }
    
    def validate_all(self) -> Dict:
        """
        Validate all LinkedIn links in the HTML file.
        
        Returns:
            Dict with validation results
        """
        links = self.extract_linkedin_links()
        results = {
            'total': len(links),
            'valid': [],
            'needs_verification': [],
            'broken': [],
            'profiles': links  # Store all profile data
        }
        
        for link_data in links:
            url = link_data['url']
            result = self.check_linkedin_url(url)
            result.update(link_data)
            
            if result.get('error') or result['status_code'] >= 400:
                results['broken'].append(result)
                logger.warning(f"✗ BROKEN: {link_data['display_text']} at {link_data['company']}")
            elif result.get('needs_verification'):
                results['needs_verification'].append(result)
                logger.info(f"⚠ VERIFY: {link_data['display_text']} at {link_data['company']}")
            else:
                results['valid'].append(result)
                logger.info(f"✓ VALID: {link_data['display_text']}")
        
        return results
    
    def update_linkedin_url(self, old_url: str, new_url: str, new_text: str = None) -> bool:
        """
        Update a LinkedIn URL in the HTML file.
        
        Args:
            old_url: Current URL to replace
            new_url: New LinkedIn URL
            new_text: Optional new display text
            
        Returns:
            True if updated successfully
        """
        with open(self.html_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Simple URL replacement
        if old_url in content:
            content = content.replace(old_url, new_url)
            
            with open(self.html_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            logger.info(f"Updated: {old_url} → {new_url}")
            return True
        
        return False
    
    def generate_report(self, results: Dict) -> str:
        """Generate a human-readable validation report."""
        report = []
        report.append("=" * 60)
        report.append("LINKEDIN PROFILE VALIDATION REPORT")
        report.append("=" * 60)
        report.append(f"Total profiles: {results['total']}")
        report.append(f"Valid: {len(results['valid'])}")
        report.append(f"Needs verification: {len(results['needs_verification'])}")
        report.append(f"Broken: {len(results['broken'])}")
        report.append("")
        
        if results['needs_verification']:
            report.append("⚠ PROFILES NEEDING VERIFICATION:")
            for p in results['needs_verification']:
                report.append(f"  Company: {p['company']}")
                report.append(f"  Contact: {p['display_text']}")
                report.append(f"  URL: {p['url']}")
                report.append("")
        
        if results['broken']:
            report.append("✗ BROKEN PROFILES:")
            for p in results['broken']:
                report.append(f"  Company: {p['company']}")
                report.append(f"  Contact: {p['display_text']}")
                report.append(f"  URL: {p['url']}")
                report.append(f"  Error: {p.get('error', 'Unknown')}")
                report.append("")
        
        return "\n".join(report)


def main():
    """Test the LinkedIn validator."""
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    if len(sys.argv) < 2:
        print("Usage: python linkedin_validator.py <html_file>")
        sys.exit(1)
    
    validator = LinkedInValidator(sys.argv[1])
    results = validator.validate_all()
    print(validator.generate_report(results))


if __name__ == '__main__':
    main()
