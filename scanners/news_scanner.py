"""
News Scanner Module
====================
Scans healthcare RSS feeds and extracts article metadata.
"""

import feedparser
import re
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from urllib.parse import urlparse

logger = logging.getLogger('NewsScanner')


class NewsScanner:
    """Scans RSS feeds for healthcare news articles."""
    
    def __init__(self, config: dict):
        """Initialize with configuration."""
        self.config = config
        self.feeds = config['data_sources']['rss_feeds']
        self.lookback_days = config['data_sources']['lookback_days']
        self.last_scan_count = 0
        
    def scan_all_feeds(self) -> List[Dict]:
        """
        Scan all configured RSS feeds in parallel for better performance.
        
        Returns:
            List of article dictionaries with metadata
        """
        import concurrent.futures
        
        all_articles = []
        enabled_feeds = [f for f in self.feeds if f.get('enabled', True)]
        
        # Parallel scanning with ThreadPoolExecutor
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_feed = {
                executor.submit(self._scan_feed, feed): feed 
                for feed in enabled_feeds
            }
            
            for future in concurrent.futures.as_completed(future_to_feed):
                feed = future_to_feed[future]
                try:
                    articles = future.result()
                    all_articles.extend(articles)
                    logger.info(f"   ✓ {feed['name']}: {len(articles)} articles")
                except Exception as e:
                    logger.error(f"   ✗ {feed['name']}: {e}")
        
        # Deduplicate by URL
        seen_urls = set()
        unique_articles = []
        for article in all_articles:
            if article['url'] not in seen_urls:
                seen_urls.add(article['url'])
                unique_articles.append(article)
        
        self.last_scan_count = len(unique_articles)
        logger.info(f"   Total unique articles: {len(unique_articles)}")
        
        return unique_articles
    
    def _scan_feed(self, feed_config: dict) -> List[Dict]:
        """Scan a single RSS feed."""
        articles = []
        cutoff_date = datetime.now() - timedelta(days=self.lookback_days)
        
        try:
            feed = feedparser.parse(feed_config['url'])
            
            for entry in feed.entries:
                # Parse publication date
                pub_date = self._parse_date(entry)
                
                # Skip if older than lookback period
                if pub_date and pub_date < cutoff_date:
                    continue
                
                # Extract article data
                article = {
                    'title': self._clean_html(entry.get('title', '')),
                    'summary': self._clean_html(entry.get('summary', '')),
                    'url': entry.get('link', ''),
                    'source': feed_config['name'],
                    'published_date': pub_date.isoformat() if pub_date else None,
                    'content': self._get_full_content(entry)
                }
                
                # Only include if it has meaningful content
                if article['title'] and len(article['summary']) > 50:
                    articles.append(article)
                    
        except Exception as e:
            logger.error(f"   Error scanning {feed_config['name']}: {e}")
        
        logger.info(f"     Found {len(articles)} recent articles")
        return articles
    
    def _parse_date(self, entry) -> Optional[datetime]:
        """Parse publication date from feed entry."""
        date_fields = ['published_parsed', 'updated_parsed', 'created_parsed']
        
        for field in date_fields:
            if hasattr(entry, field) and getattr(entry, field):
                try:
                    time_struct = getattr(entry, field)
                    return datetime(*time_struct[:6])
                except:
                    continue
        
        return None
    
    def _clean_html(self, text: str) -> str:
        """Remove HTML tags from text."""
        # Remove HTML tags
        clean = re.sub(r'<[^>]+>', ' ', text)
        # Normalize whitespace
        clean = re.sub(r'\s+', ' ', clean).strip()
        return clean
    
    def _get_full_content(self, entry) -> str:
        """Extract full content from entry if available."""
        content = ''
        
        # Try content field
        if hasattr(entry, 'content') and entry.content:
            content = entry.content[0].get('value', '')
        
        # Fallback to summary
        if not content:
            content = entry.get('summary', '')
        
        return self._clean_html(content)


# Demo/test function
def demo_scan():
    """Demo the scanner with sample feeds."""
    sample_config = {
        'data_sources': {
            'rss_feeds': [
                {
                    'name': 'Fierce Healthcare',
                    'url': 'https://www.fiercehealthcare.com/rss/xml',
                    'enabled': True
                }
            ],
            'lookback_days': 7
        }
    }
    
    scanner = NewsScanner(sample_config)
    articles = scanner.scan_all_feeds()
    
    print(f"\nFound {len(articles)} articles:")
    for article in articles[:5]:
        print(f"  - {article['title'][:60]}...")
        print(f"    Source: {article['source']}")
        print(f"    Date: {article['published_date']}")
        print()


if __name__ == '__main__':
    demo_scan()
