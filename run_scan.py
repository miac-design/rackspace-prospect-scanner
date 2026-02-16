#!/usr/bin/env python3
"""
Standalone scanner that uses built-in Python libraries only.
Scans RSS feeds, qualifies articles, updates HTML with timestamp.
No external dependencies (feedparser) needed.
"""
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import logging
import sys
import ssl
import shutil
import argparse
from pathlib import Path
from reasoning.qualifier import ProspectQualifier
from outputs.html_updater import HTMLUpdater
from idempotency import IdempotencyManifest
from scan_history import record_scan_history

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('StandaloneScanner')

# Bypass SSL verification for RSS feeds
ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE


def fetch_rss(url: str, timeout: int = 10) -> list:
    """Fetch and parse an RSS feed using built-in libraries."""
    articles = []
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Rackspace Prospect Scanner)'})
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_ctx) as resp:
            raw = resp.read()
        root = ET.fromstring(raw)
        
        # Handle both RSS and Atom feeds
        # RSS: channel/item
        for item in root.findall('.//item'):
            title = item.findtext('title', '').strip()
            desc = item.findtext('description', '').strip()
            link = item.findtext('link', '').strip()
            pub_date = item.findtext('pubDate', '')
            source = url.split('/')[2]  # domain as source name
            
            # Clean HTML from description
            desc = re.sub(r'<[^>]+>', '', desc)
            
            if title:
                articles.append({
                    'title': title,
                    'summary': desc[:500],
                    'content': desc,
                    'url': link,
                    'source': source,
                    'published_date': pub_date,
                })
        
        # Atom: entry
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        for entry in root.findall('.//atom:entry', ns):
            title = entry.findtext('atom:title', '', ns).strip()
            summary = entry.findtext('atom:summary', '', ns).strip()
            link_el = entry.find('atom:link', ns)
            link = link_el.get('href', '') if link_el is not None else ''
            pub_date = entry.findtext('atom:published', '', ns) or entry.findtext('atom:updated', '', ns)
            source = url.split('/')[2]
            
            summary = re.sub(r'<[^>]+>', '', summary)
            
            if title:
                articles.append({
                    'title': title,
                    'summary': summary[:500],
                    'content': summary,
                    'url': link,
                    'source': source,
                    'published_date': pub_date,
                })
    except Exception as e:
        logger.warning(f"   Failed to fetch {url}: {e}")
    
    return articles


def filter_by_lookback(articles: list, lookback_days: int) -> list:
    """Filter articles older than lookback_days."""
    cutoff = datetime.now() - timedelta(days=lookback_days)
    filtered = []
    for article in articles:
        pub = article.get('published_date', '')
        if not pub:
            filtered.append(article)  # Keep articles with no date (can't determine age)
            continue
        try:
            # Try ISO format
            dt = datetime.fromisoformat(pub.replace('Z', '+00:00')).replace(tzinfo=None)
        except ValueError:
            try:
                # Try RFC 2822 format (common in RSS)
                from email.utils import parsedate_to_datetime
                dt = parsedate_to_datetime(pub).replace(tzinfo=None)
            except Exception:
                filtered.append(article)  # Can't parse date, keep it
                continue
        if dt >= cutoff:
            filtered.append(article)
    return filtered


def run_scan(config_path: str, dry_run: bool = False):
    """Run a full scan for the given config.
    
    Args:
        config_path: Path to the agent config JSON file.
        dry_run: If True, qualify articles but don't write to HTML/JSON/manifest.
    """
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    agent_name = config.get('agent_name', config_path)
    mode_tag = ' [DRY RUN]' if dry_run else ''
    print(f"\n{'='*60}")
    print(f"  SCANNING: {agent_name}{mode_tag}")
    print(f"{'='*60}")
    
    # Step 1: Fetch articles from all RSS feeds
    feeds = config['data_sources']['rss_feeds']
    all_articles = []
    feed_errors = []
    
    for feed in feeds:
        if not feed.get('enabled', True):
            continue
        url = feed['url']
        print(f"\n📡 Fetching: {feed['name']}...")
        articles = fetch_rss(url)
        if not articles:
            feed_errors.append(feed['name'])
        print(f"   Found {len(articles)} articles")
        all_articles.extend(articles)
    
    total_fetched = len(all_articles)
    print(f"\n📊 Total articles fetched: {total_fetched}")
    
    # Step 1b: Filter by lookback period
    lookback_days = config['data_sources'].get('lookback_days', 7)
    all_articles = filter_by_lookback(all_articles, lookback_days)
    articles_after_lookback = len(all_articles)
    print(f"   After lookback filter ({lookback_days} days): {articles_after_lookback} articles")
    
    # Step 2: Qualify articles
    qualifier = ProspectQualifier(config)
    qualified = []
    
    for article in all_articles:
        prospect = qualifier.qualify(article)
        if prospect:
            qualified.append(prospect)
            signal_type = prospect.get('signal_type', 'general')
            print(f"   ✅ {prospect['organization']} (Score: {prospect['qualification_score']}, Signal: {signal_type})")
    
    print(f"\n🎯 Qualified prospects: {len(qualified)}/{articles_after_lookback}")
    
    if dry_run:
        print(f"\n📊 DRY RUN complete — {len(qualified)} would be processed. No files modified.")
        for p in qualified:
            print(f"   • {p['organization']} | Score: {p['qualification_score']} | Signal: {p.get('signal_type', '?')}")
            print(f"     Reach Out: {p.get('reach_out_reason', 'N/A')}")
            print(f"     Audit: {p.get('score_audit', 'N/A')}")
            print(f"     Review: {p.get('review_status', '?')} → {p.get('recommended_reviewer', '?')}")
        return qualified
    
    # Step 2c: Website enrichment (non-blocking, optional)
    try:
        from scanners.website_scanner import WebsiteScanner
        ws = WebsiteScanner(timeout=8)
        print(f"\n🌐 Enriching prospects with website data...")
        for i, prospect in enumerate(qualified):
            enriched = ws.enrich_prospect(prospect)
            note = enriched.get('website_data', {}).get('enrichment_note', '')
            if note and 'no_domain_found' not in enriched.get('website_data', {}).get('status', ''):
                print(f"   🌐 {prospect['organization']}: {note}")
        print(f"   Website enrichment complete")
    except Exception as e:
        print(f"   ⚠️  Website enrichment skipped: {e}")
    
    # Step 2b: Idempotency — filter out already-seen prospects
    manifest = IdempotencyManifest()
    new_prospects = manifest.filter_new(qualified)
    deduped_count = len(qualified) - len(new_prospects)
    if deduped_count > 0:
        print(f"   🔁 Skipped {deduped_count} already-seen prospect(s)")
    
    # Step 3: Update HTML
    updater = HTMLUpdater(config)
    
    # Always record scan time
    updater.record_scan(prospect_count=len(new_prospects))
    print(f"   📝 Updated Pipeline Status banner")
    
    # Insert cards if any new
    if new_prospects:
        updater.update(new_prospects)
        print(f"   📝 Inserted {len(new_prospects)} new prospect cards")
    else:
        print(f"   ✅ No new prospects — banner timestamp updated")
    
    # Save to JSON (append new prospects)
    output_json = config['output']['prospects_json']
    existing = []
    if Path(output_json).exists():
        try:
            with open(output_json, 'r') as f:
                existing = json.load(f)
        except (json.JSONDecodeError, IOError):
            existing = []
    
    for prospect in new_prospects:
        prospect['added_date'] = datetime.now().isoformat()
        existing.append(prospect)
    
    with open(output_json, 'w') as f:
        json.dump(existing, f, indent=2, default=str)
    
    # Step 4: Record scan history
    record_scan_history(
        config_name=config_path,
        articles_fetched=total_fetched,
        articles_after_lookback=articles_after_lookback,
        prospects_qualified=len(qualified),
        prospects_inserted=len(new_prospects),
        prospects_deduped=deduped_count,
        feed_errors=feed_errors,
        threshold=config['qualification_threshold'],
    )
    
    return new_prospects


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Rackspace Prospect Scanner')
    parser.add_argument('--dry-run', action='store_true',
                        help='Qualify articles without writing to HTML/JSON/manifest')
    args = parser.parse_args()
    
    # Run Healthcare scan
    hc_prospects = run_scan('agent_config.json', dry_run=args.dry_run)
    
    # Run BFSI scan
    bfsi_prospects = run_scan('bfsi_agent_config.json', dry_run=args.dry_run)
    
    if not args.dry_run:
        # Copy Healthcare source to dist (both index and healthcare page)
        shutil.copy('Rackspace_Healthcare_Prospects.html', 'dist_prospects/index.html')
        shutil.copy('Rackspace_Healthcare_Prospects.html', 'dist_prospects/healthcare.html')
        print("\n✅ Copied Healthcare HTML → dist_prospects/index.html + healthcare.html")
    
    print(f"\n{'='*60}")
    print(f"  SCAN COMPLETE{'  [DRY RUN]' if args.dry_run else ''}")
    print(f"  Healthcare: {len(hc_prospects)} prospects")
    print(f"  BFSI: {len(bfsi_prospects)} prospects")
    print(f"{'='*60}")
