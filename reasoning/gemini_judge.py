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
import re
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


def resolve_entity(title: str, summary: str) -> dict:
    """
    Resolve the primary company in an article to a canonical name + domain.

    Single structured LLM call that does NER + canonicalization + domain
    lookup at once. This is the PRIMARY org-resolution path (regex is the
    offline fallback). Returns clean account names a seller recognizes
    instead of headline fragments.

    Returns:
        {
            'name': str,                 # canonical company name (no headline verbs)
            'domain': str or None,       # primary website domain, e.g. 'wellspan.org'
            'is_specific_company': bool, # False for industry groups / govt / generic
            'confidence': float,         # 0.0 - 1.0
        }
        or None if the API is unavailable or the response can't be parsed.
    """
    if not is_available():
        return None

    prompt = f"""You are a B2B sales-intelligence entity resolver.
Identify the PRIMARY company or organization that is the SUBJECT of this article —
the specific entity a managed-cloud vendor (Rackspace) would sell TO.

Rules:
- Ignore media outlets, news wires, industry associations, government agencies,
  and generic groups ("the industry", "hospitals") UNLESS one of them is clearly
  the subject being sold to.
- Return the CANONICAL company name as commonly known — no headline verbs
  ("Launches", "Announces"), no trailing descriptors, no duplicated words.
- Return the company's PRIMARY website domain (e.g. "wellspan.org"), or null if unsure.

Title: {title}
Summary: {summary[:400]}

Respond ONLY as JSON (no markdown, no backticks):
{{"name": "Canonical Company Name or null", "domain": "example.com or null", "is_specific_company": true/false, "confidence": 0.0-1.0}}"""

    try:
        result = _call_gemini(prompt)
        if result:
            parsed = _parse_entity(result)
            if parsed:
                logger.info(f"ENTITY RESOLVED [{title[:60]}] → "
                            f"name={parsed.get('name')}, domain={parsed.get('domain')}, "
                            f"specific={parsed.get('is_specific_company')}, "
                            f"confidence={parsed.get('confidence')}")
                return parsed
    except Exception as e:
        logger.warning(f"Entity resolution failed for [{title[:60]}]: {e}")

    return None


def _clean_domain(domain) -> str:
    """Normalize an LLM-proposed domain to a bare host, or None if unusable."""
    if not domain or not isinstance(domain, str):
        return None
    d = domain.strip().lower()
    if not d or d == 'null':
        return None
    d = re.sub(r'^https?://', '', d)   # strip protocol if a full URL came back
    d = d.split('/')[0]                # drop any path
    if d.startswith('www.'):
        d = d[4:]
    # Must look like a real domain: a dot, no spaces
    if '.' not in d or ' ' in d:
        return None
    return d


def _parse_entity(text: str) -> dict:
    """Parse the resolve_entity JSON response, clamping/cleaning fields."""
    text = _clean_json_text(text)
    if not text:
        return None
    try:
        result = json.loads(text)
        name = result.get('name')
        if not name or not isinstance(name, str) or name.strip().lower() == 'null':
            return None
        return {
            'name': name.strip().strip('"').strip("'"),
            'domain': _clean_domain(result.get('domain')),
            'is_specific_company': bool(result.get('is_specific_company', True)),
            'confidence': max(0.0, min(1.0, float(result.get('confidence', 0.5)))),
        }
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.debug(f"Failed to parse entity response: {e}\nRaw: {text[:200]}")
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


def _clean_json_text(text: str) -> str:
    """Strip markdown code fences and language tags from an LLM JSON response."""
    if not text:
        return ''
    text = text.strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[1] if '\n' in text else text[3:]
    if text.endswith('```'):
        text = text[:-3]
    text = text.strip()
    if text.startswith('json'):
        text = text[4:].strip()
    return text


def _parse_response(text: str) -> dict:
    """Parse Gemini's JSON response, handling common formatting issues."""
    text = _clean_json_text(text)
    if not text:
        return None

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
