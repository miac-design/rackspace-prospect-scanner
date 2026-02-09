#!/usr/bin/env python3
"""
Feed Health Monitor
====================
Tracks RSS feed health over time. Auto-disables feeds after 3 consecutive
failures. Logs all results to feed_health.json for observability.

Usage:
    python feed_health.py              # Check all feeds
    python feed_health.py --auto-fix   # Check and auto-disable failing feeds
"""
import json
import urllib.request
import ssl
import argparse
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger('FeedHealth')

HEALTH_FILE = 'feed_health.json'
FAILURE_THRESHOLD = 3  # Auto-disable after this many consecutive failures

# SSL context for feed checks
ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE


def load_health_data() -> dict:
    """Load existing health tracking data."""
    if Path(HEALTH_FILE).exists():
        try:
            with open(HEALTH_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            logger.warning("feed_health.json corrupted, starting fresh")
    return {'feeds': {}, 'last_check': None}


def save_health_data(data: dict):
    """Save health tracking data."""
    with open(HEALTH_FILE, 'w') as f:
        json.dump(data, f, indent=2, default=str)


def check_feed(url: str, timeout: int = 10) -> dict:
    """Check if an RSS feed is accessible. Returns status dict."""
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Rackspace Feed Health Monitor)'
        })
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_ctx) as resp:
            status = resp.status
            content_length = len(resp.read())
        return {
            'status': 'ok',
            'http_code': status,
            'content_bytes': content_length,
            'error': None,
        }
    except urllib.error.HTTPError as e:
        return {'status': 'error', 'http_code': e.code, 'content_bytes': 0, 'error': str(e)}
    except urllib.error.URLError as e:
        return {'status': 'error', 'http_code': 0, 'content_bytes': 0, 'error': str(e.reason)}
    except Exception as e:
        return {'status': 'error', 'http_code': 0, 'content_bytes': 0, 'error': str(e)}


def check_all_feeds(config_paths: list) -> dict:
    """Check all feeds across configs and update health tracking."""
    health = load_health_data()
    results = {'ok': [], 'failing': [], 'auto_disabled': []}
    
    for config_path in config_paths:
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        agent_name = config.get('agent_name', config_path)
        feeds = config['data_sources']['rss_feeds']
        
        print(f"\n📡 Checking feeds for {agent_name}...")
        
        for feed in feeds:
            name = feed['name']
            url = feed['url']
            enabled = feed.get('enabled', True)
            
            # Track by URL as unique key
            feed_key = url
            if feed_key not in health['feeds']:
                health['feeds'][feed_key] = {
                    'name': name,
                    'config': config_path,
                    'consecutive_failures': 0,
                    'total_checks': 0,
                    'total_failures': 0,
                    'last_status': None,
                    'last_check': None,
                }
            
            tracker = health['feeds'][feed_key]
            tracker['total_checks'] += 1
            
            if not enabled:
                print(f"   ⏭  {name}: Disabled (skipping)")
                continue
            
            result = check_feed(url)
            tracker['last_check'] = datetime.now().isoformat()
            tracker['last_status'] = result['status']
            
            if result['status'] == 'ok':
                tracker['consecutive_failures'] = 0
                results['ok'].append(name)
                print(f"   ✅ {name}: HTTP {result['http_code']} ({result['content_bytes']} bytes)")
            else:
                tracker['consecutive_failures'] += 1
                tracker['total_failures'] += 1
                results['failing'].append({
                    'name': name,
                    'url': url,
                    'config': config_path,
                    'error': result['error'],
                    'consecutive_failures': tracker['consecutive_failures'],
                })
                print(f"   ❌ {name}: {result['error']} (failures: {tracker['consecutive_failures']})")
    
    health['last_check'] = datetime.now().isoformat()
    save_health_data(health)
    return results


def auto_disable_failing(results: dict, threshold: int = FAILURE_THRESHOLD):
    """Auto-disable feeds that exceed the failure threshold."""
    disabled_count = 0
    
    for failing in results['failing']:
        if failing['consecutive_failures'] >= threshold:
            config_path = failing['config']
            feed_url = failing['url']
            
            with open(config_path, 'r') as f:
                config = json.load(f)
            
            for feed in config['data_sources']['rss_feeds']:
                if feed['url'] == feed_url:
                    feed['enabled'] = False
                    feed['_disabled_reason'] = (
                        f"Auto-disabled: {failing['consecutive_failures']} consecutive failures. "
                        f"Last error: {failing['error']}"
                    )
                    feed['_disabled_date'] = datetime.now().isoformat()
                    disabled_count += 1
                    print(f"   🔴 AUTO-DISABLED: {failing['name']} ({failing['consecutive_failures']} failures)")
                    break
            
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=4)
            
            results['auto_disabled'].append(failing['name'])
    
    return disabled_count


def main():
    parser = argparse.ArgumentParser(description='RSS Feed Health Monitor')
    parser.add_argument('--auto-fix', action='store_true',
                        help=f'Auto-disable feeds after {FAILURE_THRESHOLD} consecutive failures')
    args = parser.parse_args()
    
    config_paths = ['agent_config.json', 'bfsi_agent_config.json']
    results = check_all_feeds(config_paths)
    
    if args.auto_fix and results['failing']:
        print(f"\n🔧 Auto-fix mode: disabling feeds with {FAILURE_THRESHOLD}+ failures...")
        disabled = auto_disable_failing(results)
        if disabled:
            print(f"   Disabled {disabled} feed(s)")
    
    # Summary
    print(f"\n{'='*50}")
    print(f"  FEED HEALTH SUMMARY")
    print(f"  ✅ Healthy: {len(results['ok'])}")
    print(f"  ❌ Failing: {len(results['failing'])}")
    if results['auto_disabled']:
        print(f"  🔴 Auto-disabled: {len(results['auto_disabled'])}")
    print(f"{'='*50}")


if __name__ == '__main__':
    main()
