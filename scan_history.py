#!/usr/bin/env python3
"""
Scan History Logger
====================
Appends a structured JSON record after every scan. Provides observability
into pipeline performance over time: articles fetched, prospects qualified,
pass rates, feed errors, and more.

Usage (imported by run_scan.py):
    from scan_history import record_scan_history
    record_scan_history(config_name, articles_count, qualified_count, feed_errors)
"""
import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger('ScanHistory')

HISTORY_FILE = 'scan_history.json'


def load_history() -> list:
    """Load existing scan history."""
    if Path(HISTORY_FILE).exists():
        try:
            with open(HISTORY_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
    return []


def record_scan_history(
    config_name: str,
    articles_fetched: int,
    articles_after_lookback: int,
    prospects_qualified: int,
    prospects_inserted: int,
    prospects_deduped: int = 0,
    feed_errors: list = None,
    threshold: int = 65,
):
    """
    Record a single scan run to the history file.
    
    Args:
        config_name: Which config was used (e.g., 'agent_config.json')
        articles_fetched: Total articles from RSS feeds
        articles_after_lookback: Articles remaining after date filter
        prospects_qualified: Number that passed scoring threshold
        prospects_inserted: Number actually inserted into HTML (after dedup)
        prospects_deduped: Number skipped as duplicates
        feed_errors: List of feed names that errored
        threshold: Qualification threshold used
    """
    history = load_history()
    
    pass_rate = (prospects_qualified / articles_after_lookback * 100) if articles_after_lookback > 0 else 0
    
    entry = {
        'timestamp': datetime.now().isoformat(),
        'config': config_name,
        'pipeline': 'BFSI' if 'bfsi' in config_name.lower() else 'Healthcare',
        'metrics': {
            'articles_fetched': articles_fetched,
            'articles_after_lookback': articles_after_lookback,
            'prospects_qualified': prospects_qualified,
            'prospects_inserted': prospects_inserted,
            'prospects_deduped': prospects_deduped,
            'pass_rate_pct': round(pass_rate, 1),
        },
        'threshold': threshold,
        'feed_errors': feed_errors or [],
    }
    
    history.append(entry)
    
    # Keep last 100 entries to avoid file bloat
    if len(history) > 100:
        history = history[-100:]
    
    with open(HISTORY_FILE, 'w') as f:
        json.dump(history, f, indent=2, default=str)
    
    logger.info(f"Recorded scan: {config_name} → {prospects_qualified}/{articles_after_lookback} qualified ({pass_rate:.1f}%)")
    return entry


def get_summary(last_n: int = 10) -> dict:
    """Get a summary of the last N scans."""
    history = load_history()
    recent = history[-last_n:]
    
    if not recent:
        return {'message': 'No scan history available'}
    
    hc_scans = [h for h in recent if h['pipeline'] == 'Healthcare']
    bfsi_scans = [h for h in recent if h['pipeline'] == 'BFSI']
    
    def avg_metric(scans, key):
        vals = [s['metrics'][key] for s in scans]
        return round(sum(vals) / len(vals), 1) if vals else 0
    
    return {
        'total_scans': len(recent),
        'healthcare': {
            'scans': len(hc_scans),
            'avg_articles': avg_metric(hc_scans, 'articles_fetched'),
            'avg_qualified': avg_metric(hc_scans, 'prospects_qualified'),
            'avg_pass_rate': avg_metric(hc_scans, 'pass_rate_pct'),
        },
        'bfsi': {
            'scans': len(bfsi_scans),
            'avg_articles': avg_metric(bfsi_scans, 'articles_fetched'),
            'avg_qualified': avg_metric(bfsi_scans, 'prospects_qualified'),
            'avg_pass_rate': avg_metric(bfsi_scans, 'pass_rate_pct'),
        },
    }


if __name__ == '__main__':
    summary = get_summary()
    print(json.dumps(summary, indent=2))
