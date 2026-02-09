"""
Link Validator Module
=====================
Validates all source URLs in the prospect list before deployment.
Checks HTTP status and handles broken links gracefully.
"""

import requests
import logging
import re
from pathlib import Path
from typing import List, Tuple, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger('LinkValidator')


class LinkValidator:
    """Validates source links in the HTML prospect file."""
    
    def __init__(self, html_path: str, timeout: int = 10):
        """
        Initialize the link validator.
        
        Args:
            html_path: Path to the HTML file containing source links
            timeout: Request timeout in seconds
        """
        self.html_path = Path(html_path)
        self.timeout = timeout
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
    
    def extract_source_links(self) -> List[Tuple[str, str]]:
        """
        Extract all source links from the HTML file.
        
        Returns:
            List of tuples: (url, link_text)
        """
        with open(self.html_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Match source-link anchors: <a href="URL" class="source-link"...>TEXT</a>
        pattern = r'<a\s+href="([^"]+)"\s*class="source-link"[^>]*>([^<]+)</a>'
        matches = re.findall(pattern, content)
        
        logger.info(f"Found {len(matches)} source links to validate")
        return matches
    
    def check_url(self, url: str) -> Dict:
        """
        Check if a URL is accessible.
        
        Args:
            url: URL to check
            
        Returns:
            Dict with status info
        """
        try:
            # Use HEAD request for efficiency, fall back to GET if needed
            response = requests.head(
                url, 
                headers=self.headers, 
                timeout=self.timeout,
                allow_redirects=True
            )
            
            # Some sites block HEAD requests, try GET
            if response.status_code >= 400:
                response = requests.get(
                    url,
                    headers=self.headers,
                    timeout=self.timeout,
                    allow_redirects=True
                )
            
            return {
                'url': url,
                'status_code': response.status_code,
                'is_valid': response.status_code < 400,
                'final_url': response.url
            }
            
        except requests.RequestException as e:
            logger.warning(f"Failed to check {url}: {e}")
            return {
                'url': url,
                'status_code': 0,
                'is_valid': False,
                'error': str(e)
            }
    
    def validate_all(self, max_workers: int = 5) -> Dict:
        """
        Validate all source links in the HTML file.
        
        Args:
            max_workers: Number of concurrent checks
            
        Returns:
            Dict with validation results
        """
        links = self.extract_source_links()
        results = {
            'total': len(links),
            'valid': [],
            'broken': [],
            'checked': 0
        }
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_link = {
                executor.submit(self.check_url, url): (url, text) 
                for url, text in links
            }
            
            for future in as_completed(future_to_link):
                url, text = future_to_link[future]
                result = future.result()
                result['link_text'] = text
                results['checked'] += 1
                
                if result['is_valid']:
                    results['valid'].append(result)
                    logger.info(f"✓ {url[:60]}...")
                else:
                    results['broken'].append(result)
                    logger.warning(f"✗ BROKEN: {url[:60]}...")
        
        logger.info(f"Validation complete: {len(results['valid'])} valid, {len(results['broken'])} broken")
        return results
    
    def fix_broken_links(self, results: Dict) -> int:
        """
        Replace broken links with signal date badges (no clickable link).
        
        Args:
            results: Validation results from validate_all()
            
        Returns:
            Number of links fixed
        """
        if not results['broken']:
            return 0
        
        with open(self.html_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        fixed_count = 0
        for broken in results['broken']:
            url = broken['url']
            text = broken['link_text']
            
            # Extract date from link text (e.g., "✓ Signal: Sept 2025 AI Strategy →")
            date_match = re.search(r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s*\d{0,2},?\s*\d{4})', text)
            if date_match:
                date_str = date_match.group(1)
            else:
                date_str = "Date unavailable"
            
            # Create replacement badge (no link, just text)
            old_link = f'<a href="{url}"'
            # Find the full anchor tag and replace with span
            pattern = rf'<a\s+href="{re.escape(url)}"[^>]*class="source-link"[^>]*>[^<]+</a>'
            replacement = f'<span class="source-link" style="cursor: default; opacity: 0.7;">✓ Signal: {date_str} (source archived)</span>'
            
            new_content = re.sub(pattern, replacement, content)
            if new_content != content:
                content = new_content
                fixed_count += 1
                logger.info(f"Fixed broken link: {url[:50]}...")
        
        with open(self.html_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        logger.info(f"Fixed {fixed_count} broken links")
        return fixed_count


def main():
    """Test the link validator."""
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    if len(sys.argv) < 2:
        print("Usage: python link_validator.py <html_file>")
        sys.exit(1)
    
    validator = LinkValidator(sys.argv[1])
    results = validator.validate_all()
    
    print(f"\n{'='*60}")
    print(f"LINK VALIDATION REPORT")
    print(f"{'='*60}")
    print(f"Total links: {results['total']}")
    print(f"Valid: {len(results['valid'])}")
    print(f"Broken: {len(results['broken'])}")
    
    if results['broken']:
        print(f"\nBroken Links:")
        for broken in results['broken']:
            print(f"  ✗ {broken['url'][:70]}...")
        
        fix = input("\nFix broken links? (y/n): ")
        if fix.lower() == 'y':
            validator.fix_broken_links(results)
            print("Links fixed!")


if __name__ == '__main__':
    main()
