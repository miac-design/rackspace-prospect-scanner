#!/usr/bin/env python3
"""
Test script with sample articles to demonstrate the agent works.
Uses manually crafted test data that simulates real cloud migration announcements.
"""

import json
from reasoning.qualifier import ProspectQualifier

# Load config
with open('agent_config.json', 'r') as f:
    config = json.load(f)

qualifier = ProspectQualifier(config)

# Sample articles that simulate real cloud migration announcements
test_articles = [
    {
        'title': 'Mercy Health System Announces Major Cloud Migration to AWS',
        'summary': 'Mercy Health System announced a comprehensive cloud migration initiative today, partnering with AWS to modernize its IT infrastructure. The $75M project will move Epic EHR workloads and support AI-powered clinical decision tools. Seeking managed services partner for HIPAA compliant operations.',
        'url': 'https://example.com/mercy-aws',
        'source': 'Healthcare IT News',
        'published_date': '2026-01-20'
    },
    {
        'title': 'Regional Medical Center Seeks Cloud Partners for Digital Transformation',
        'summary': 'Valley Regional Medical Center is evaluating cloud providers for a major digital transformation project. The health system plans to migrate by 2027 and is looking for managed services support for AI infrastructure and compliance.',
        'url': 'https://example.com/valley-cloud',
        'source': 'Fierce Healthcare', 
        'published_date': '2026-01-19'
    },
    {
        'title': 'Kaiser Permanente Expands AI Operations with New Data Platform',
        'summary': 'Kaiser Permanente announced expansion of its AI operations with a new scalable data platform. The health system is scaling machine learning workloads and operationalizing AI for patient care coordination.',
        'url': 'https://example.com/kaiser-ai',
        'source': 'Healthcare IT News',
        'published_date': '2026-01-18'
    },
    {
        'title': 'HCA Healthcare Deploys Generative AI Across 180 Hospitals',
        'summary': 'HCA Healthcare is deploying generative AI and large language models across its hospital network. The initiative requires significant AI infrastructure and MLOps capabilities.',
        'url': 'https://example.com/hca-genai',
        'source': 'Becker\'s Health IT',
        'published_date': '2026-01-17'
    },
    {
        'title': 'Telehealth Bill Passes Senate Committee',
        'summary': 'A new telehealth bill has passed the Senate committee. This policy update affects healthcare providers nationwide.',
        'url': 'https://example.com/telehealth-bill',
        'source': 'Fierce Healthcare',
        'published_date': '2026-01-21'
    }
]

print("="*60)
print("TESTING PROSPECT QUALIFICATION")
print("="*60)

qualified = []
for i, article in enumerate(test_articles):
    print(f"\n--- Article {i+1}: {article['title'][:50]}...")
    result = qualifier.qualify(article)
    
    if result:
        print(f"✅ QUALIFIED - Score: {result['qualification_score']}/100")
        print(f"   Organization: {result['organization']}")
        print(f"   Rackspace Wedge: {result['rackspace_wedge']}")
        print(f"   AI Use Case: {result['ai_agent_use_case']}")
        print(f"   Priority: {result['priority']}")
        qualified.append(result)
    else:
        print("❌ Did not qualify")

print("\n" + "="*60)
print(f"SUMMARY: {len(qualified)}/{len(test_articles)} articles qualified as prospects")
print("="*60)

if qualified:
    print("\nQualified prospects would be saved to prospects_data.json")
    print(json.dumps(qualified, indent=2))
