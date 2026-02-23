"""
Prospect Qualifier Module
=========================
AI reasoning engine that qualifies prospects against Rackspace criteria.
Uses rules-based scoring with keyword matching and signal analysis.
"""

import re
import hashlib
import logging
from typing import Dict, Optional, List

logger = logging.getLogger('ProspectQualifier')


class ProspectQualifier:
    """Qualifies healthcare articles as potential Rackspace prospects."""
    
    def __init__(self, config: dict):
        """Initialize with configuration."""
        self.config = config
        self.criteria = config['qualification_criteria']
        self.value_props = config['rackspace_value_propositions']
        self.ai_use_cases = config['ai_agent_use_cases']
        self.categories = config['categories']
        self.signal_types = config.get('signal_types', {})
        self.expert_reviewers = config.get('expert_reviewers', {})
        
    def qualify(self, article: dict) -> Optional[Dict]:
        """
        Qualify an article as a potential prospect.
        
        Pipeline:
        1. Domain relevance gate (keyword)
        2. Org extraction (regex → Gemini fallback)
        3. Score calculation (weighted keywords + negation)
        4. Borderline LLM judge (Gemini for score 25-39)
        5. Threshold gate
        """
        # Combine all text for analysis
        full_text = f"{article['title']} {article['summary']} {article.get('content', '')}"
        full_text_lower = full_text.lower()
        title_short = article['title'][:80]
        
        # Step 0: Domain relevance gate — reject off-topic articles early
        if not self._is_domain_relevant(full_text_lower):
            logger.info(f"REJECTED [{title_short}] → Gate: DOMAIN (no domain terms found)")
            return None
        
        # Step 1: Extract organization name (regex first)
        organization = self._extract_organization(article['title'], article['summary'])
        
        # Step 1b: Calculate score first to decide if we should keep articles without org names
        scores = self._calculate_scores(full_text_lower)
        total_score = sum(scores.values())
        score_detail = ' | '.join(f"{k}:{v}" for k, v in scores.items() if v > 0) or 'no matches'
        
        # If no organization found, try fallbacks in order
        if not organization:
            if total_score >= 30:
                organization = self._extract_fallback_org(article['title'])
            
            # Gemini NER fallback — if regex fails and article has some signal
            if not organization and total_score >= 15:
                from reasoning.gemini_judge import extract_organization as gemini_extract
                gemini_org = gemini_extract(article['title'], article['summary'])
                if gemini_org:
                    organization = gemini_org
                    logger.info(f"GEMINI ORG [{title_short}] → {gemini_org}")
            
            if not organization and total_score >= 40:
                # Last resort: use source domain
                source = article.get('source', '')
                if source:
                    clean_source = source.replace('www.', '').split('.')[0].title()
                    organization = f"{clean_source} (Industry Signal)"
            
            if not organization:
                logger.info(f"REJECTED [{title_short}] → Gate: ORG (no company found, score={total_score}, {score_detail})")
                return None
        
        # Step 2: Use scores already calculated above
        
        # Step 3: Check for negative signals (disqualifiers)
        if self._has_negative_signals(full_text_lower):
            total_score -= 20  # Penalty for existing partnerships
            
        # Step 4: Apply category boost
        category = self._determine_category(full_text_lower)
        if category:
            total_score += self.categories[category].get('priority_boost', 0)
        
        # Step 5: Threshold gate — with Gemini judge for borderline cases
        threshold = self.config['qualification_threshold']
        borderline_floor = max(threshold - 15, 15)  # e.g., 25 when threshold is 40
        
        if total_score < threshold:
            # Borderline: close to threshold → ask Gemini
            if total_score >= borderline_floor:
                from reasoning.gemini_judge import judge_article
                domain = 'bfsi' if 'bfsi' in self.config.get('agent_name', '').lower() else 'healthcare'
                judgment = judge_article(
                    title=article['title'],
                    summary=article['summary'],
                    source=article.get('source', ''),
                    domain=domain,
                    current_score=total_score,
                    score_breakdown=scores,
                )
                
                if judgment and judgment.get('is_relevant') and judgment.get('confidence', 0) >= 0.6:
                    # Gemini says it's relevant — promote it
                    total_score = judgment['adjusted_score']
                    if judgment.get('organization'):
                        organization = judgment['organization']
                    logger.info(f"LLM PROMOTED [{title_short}] → score {total_score}, org={organization}")
                else:
                    reason = "LLM rejected" if judgment else "LLM unavailable"
                    logger.info(f"REJECTED [{title_short}] → Gate: SCORE+LLM ({total_score}/{threshold}, {reason}, {score_detail})")
                    return None
            else:
                logger.info(f"REJECTED [{title_short}] → Gate: SCORE ({total_score}/{threshold}, org={organization}, {score_detail})")
                return None
        
        # Step 6: Generate Rackspace-specific fields
        rackspace_wedge = self._generate_wedge(scores, full_text_lower)
        ai_use_case = self._suggest_ai_use_case(full_text_lower)
        priority = self._determine_priority(total_score)
        signal = self._extract_signal(article['title'], article['summary'])
        
        # Step 7: Detect signal type + reason to reach out (Madhavi feedback #1)
        signal_type, reach_out_reason = self._detect_signal_type(full_text_lower)
        
        # Step 8: Generate score audit trail (Madhavi feedback #3)
        score_audit = self._generate_score_audit(scores, total_score)
        
        # Step 9: Assign expert review status (Madhavi feedback #4)
        review_status, recommended_reviewer = self._assign_review_status(category)
        
        return {
            'organization': organization,
            'signal': signal,
            'signal_type': signal_type,
            'reach_out_reason': reach_out_reason,
            'source_url': article['url'],
            'source_date': article.get('published_date'),
            'source_name': article.get('source', 'Unknown'),
            'qualification_score': min(total_score, 100),  # Cap at 100
            'score_breakdown': scores,
            'score_audit': score_audit,
            'rackspace_wedge': rackspace_wedge,
            'ai_agent_use_case': ai_use_case,
            'category': self._format_category(category),
            'priority': priority,
            'review_status': review_status,
            'recommended_reviewer': recommended_reviewer,
            'verified': False  # To be verified by user
        }
    
    def _detect_signal_type(self, text: str) -> tuple:
        """
        Detect signal types from article text.
        Returns (primary_signal_type, reach_out_reason) with compound signals.
        """
        if not self.signal_types:
            return ('general', 'Potential managed services opportunity detected')
        
        matched_signals = []
        
        for sig_name, sig_def in self.signal_types.items():
            trigger_keywords = sig_def.get('trigger_keywords', [])
            matches = sum(1 for kw in trigger_keywords if kw.lower() in text)
            if matches > 0:
                matched_signals.append({
                    'name': sig_name,
                    'matches': matches,
                    'reason': sig_def.get('reach_out_reason', 'Industry activity detected'),
                })
        
        if not matched_signals:
            return ('general', 'Industry activity detected — worth monitoring for sales opportunity')
        
        # Sort by match count (strongest first)
        matched_signals.sort(key=lambda s: s['matches'], reverse=True)
        
        # Primary signal is the strongest
        primary = matched_signals[0]['name']
        
        # Compound signal: combine top 2 if multiple match
        if len(matched_signals) >= 2:
            signal_type = f"{matched_signals[0]['name']}+{matched_signals[1]['name']}"
            reason = f"{matched_signals[0]['reason']}. Additionally: {matched_signals[1]['reason']}"
        else:
            signal_type = primary
            reason = matched_signals[0]['reason']
        
        return (signal_type, reason)
    
    def _generate_score_audit(self, scores: dict, total: int) -> str:
        """
        Generate a human-readable scoring audit trail.
        Shows each criterion, matches found, and contribution to total.
        """
        parts = []
        for criterion, score in scores.items():
            weight = self.criteria.get(criterion, {}).get('weight', 0)
            if score > 0:
                parts.append(f"{criterion.replace('_', ' ').title()}: {score}/{weight}")
            else:
                parts.append(f"{criterion.replace('_', ' ').title()}: 0/{weight}")
        
        audit = ' | '.join(parts)
        return f"{audit} → Total: {total}"
    
    def _assign_review_status(self, category: str) -> tuple:
        """
        Assign expert review status and recommended reviewer based on category.
        Returns (review_status, recommended_reviewer).
        """
        reviewer = self.expert_reviewers.get(
            category, 
            self.expert_reviewers.get('default', 'Product Team')
        )
        return ('pending_expert_review', reviewer)
    
    def _is_domain_relevant(self, text: str) -> bool:
        """
        Check if the article text is actually about healthcare or BFSI.
        Scopes keyword check to the active pipeline's domain.
        """
        # Healthcare domain keywords
        healthcare_terms = [
            'health', 'hospital', 'patient', 'clinical', 'medical', 'ehr',
            'epic', 'cerner', 'physician', 'nurse', 'care coordination',
            'medicare', 'medicaid', 'hipaa', 'pharmacy', 'diagnosis',
            'treatment', 'surgery', 'telehealth', 'biotech', 'pharma',
            'fda', 'drug', 'therapy', 'wellness', 'mental health',
        ]
        
        # BFSI domain keywords
        bfsi_terms = [
            'bank', 'banking', 'financial', 'insurance', 'insurer',
            'underwriting', 'fintech', 'payment', 'lending', 'credit',
            'deposits', 'mortgage', 'wealth management', 'asset management',
            'hedge fund', 'private equity', 'trading', 'securities',
            'compliance', 'pci dss', 'sox', 'ffiec', 'glba',
            'claims', 'premium', 'policyholder', 'actuarial',
        ]
        
        # Scope to the active pipeline's domain
        agent_name = self.config.get('agent_name', '').lower()
        if 'bfsi' in agent_name:
            domain_terms = bfsi_terms
        elif 'healthcare' in agent_name:
            domain_terms = healthcare_terms
        else:
            # Fallback: check both (for unknown configs)
            domain_terms = healthcare_terms + bfsi_terms
        
        # Require at least 1 domain-relevant term to pass
        match_count = sum(1 for term in domain_terms if term in text)
        if match_count >= 1:
            return True
        
        logger.debug("   Article rejected: insufficient domain relevance")
        return False
    
    def _extract_organization(self, title: str, summary: str) -> Optional[str]:
        """Extract organization name from article."""
        # Common healthcare organization patterns (expanded)
        patterns = [
            # Standard health system patterns
            r'([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*\s+(?:Health(?:care)?|Hospital|Medical Center|Clinic|System|Network|Group)s?)',
            # Enterprise/Partner patterns
            r'([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*\s+(?:Enterprises|Partners|Solutions))',
            # Saint/Mount patterns
            r'((?:Mount|St\.?|Saint)\s+[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)',
            # Well-known company patterns (e.g., "GE HealthCare", "Philips")
            r'(GE\s+HealthCare|Philips|Siemens\s+Healthineers|Epic|Cerner|Oracle\s+Health)',
            # BFSI organization patterns (banks, insurers, financial institutions)
            r'([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*\s+(?:Bank|Insurance|Financial|Capital|Securities|Bancorp|Credit Union)s?)',
            # "Company announces/launches" pattern — strict: 2-4 capitalized words before verb
            r'([A-Z][a-zA-Z]{2,}(?:\s+[A-Z][a-zA-Z]{2,}){0,3})\s+(?:announces|launches|partners|expands|selects|deploys|unveils|raises|secures|hires)',
        ]
        
        text = f"{title} {summary}"
        
        for pattern in patterns:
            matches = re.findall(pattern, text)
            if matches:
                # Return the longest match (usually most specific)
                org = max(matches, key=len).strip()
                # Clean up common issues
                org = re.sub(r'\s+', ' ', org)
                # Filter out common false positives
                false_positives = [
                    'The', 'This', 'That', 'How', 'What', 'Why', 'New', 'More',
                    'According', 'Breaking', 'Report', 'Study', 'Update',
                    'Stage', 'Practice', 'Virtual', 'Digital', 'Here', 'Most',
                    'Several', 'Many', 'Some', 'Every', 'Next', 'Five', 'Top',
                    'Also', 'Just', 'Only', 'Even', 'Already', 'Nearly',
                ]
                # Quality gates:
                # 1. Must be > 5 chars
                # 2. Must not be a single common word
                # 3. Must be < 60 chars (reject sentence fragments)
                # 4. Must contain at least 2 words for non-known-company patterns
                # 5. First word must not be a common word
                if (len(org) > 5 
                    and org not in false_positives
                    and org.split()[0] not in false_positives
                    and len(org) <= 60
                    and (' ' in org or pattern == patterns[3])):
                    return org
        
        return None

    def _extract_fallback_org(self, title: str) -> Optional[str]:
        """Extract a fallback organization identifier from article title."""
        # For articles with strong signals but no clear org, create a descriptive identifier.
        # Quality checks to avoid garbage like 'the system', 'st India Proposes', etc.
        
        # Try to extract proper nouns at start of title
        match = re.match(r'^([A-Z][a-zA-Z]{2,}(?:\s+[A-Z][a-zA-Z]{2,}){0,3})', title)
        if match:
            potential_org = match.group(1).strip()
            
            # Quality gate: reject common garbage patterns
            garbage_patterns = [
                r'^(st|nd|rd|th)\s',    # RSS fragment artifacts like 'st India'
                r'^(the|a|an|how|what|why|new|more|top|best)\s',  # common words
                r'^(report|study|survey|analysis|update|breaking)\s', # generic headers
                r'^(google|apple|meta|microsoft|amazon)\s',  # big tech (not prospects)
                r'^(according|practice|stage|virtual|digital|why)\s',  # more garbage
                r'^(appeared|next|every|overall|here|just|also)\s',  # RSS fragments
                r'^(five|three|ten|seven|most|several|many|some)\s',  # quantifiers
                r'^(for|from|with|into|over|under|about|after|before)\s',  # prepositions
            ]
            for gp in garbage_patterns:
                if re.match(gp, potential_org, re.IGNORECASE):
                    return None
            
            # Must be at least 6 chars, contain at least one space (2+ words),
            # and be under 40 chars to avoid sentence fragments
            if len(potential_org) >= 6 and ' ' in potential_org and len(potential_org) <= 40:
                return potential_org
        
        return None
    
    def _calculate_scores(self, text: str) -> Dict[str, int]:
        """Calculate scores for each qualification criterion.
        
        Supports two keyword formats:
        - List: ["cloud migration", "AWS"]  → each keyword counts as weight 1
        - Dict: {"cloud migration": 3, "cloud": 0.5}  → per-keyword weights
        
        Also checks for negative context (negation words near keywords).
        """
        scores = {}
        negation_words = ['not', 'no ', 'never', 'abandons', 'exits', 'reduces',
                          'delays', 'cancels', 'drops', 'rejects', 'halts',
                          'suspends', 'without', 'lacks', "won't", "didn't"]
        
        for criterion_name, criterion_config in self.criteria.items():
            weight = criterion_config['weight']
            keywords_raw = criterion_config['keywords']
            
            # Normalize to {keyword: kw_weight} format
            if isinstance(keywords_raw, dict):
                keywords = keywords_raw
            else:
                # Flat list: all keywords equal weight 1.0
                keywords = {kw: 1.0 for kw in keywords_raw}
            
            # Score each keyword match
            weighted_sum = 0
            match_count = 0
            
            for kw, kw_weight in keywords.items():
                kw_lower = kw.lower()
                if kw_lower in text:
                    # Check for negative context: is there a negation word
                    # within 5 words (roughly 40 chars) before the keyword?
                    kw_pos = text.find(kw_lower)
                    context_start = max(0, kw_pos - 40)
                    context_window = text[context_start:kw_pos]
                    
                    negated = any(neg in context_window for neg in negation_words)
                    if negated:
                        logger.debug(f"   Negated keyword '{kw}' in context: ...{context_window}...")
                        continue  # Skip this match — it's negated
                    
                    weighted_sum += kw_weight
                    match_count += 1
            
            # Score: weighted sum normalized against criterion weight
            if match_count > 0:
                # Normalize: weighted_sum of 1.0 = 50% of criterion weight, 3.0+ = 100%
                score_pct = min(weighted_sum / 3.0, 1.0) * 0.5 + 0.5
                scores[criterion_name] = int(weight * score_pct)
            else:
                scores[criterion_name] = 0
        
        return scores
    
    def _has_negative_signals(self, text: str) -> bool:
        """Check for signals that indicate existing partnerships."""
        negative_keywords = self.criteria.get('managed_services_gap', {}).get('negative_signals', [])
        
        for signal in negative_keywords:
            if signal.lower() in text:
                logger.debug(f"   Negative signal found: {signal}")
                return True
        
        return False
    
    def _determine_category(self, text: str) -> Optional[str]:
        """Determine prospect category."""
        for category_name, category_config in self.categories.items():
            keywords = category_config['keywords']
            if any(kw.lower() in text for kw in keywords):
                return category_name
        # Default to first category in config (works for both Healthcare and BFSI)
        default = next(iter(self.categories), None)
        return default
    
    def _format_category(self, category: Optional[str]) -> str:
        """Format category for display."""
        category_map = {
            'health_system': 'Health System',
            'medtech': 'MedTech',
            'payer': 'Payer/Insurance',
            'banking': 'Banking',
            'insurance': 'Insurance',
            'fintech': 'FinTech',
            'asset_management': 'Asset Management',
            'bfsi': 'BFSI',
        }
        # Config-aware fallback instead of hardcoded 'Healthcare'
        agent_name = self.config.get('agent_name', '').lower()
        default = 'BFSI' if 'bfsi' in agent_name else 'Healthcare'
        return category_map.get(category, default)
    
    def _generate_wedge(self, scores: Dict[str, int], text: str) -> str:
        """Generate Rackspace value proposition wedge."""
        wedges = []
        
        # Detect which domain we're in
        is_bfsi = any(term in text for term in ['bank', 'insurance', 'fintech', 'payment', 'trading'])
        
        # Map high-scoring criteria to value propositions
        if scores.get('cloud_migration', 0) > 10:
            wedges.append("Post-migration optimization")
        if scores.get('managed_services_gap', 0) > 10:
            wedges.append("managed private cloud operations")
        if scores.get('ai_infrastructure', 0) > 10:
            wedges.append("AI/ML infrastructure management")
        if scores.get('compliance_sensitivity', 0) > 8:
            if is_bfsi:
                wedges.append("PCI/SOX-compliant hosting")
            else:
                wedges.append("HIPAA-compliant hosting")
        if scores.get('timing_urgency', 0) > 8:
            wedges.append("accelerated deployment support")
        
        if not wedges:
            # Deterministic fallback: use first value prop (not random)
            wedges = [self.value_props[0]]
        
        return ", ".join(wedges[:3])  # Limit to 3 wedges
    
    def _suggest_ai_use_case(self, text: str) -> str:
        """Suggest relevant AI agent use case."""
        # Map keywords to use cases — Healthcare triggers
        use_case_triggers = {
            'patient flow': 'Patient flow optimization agent',
            'surgical': 'Surgical scheduling optimization',
            'bed management': 'Bed management agent',
            'documentation': 'Clinical documentation automation',
            'prior auth': 'Prior authorization agent',
            'revenue cycle': 'Revenue cycle optimization agent',
            'supply chain': 'Supply chain prediction agent',
            'care coordination': 'Care coordination agent',
            'epic': 'EHR workflow automation agent',
            'ehr': 'EHR workflow automation agent',
            # BFSI triggers
            'fraud': 'Fraud detection and prevention agent',
            'kyc': 'KYC automation agent',
            'claims': 'Claims processing automation',
            'payment': 'Real-time payment monitoring agent',
            'trading': 'Trading anomaly detection agent',
            'compliance': 'Regulatory compliance monitoring',
            'underwriting': 'Automated underwriting agent',
            'credit': 'Credit risk assessment agent',
            'transaction': 'Transaction anomaly monitoring',
            'onboarding': 'Customer onboarding automation',
        }
        
        for trigger, use_case in use_case_triggers.items():
            if trigger in text:
                return use_case
        
        # Deterministic fallback: use first configured use case (not random)
        return self.ai_use_cases[0]
    
    def _determine_priority(self, score: int) -> str:
        """Determine prospect priority based on score."""
        if score >= 80:
            return 'High'
        elif score >= 65:
            return 'Medium'
        else:
            return 'Standard'
    
    def _extract_signal(self, title: str, summary: str) -> str:
        """Extract the key signal/news from the article."""
        # Prefer title if it's descriptive
        if len(title) > 30:
            return title
        
        # Otherwise use first sentence of summary
        sentences = summary.split('.')
        if sentences:
            return sentences[0].strip() + '.'
        
        return title


# Demo/test function
def demo_qualify():
    """Demo the qualifier with sample articles."""
    import json
    
    with open('agent_config.json', 'r') as f:
        config = json.load(f)
    
    qualifier = ProspectQualifier(config)
    
    # Sample article
    sample_article = {
        'title': 'Regional Health System Announces $50M Cloud Migration Initiative',
        'summary': 'ABC Healthcare announced plans to migrate its entire IT infrastructure to the cloud by 2027. The health system is seeking managed services partners to support HIPAA-compliant operations and AI infrastructure.',
        'url': 'https://example.com/news/abc-cloud',
        'source': 'Healthcare IT News',
        'published_date': '2026-01-20'
    }
    
    result = qualifier.qualify(sample_article)
    
    if result:
        print("\n✅ Prospect Qualified:")
        print(json.dumps(result, indent=2))
    else:
        print("\n❌ Article did not qualify")


if __name__ == '__main__':
    demo_qualify()
