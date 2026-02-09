#!/usr/bin/env python3
"""Debug script to see what articles are being scanned and why they don't qualify."""

import json
from scanners.news_scanner import NewsScanner
from reasoning.qualifier import ProspectQualifier

# Load config
with open('agent_config.json', 'r') as f:
    config = json.load(f)

scanner = NewsScanner(config)
qualifier = ProspectQualifier(config)

# Scan articles
articles = scanner.scan_all_feeds()

print(f"\n{'='*60}")
print(f"SCANNED {len(articles)} ARTICLES")
print('='*60)

for i, article in enumerate(articles[:10]):  # First 10 only
    print(f"\n--- Article {i+1} ---")
    print(f"Title: {article['title'][:80]}...")
    print(f"Source: {article['source']}")
    
    # Try to extract org
    org = qualifier._extract_organization(article['title'], article['summary'])
    print(f"Org Extracted: {org}")
    
    # Calculate score
    full_text = f"{article['title']} {article['summary']} {article.get('content', '')}"
    scores = qualifier._calculate_scores(full_text.lower())
    total = sum(scores.values())
    print(f"Score: {total}/100 (threshold: {config['qualification_threshold']})")
    print(f"  cloud_migration: {scores.get('cloud_migration', 0)}")
    print(f"  ai_infrastructure: {scores.get('ai_infrastructure', 0)}")
    print(f"  compliance: {scores.get('compliance_sensitivity', 0)}")
    
    # Why didn't it qualify?
    if not org:
        print("❌ REJECTED: No organization found")
    elif total < config['qualification_threshold']:
        print(f"❌ REJECTED: Score too low ({total} < {config['qualification_threshold']})")
    else:
        print("✅ Would qualify!")

print("\n" + "="*60)
