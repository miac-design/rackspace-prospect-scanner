"""
HTML Updater Module
===================
Updates the Rackspace Healthcare/BFSI Prospects HTML file with new prospects.
Generates cards that match the existing CSS design system.
"""

import re
import logging
from datetime import datetime
from typing import List, Dict
from pathlib import Path

logger = logging.getLogger('HTMLUpdater')

# Stable insertion anchor present in the dist HTML files. New prospect cards
# are inserted immediately before this comment, so it always marks the next
# insertion point. Far more robust than inferring document structure.
INSERT_ANCHOR = '<!-- MIRA:INSERT-NEW-PROSPECTS -->'


class HTMLUpdater:
    """Updates HTML prospect document with new entries."""
    
    def __init__(self, config: dict):
        """Initialize with configuration."""
        self.config = config
        self.html_path = config['output']['html_file']
        # Detect if this is a BFSI config based on agent name or output file
        self.is_bfsi = 'bfsi' in self.html_path.lower() or 'BFSI' in config.get('agent_name', '')
        


    def record_scan(self, prospect_count: int = 0) -> bool:
        """
        Record that a scan happened, even if zero prospects were added.
        Updates the Pipeline Status banner so the user always knows when
        the system last checked.
        """
        if not Path(self.html_path).exists():
            logger.warning(f"HTML file not found: {self.html_path}")
            return False
        
        try:
            with open(self.html_path, 'r', encoding='utf-8') as f:
                html_content = f.read()
            
            html_content = self._update_timestamp(html_content, prospect_count=prospect_count)
            
            with open(self.html_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            logger.info(f"   Recorded scan result: {prospect_count} prospects")
            return True
        except Exception as e:
            logger.error(f"   Error recording scan: {e}")
            return False
    
    def update(self, prospects: List[Dict]) -> bool:
        """
        Update HTML file with new prospects.
        
        Args:
            prospects: List of qualified prospect dictionaries
            
        Returns:
            True if successful, False otherwise
        """
        if not Path(self.html_path).exists():
            logger.warning(f"HTML file not found: {self.html_path}")
            return False
        
        try:
            with open(self.html_path, 'r', encoding='utf-8') as f:
                html_content = f.read()
            
            # Note: Deduplication is handled upstream by the IdempotencyManifest.
            # All prospects passed here are guaranteed to be new.
            new_prospects = prospects
            
            # Generate new prospect cards
            new_cards_html = self._generate_prospect_cards(new_prospects)
            
            # Add a batch timestamp comment
            timestamp = datetime.now().isoformat()
            batch_html = f'\n<!-- New Prospects Added {timestamp} -->\n{new_cards_html}'
            
            # Primary strategy: insert immediately before the stable anchor
            # comment, which lives inside the prospect list container. The
            # anchor stays in place, marking the next insertion point.
            inserted = False
            if INSERT_ANCHOR in html_content:
                new_html = html_content.replace(
                    INSERT_ANCHOR,
                    f'{batch_html}\n                    {INSERT_ANCHOR}',
                    1,
                )
                inserted = True
            else:
                # Legacy fallbacks for documents without the anchor
                logger.warning("   Insertion anchor missing — trying legacy patterns")
                insertion_patterns = [
                    r'(<div class="removed-section")',
                    r'(<footer)',
                    r'(</div>\s*<script)',
                ]
                for pattern in insertion_patterns:
                    match = re.search(pattern, html_content, re.DOTALL)
                    if match:
                        insert_pos = match.start()
                        new_html = (
                            html_content[:insert_pos] +
                            batch_html + '\n' +
                            html_content[insert_pos:]
                        )
                        inserted = True
                        break

                if not inserted and '</body>' in html_content:
                    new_html = html_content.replace(
                        '</body>', f'{batch_html}\n</body>', 1)
                    inserted = True
                    logger.warning("   Used fallback insertion (before </body>)")

            if not inserted:
                # Document is malformed (no anchor, no known landmarks, no
                # </body>). Fail loudly instead of silently writing the file
                # unchanged and letting the banner claim prospects were added.
                logger.error(
                    f"   INSERTION FAILED: no anchor or landmark found in "
                    f"{self.html_path} — cards NOT added")
                return False

            # Note: timestamp is updated by record_scan() — no need to call _update_timestamp again

            with open(self.html_path, 'w', encoding='utf-8') as f:
                f.write(new_html)

            logger.info(f"   Added {len(new_prospects)} prospects to HTML")
            return True
            
        except Exception as e:
            logger.error(f"   Error updating HTML: {e}")
            return False
    
    def _generate_prospect_cards(self, prospects: List[Dict]) -> str:
        """Generate HTML cards for new prospects."""
        cards = []
        
        for prospect in prospects:
            card = self._generate_single_card(prospect)
            cards.append(card)
        
        return '\n'.join(cards)
    
    def _generate_single_card(self, prospect: Dict) -> str:
        """
        Generate a single prospect card HTML that matches the existing page design.
        Uses the same CSS classes as the hand-crafted original cards.
        Enhanced with: signal type, reach-out reason, score audit, review status.
        """
        # Determine priority styling
        priority = prospect.get('priority', 'Standard')
        score = prospect.get('qualification_score', 0)
        
        # Choose use-case tag classes based on available data
        use_case_tags = self._generate_use_case_tags(prospect)
        
        # Format source date
        source_date = prospect.get('source_date', '')
        formatted_date = self._format_date(source_date)
        
        # Build the wedge text
        wedge_text = prospect.get('rackspace_wedge', 'Managed cloud services opportunity')
        ai_use_case = prospect.get('ai_agent_use_case', 'AI operations support')
        
        # Determine signal pills
        signal_pills = self._generate_signal_pills(prospect)
        
        # Build offer recommendation
        offer = self._suggest_offer(prospect)
        
        # Source link
        source_url = prospect.get('source_url', '#')
        source_name = prospect.get('source_name', 'News')
        
        # New fields from manager feedback
        signal_type = prospect.get('signal_type', 'general').replace('_', ' ').title()
        reach_out_reason = prospect.get('reach_out_reason', '')
        score_audit = prospect.get('score_audit', '')
        review_status = prospect.get('review_status', 'pending_expert_review')
        recommended_reviewer = prospect.get('recommended_reviewer', 'Product Team')
        website_note = prospect.get('website_data', {}).get('enrichment_note', '') if isinstance(prospect.get('website_data'), dict) else ''
        
        # Review status badge
        if review_status == 'expert_approved':
            review_badge = '<span style="background: #22c55e; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.65rem;">✓ Expert Approved</span>'
        elif review_status == 'expert_rejected':
            review_badge = '<span style="background: #ef4444; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.65rem;">✗ Rejected</span>'
        else:
            review_badge = f'<span style="background: #f59e0b; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.65rem;">⏳ Needs Review — {recommended_reviewer}</span>'
        
        # Color variables depend on healthcare vs BFSI
        if self.is_bfsi:
            primary_color = 'var(--blue-primary)'
        else:
            primary_color = 'var(--plum)'
        
        # Build reach-out reason box (only if available). Spans the full grid
        # width so the card never renders a half-empty row.
        reach_out_html = ''
        if reach_out_reason:
            reach_out_html = f'''
                    <div class="info-box" style="grid-column: 1 / -1; border-left: 3px solid {primary_color}; background: rgba(139, 92, 246, 0.05);">
                        <div class="label">💡 Reason to Reach Out <span style="font-size: 0.6rem; background: {primary_color}; color: white; padding: 1px 6px; border-radius: 3px; margin-left: 6px;">{signal_type}</span></div>
                        <div class="info-text"><strong>{reach_out_reason}</strong></div>
                    </div>'''
        
        # Build score audit section (collapsible)
        score_audit_html = ''
        if score_audit:
            score_audit_html = f'''
                        <div class="intel-item">
                            <div class="intel-label">Score Breakdown</div>
                            <div class="intel-value" style="font-size: 0.75rem; font-family: monospace;">{score_audit}</div>
                        </div>'''
        
        # Build website enrichment note
        website_html = ''
        if website_note:
            website_html = f'''
                        <div class="intel-item">
                            <div class="intel-label">Website Intel</div>
                            <div class="intel-value">{website_note}</div>
                        </div>'''

        # Build Current Vendors chips from website enrichment (same markup as
        # the hand-curated cards) so auto-cards match the original design.
        vendors_html = ''
        vendor_badges = self._generate_vendor_badges(prospect)
        if vendor_badges:
            vendors_html = f'''
                        <div class="intel-item">
                            <div class="intel-label">Current Vendors</div>
                            <div class="vendor-badges">
                                {vendor_badges}
                            </div>
                        </div>'''
        
        card_html = f'''
                <!-- NEW PROSPECT: {prospect['organization']} (Auto-added {datetime.now().strftime('%Y-%m-%d')}) -->
                <div class="prospect-card" data-use-cases="{prospect.get('data_use_cases', 'ai-analytics')}">
                    <div class="card-header">
                        <div>
                            <div class="company-name">{prospect['organization']} <span style="font-size: 0.65rem; background: {primary_color}; color: white; padding: 2px 6px; border-radius: 4px; margin-left: 8px; vertical-align: middle;">NEW</span></div>
                            <div class="company-type">{prospect.get('category', 'Healthcare')} • {priority} Priority {review_badge}</div>
                            {use_case_tags}
                        </div>
                        <div class="score-badge"><span class="score-number">{score}</span><span class="score-label">score</span></div>
                    </div>

                    <div class="info-grid">
                        <div class="info-box">
                            <div class="label">Rackspace Wedge</div>
                            <div class="info-text">
                                <strong>{wedge_text}</strong>
                            </div>
                        </div>
                        <div class="info-box ai-use-case">
                            <div class="label">AI Opportunity (Suggested)</div>
                            <div class="info-text">
                                <strong>{ai_use_case}</strong>
                            </div>
                        </div>{reach_out_html}
                    </div>

                    <div class="offer-recommendation">
                        <div class="label">Recommended Rackspace Offer</div>
                        <div class="offer-text">{offer}</div>
                    </div>

                    <div class="intelligence-section">
                        <div class="intel-item">
                            <div class="intel-label">Signal</div>
                            <div class="intel-value">{prospect.get('signal', 'Industry signal detected')}</div>
                        </div>
                        <div class="intel-item">
                            <div class="intel-label">Signals</div>
                            <div class="signal-pills">
                                {signal_pills}
                            </div>
                        </div>{vendors_html}{score_audit_html}{website_html}
                        <div class="intel-item">
                            <div class="intel-label">Source</div>
                            <div class="intel-value">
                                <a href="{source_url}" target="_blank">✓ {source_name} ({formatted_date})</a>
                            </div>
                        </div>
                        <div class="intel-item">
                            <div class="intel-label">Review Status</div>
                            <div class="intel-value">{review_badge}</div>
                        </div>
                        <div class="intel-item">
                            <div class="intel-label">Added to List</div>
                            <div class="intel-value">{datetime.now().strftime('%B %d, %Y')}</div>
                        </div>
                    </div>
                </div>'''
        return card_html
    
    def _generate_vendor_badges(self, prospect: Dict) -> str:
        """Build vendor-badge chips from website-enrichment tech hints.

        Maps raw keyword hits (e.g. 'aws', 'google cloud') to display names
        and renders the same `vendor-badge` markup as the curated cards.
        Returns '' when no enrichment data exists — the section is omitted
        rather than shown empty.
        """
        website_data = prospect.get('website_data')
        if not isinstance(website_data, dict):
            return ''

        display_names = {
            'aws': 'AWS',
            'amazon web services': 'AWS',
            'azure': 'Azure',
            'google cloud': 'Google Cloud',
            'gcp': 'Google Cloud',
            'openstack': 'OpenStack',
            'kubernetes': 'Kubernetes',
        }

        vendors = []
        for hint in website_data.get('tech_stack_hints', []):
            name = display_names.get(str(hint).lower())
            if name and name not in vendors:
                vendors.append(name)

        badges = [f'<span class="vendor-badge">{v}</span>' for v in vendors[:4]]
        return '\n                                '.join(badges)

    def _generate_use_case_tags(self, prospect: Dict) -> str:
        """Generate use-case tag HTML based on prospect data."""
        tags = []
        text = f"{prospect.get('rackspace_wedge', '')} {prospect.get('ai_agent_use_case', '')} {prospect.get('signal', '')}".lower()
        
        if any(kw in text for kw in ['ai', 'ml', 'machine learning', 'genai', 'llm']):
            tags.append('<span class="use-case-tag ai-analytics">AI Analytics</span>')
        if any(kw in text for kw in ['hipaa', 'compliance', 'pci', 'sox', 'regulatory']):
            tags.append('<span class="use-case-tag compliance">Compliance</span>')
        if any(kw in text for kw in ['migration', 'hybrid', 'cloud']):
            tags.append('<span class="use-case-tag hybrid-migration">Hybrid Migration</span>')
        if any(kw in text for kw in ['secure', 'security', 'hosting', 'private cloud']):
            tags.append('<span class="use-case-tag secure-hosting">Secure Hosting</span>')
        if any(kw in text for kw in ['fraud', 'detection', 'anomaly']):
            tags.append('<span class="use-case-tag fraud-detection">Fraud Detection</span>')
        
        if not tags:
            tags.append('<span class="use-case-tag ai-analytics">AI Analytics</span>')
        
        return f'<div class="use-case-tags">{" ".join(tags)}</div>'
    
    def _generate_signal_pills(self, prospect: Dict) -> str:
        """Generate signal pill HTML based on prospect data."""
        pills = []
        text = f"{prospect.get('signal', '')} {prospect.get('rackspace_wedge', '')}".lower()
        
        if any(kw in text for kw in ['cloud', 'migration', 'aws', 'azure', 'gcp']):
            pills.append('<span class="signal-pill cloud">Cloud Migration</span>')
        if any(kw in text for kw in ['digital transformation', 'modernization']):
            pills.append('<span class="signal-pill digital">Digital Transformation</span>')
        if any(kw in text for kw in ['ai', 'ml', 'genai', 'llm']):
            pills.append('<span class="signal-pill digital">GenAI</span>')
        if any(kw in text for kw in ['merger', 'm&a', 'acquisition']):
            pills.append('<span class="signal-pill ma">M&A</span>')
        if any(kw in text for kw in ['funding', 'raised', 'investment']):
            pills.append('<span class="signal-pill funding">Funding</span>')
        
        if not pills:
            pills.append('<span class="signal-pill digital">Industry Signal</span>')
        
        return '\n                                '.join(pills)
    
    def _suggest_offer(self, prospect: Dict) -> str:
        """Suggest a Rackspace offer based on prospect signals."""
        text = f"{prospect.get('rackspace_wedge', '')} {prospect.get('ai_agent_use_case', '')}".lower()
        
        if 'private cloud' in text and 'ai' in text:
            return 'Private Cloud + AI Agents'
        elif 'migration' in text:
            return 'OpenStack Flex + Managed Migration'
        elif 'compliance' in text or 'hipaa' in text or 'pci' in text:
            return 'Private Cloud + Managed Compliance'
        elif 'ai' in text or 'ml' in text:
            return 'AI Agents + Managed Infrastructure'
        else:
            return 'Private Cloud + Managed Services'
    
    def _format_date(self, date_str: str) -> str:
        """Format a date string for display."""
        if not date_str:
            return 'Recent'
        try:
            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            return dt.strftime('%b %d, %Y')
        except:
            return date_str
    
    def _update_timestamp(self, html: str, prospect_count: int = 0) -> str:
        """Update the Pipeline Status banner with scan results."""
        try:
            from zoneinfo import ZoneInfo
            now = datetime.now(ZoneInfo('America/Chicago'))
            tz_label = 'CST' if now.strftime('%Z') == 'CST' else 'CDT'
        except ImportError:
            # Fallback for older Python without zoneinfo
            from datetime import timedelta
            now = datetime.utcnow() - timedelta(hours=6)
            tz_label = 'CST'
        date_str = now.strftime('%B %d, %Y')
        time_str = now.strftime('%I:%M %p').lstrip('0')
        full_timestamp = f"{date_str} at {time_str} {tz_label}"
        
        # Build the result message
        if prospect_count > 0:
            result_msg = f"📊 <strong>{prospect_count} new prospect{'s' if prospect_count != 1 else ''} added</strong>"
            result_display = ''
        else:
            result_msg = "✅ <strong>No new prospects this week</strong> — all scanned articles were below threshold"
            result_display = ''
        
        # Replace the scan-timestamp paragraph content
        timestamp_replacement = f'<p id="scan-timestamp">🕐 <strong>Last scanned:</strong> {full_timestamp}</p>'
        html = re.sub(
            r'<p id="scan-timestamp">.*?</p>',
            timestamp_replacement,
            html,
            flags=re.DOTALL
        )
        
        # Replace the scan-result paragraph
        result_replacement = f'<p id="scan-result">{result_msg}</p>'
        html = re.sub(
            r'<p id="scan-result"[^>]*>.*?</p>',
            result_replacement,
            html,
            flags=re.DOTALL
        )
        
        logger.info(f"   Updated scan banner: {full_timestamp} | {prospect_count} prospects")
        return html


# Demo function
def demo_update():
    """Demo the HTML updater with matching card format."""
    import json
    
    with open('agent_config.json', 'r') as f:
        config = json.load(f)
    
    updater = HTMLUpdater(config)
    
    # Sample prospect
    sample_prospects = [{
        'organization': 'Demo Health System',
        'signal': 'Announced major cloud initiative with AI infrastructure expansion',
        'source_url': 'https://example.com',
        'source_date': '2026-01-22',
        'source_name': 'Healthcare IT News',
        'qualification_score': 75,
        'rackspace_wedge': 'Managed private cloud, AI ops infrastructure',
        'ai_agent_use_case': 'Patient flow optimization agent',
        'category': 'Health System',
        'priority': 'High'
    }]
    
    # Generate card HTML (without actually updating file)
    card = updater._generate_single_card(sample_prospects[0])
    print("Generated card HTML:")
    print(card)


if __name__ == '__main__':
    demo_update()
