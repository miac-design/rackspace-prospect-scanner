"""
Gemini LLM Judge Module
========================
Uses Google Gemini API to:
1. Extract real company names from articles (replacing regex fallbacks)
2. Judge borderline articles for Rackspace sales relevance
3. Generate contextual reach-out reasons

Only called for borderline articles (score 25-39) to minimize API usage.
Falls back gracefully to regex if API is unavailable.
"""

import json
import logging
import os
import urllib.request
import ssl

logger = logging.getLogger('GeminiJudge')

# Gemini API configuration
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')


def is_available() -> bool:
    """Check if Gemini API is configured."""
    return bool(GEMINI_API_KEY)


def judge_article(title: str, summary: str, source: str, domain: str,
                  current_score: int, score_breakdown: dict) -> dict:
    """
    Ask Gemini to judge a borderline article for Rackspace sales relevance.
    
    Args:
        title: Article title
        summary: Article summary/description
        source: Source domain
        domain: 'healthcare' or 'bfsi'
        current_score: Current keyword-based score
        score_breakdown: Dict of criterion scores
        
    Returns:
        {
            'organization': str or None,
            'is_relevant': bool,
            'confidence': float (0-1),
            'adjusted_score': int,
            'reach_out_reason': str,
            'signal_type': str,
        }
    """
    if not is_available():
        logger.debug("Gemini API not configured — skipping LLM judge")
        return None
    
    prompt = f"""You are a Rackspace Technology sales intelligence analyst.
Analyze this article and determine if it represents a sales opportunity for Rackspace's managed cloud, AI infrastructure, or compliance services.

ARTICLE:
Title: {title}
Summary: {summary[:500]}
Source: {source}
Domain: {domain.upper()}

CURRENT SCORING:
Keyword score: {current_score}/100
Breakdown: {json.dumps(score_breakdown)}

INSTRUCTIONS:
1. Extract the PRIMARY COMPANY/ORGANIZATION mentioned (not media outlets, not 'the industry')
2. Judge if this company could be a Rackspace prospect (needs cloud, AI infra, or compliance services)
3. Assign a confidence score (0.0 to 1.0)
4. If relevant, explain WHY Rackspace should reach out in 1-2 sentences

Respond in this exact JSON format (no markdown, no backticks):
{{"organization": "Company Name or null", "is_relevant": true/false, "confidence": 0.0-1.0, "adjusted_score": 0-100, "reach_out_reason": "Why Rackspace should care", "signal_type": "cloud_initiative|ai_adoption|compliance_pressure|leadership_change|expansion_funding|general"}}"""

    try:
        result = _call_gemini(prompt)
        if result:
            parsed = _parse_response(result)
            if parsed:
                logger.info(f"LLM JUDGE [{title[:60]}] → org={parsed.get('organization')}, "
                           f"relevant={parsed.get('is_relevant')}, "
                           f"confidence={parsed.get('confidence')}, "
                           f"adjusted={parsed.get('adjusted_score')}")
                return parsed
    except Exception as e:
        logger.warning(f"Gemini judge failed for [{title[:60]}]: {e}")
    
    return None


def extract_organization(title: str, summary: str) -> str:
    """
    Use Gemini to extract the real company name from an article.
    Faster, simpler prompt for org extraction only.
    """
    if not is_available():
        return None
    
    prompt = f"""Extract the PRIMARY COMPANY or ORGANIZATION name from this article.
Return ONLY the company name, nothing else. If no specific company is mentioned, return "null".
Do not return media outlet names, industry groups, or government acronyms unless they ARE the subject.

Title: {title}
Summary: {summary[:300]}

Company name:"""

    try:
        result = _call_gemini(prompt)
        if result:
            org = result.strip().strip('"').strip("'")
            # Quality check
            if org and org.lower() != 'null' and len(org) > 2 and len(org) < 60:
                return org
    except Exception as e:
        logger.debug(f"Gemini org extraction failed: {e}")
    
    return None


def _call_gemini(prompt: str, max_tokens: int = 300) -> str:
    """Make a raw HTTP call to Gemini API (no SDK dependency)."""
    url = f"{GEMINI_API_URL}?key={GEMINI_API_KEY}"
    
    payload = json.dumps({
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        "generationConfig": {
            "temperature": 0.1,  # Low temp for consistent structured output
            "maxOutputTokens": max_tokens,
        }
    }).encode('utf-8')
    
    req = urllib.request.Request(
        url,
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    
    # Allow self-signed certs in CI
    ctx = ssl.create_default_context()
    
    with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    
    # Extract text from Gemini response
    candidates = data.get('candidates', [])
    if candidates:
        parts = candidates[0].get('content', {}).get('parts', [])
        if parts:
            return parts[0].get('text', '')
    
    return None


def _parse_response(text: str) -> dict:
    """Parse Gemini's JSON response, handling common formatting issues."""
    if not text:
        return None
    
    # Strip markdown code fences if present
    text = text.strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[1] if '\n' in text else text[3:]
    if text.endswith('```'):
        text = text[:-3]
    text = text.strip()
    
    # Remove 'json' language tag
    if text.startswith('json'):
        text = text[4:].strip()
    
    try:
        result = json.loads(text)
        
        # Validate required fields
        required = ['organization', 'is_relevant', 'confidence', 'adjusted_score']
        if all(k in result for k in required):
            # Clamp values
            result['confidence'] = max(0.0, min(1.0, float(result['confidence'])))
            result['adjusted_score'] = max(0, min(100, int(result['adjusted_score'])))
            return result
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.debug(f"Failed to parse Gemini response: {e}\nRaw: {text[:200]}")
    
    return None
