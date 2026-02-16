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
        
        Args:
            article: Article dictionary with title, summary, content, url, etc.
            
        Returns:
            Prospect dictionary if qualified, None otherwise
        """
        # Combine all text for analysis
        full_text = f"{article['title']} {article['summary']} {article.get('content', '')}"
        full_text_lower = full_text.lower()
        
        # Step 0: Domain relevance gate — reject off-topic articles early
        if not self._is_domain_relevant(full_text_lower):
            return None
        
        # Step 1: Extract organization name (with fallback)
        organization = self._extract_organization(article['title'], article['summary'])
        
        # Step 1b: Calculate score first to decide if we should keep articles without org names
        scores = self._calculate_scores(full_text_lower)
        total_score = sum(scores.values())
        
        # If no organization found but strong signals, use a fallback
        if not organization:
            if total_score >= 50:  # Raised from 40 — require stronger signals for fallback
                organization = self._extract_fallback_org(article['title'])
            if not organization:
                return None
        
        # Step 2: Use scores already calculated above (line 49)
        
        # Step 3: Check for negative signals (disqualifiers)
        if self._has_negative_signals(full_text_lower):
            total_score -= 20  # Penalty for existing partnerships
            
        # Step 4: Apply category boost
        category = self._determine_category(full_text_lower)
        if category:
            total_score += self.categories[category].get('priority_boost', 0)
        
        # Step 5: Skip if below threshold
        if total_score < self.config['qualification_threshold']:
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
        Detect the primary signal type from article text.
        Returns (signal_type_name, reach_out_reason) based on config signal_types.
        """
        if not self.signal_types:
            return ('general', 'Potential managed services opportunity detected')
        
        best_type = None
        best_count = 0
        
        for sig_name, sig_def in self.signal_types.items():
            trigger_keywords = sig_def.get('trigger_keywords', [])
            matches = sum(1 for kw in trigger_keywords if kw.lower() in text)
            if matches > best_count:
                best_count = matches
                best_type = sig_name
        
        if best_type and best_count > 0:
            reason = self.signal_types[best_type].get(
                'reach_out_reason', 'Potential managed services opportunity'
            )
            return (best_type, reason)
        
        return ('general', 'Industry activity detected — worth monitoring for sales opportunity')
    
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
        
        # Require at least 2 domain-relevant terms to pass
        match_count = sum(1 for term in domain_terms if term in text)
        if match_count >= 2:
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
            # Generic "Company announces" pattern
            r'([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)\s+(?:announces|launches|partners|expands|selects)',
        ]
        
        text = f"{title} {summary}"
        
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                # Return the longest match (usually most specific)
                org = max(matches, key=len).strip()
                # Clean up common issues
                org = re.sub(r'\s+', ' ', org)
                # Filter out common false positives
                false_positives = [
                    'The', 'This', 'That', 'How', 'What', 'Why', 'New', 'More',
                    'According', 'Breaking', 'Report', 'Study', 'Update',
                    'Stage', 'Practice', 'Virtual', 'Digital',
                ]
                # Quality gates:
                # 1. Must be > 5 chars
                # 2. Must not be a single common word
                # 3. Must be < 60 chars (reject sentence fragments)
                # 4. Must contain at least 2 words for non-known-company patterns
                if (len(org) > 5 
                    and org not in false_positives
                    and len(org) <= 60
                    and (' ' in org or pattern == patterns[3])):
                    return org
        
        return None
    
    def _extract_fallback_org(self, title: str) -> Optional[str]:
        """Extract a fallback organization identifier from article title."""
        # For articles with strong signals but no clear org, create a descriptive identifier.
        # Quality checks to avoid garbage like 'the system', 'st India Proposes', etc.
        
        # Try to extract proper nouns at start of title
        match = re.match(r'^([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,3})', title)
        if match:
            potential_org = match.group(1).strip()
            
            # Quality gate: reject common garbage patterns
            garbage_patterns = [
                r'^(st|nd|rd|th)\s',    # RSS fragment artifacts like 'st India'
                r'^(the|a|an|how|what|why|new|more|top|best)\s',  # common words
                r'^(report|study|survey|analysis|update|breaking)\s', # generic headers
                r'^(google|apple|meta|microsoft|amazon)\s',  # big tech (not prospects)
                r'^(according|practice|stage|virtual|digital|why)\s',  # more garbage
                r'^(appeared|first|last|next|every|overall)\s',  # RSS fragments
            ]
            for gp in garbage_patterns:
                if re.match(gp, potential_org, re.IGNORECASE):
                    return None
            
            # Must be at least 6 chars, contain at least one space (2+ words),
            # and be under 50 chars to avoid sentence fragments
            if len(potential_org) >= 6 and ' ' in potential_org and len(potential_org) <= 50:
                return f"{potential_org} (Industry Signal)"
        
        return None
    
    def _calculate_scores(self, text: str) -> Dict[str, int]:
        """Calculate scores for each qualification criterion."""
        scores = {}
        
        for criterion_name, criterion_config in self.criteria.items():
            weight = criterion_config['weight']
            keywords = criterion_config['keywords']
            
            # Count keyword matches
            match_count = sum(1 for kw in keywords if kw.lower() in text)
            
            # Score is weighted by match density (more matches = higher score, capped)
            if match_count > 0:
                # Normalize: 1 match = 50% of weight, 3+ matches = 100%
                score_pct = min(match_count / 3, 1.0) * 0.5 + 0.5
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
