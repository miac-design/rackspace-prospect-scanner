#!/usr/bin/env python3
"""
Rackspace Healthcare Prospect Scanner Agent
============================================
An AI agent that scans healthcare news, qualifies prospects against 
Rackspace's strategic criteria, and updates the prospect list.

NOTE: This is the LOCAL DEVELOPMENT entry point. For production automation,
use run_scan.py which is invoked by GitHub Actions (.github/workflows/prospect_scanner.yml).

Usage:
    python prospect_agent.py [--dry-run] [--verbose]
"""

import json
import logging
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# Import modules
from scanners.news_scanner import NewsScanner
from scanners.link_validator import LinkValidator
from reasoning.qualifier import ProspectQualifier
from outputs.html_updater import HTMLUpdater

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('ProspectAgent')


class ProspectAgent:
    """Main agent orchestrator for healthcare prospect scanning."""
    
    def __init__(self, config_path: str = 'agent_config.json'):
        """Initialize agent with configuration."""
        self.config = self._load_config(config_path)
        self.scanner = NewsScanner(self.config)
        self.qualifier = ProspectQualifier(self.config)
        self.html_updater = HTMLUpdater(self.config)
        self.prospects = []
        
    def _load_config(self, config_path: str) -> dict:
        """Load configuration from JSON file."""
        with open(config_path, 'r') as f:
            return json.load(f)
    
    def run(self, dry_run: bool = False, verbose: bool = False) -> list:
        """
        Execute full prospect scanning cycle.
        
        Args:
            dry_run: If True, don't update HTML file
            verbose: If True, print detailed progress
            
        Returns:
            List of qualified prospects
        """
        logger.info("🚀 Starting Healthcare Prospect Scanner Agent")
        logger.info(f"   Looking back {self.config['data_sources']['lookback_days']} days")
        
        # Step 1: Scan news sources
        if verbose:
            print("\n📡 Scanning news sources...")
        articles = self.scanner.scan_all_feeds()
        logger.info(f"   Found {len(articles)} articles")
        
        # Step 2: Qualify each article
        if verbose:
            print(f"\n🔍 Analyzing {len(articles)} articles...")
        qualified_prospects = []
        
        for article in articles:
            prospect = self.qualifier.qualify(article)
            if prospect and prospect['qualification_score'] >= self.config['qualification_threshold']:
                qualified_prospects.append(prospect)
                if verbose:
                    print(f"   ✅ {prospect['organization']} (Score: {prospect['qualification_score']})")
        
        logger.info(f"   Qualified {len(qualified_prospects)} prospects")
        
        # Step 3: Save prospects to JSON
        self._save_prospects(qualified_prospects)
        
        # Step 4: Update HTML (unless dry run)
        if not dry_run:
            if qualified_prospects:
                if verbose:
                    print("\n📝 Updating HTML prospect list...")
                # record_scan first (updates banner), then insert cards
                self.html_updater.record_scan(prospect_count=len(qualified_prospects))
                self.html_updater.update(qualified_prospects)
                logger.info("   HTML file updated")
                
                # Step 5: Validate all source links
                if verbose:
                    print("\n🔗 Validating source links...")
                self._validate_links(verbose)
            else:
                # No prospects — still record scan timestamp
                self.html_updater.record_scan(prospect_count=0)
                if verbose:
                    print("\n✅ No new prospects this scan — banner updated with scan time")
            
            # Step 6: Auto-deploy to Vercel
            if verbose:
                print("\n🚀 Deploying to Vercel...")
            self._deploy_to_vercel(verbose)
        else:
            logger.info("   Dry run - HTML not updated")
        
        # Step 7: Log summary
        self._log_activity(qualified_prospects)
        
        if verbose:
            self._print_summary(qualified_prospects)
        
        return qualified_prospects
    
    def _deploy_to_vercel(self, verbose: bool = False):
        """Deploy updated HTML to Vercel (requires npx on PATH)."""
        import subprocess
        import shutil
        
        # Check if npx is available before attempting deploy
        if not shutil.which('npx'):
            logger.info("   ℹ️  npx not found — skipping local deploy (GitHub Actions handles production deploys)")
            if verbose:
                print("   ℹ️  Skipping deploy (npx not on PATH — production deploys via GitHub Actions)")
            return
        
        try:
            html_path = Path(self.config['output']['html_file'])
            dist_path = Path('dist_prospects')
            dist_path.mkdir(exist_ok=True)
            
            # Only copy to index.html if this is the Healthcare config
            # BFSI config already writes directly to dist_prospects/bfsi.html
            if 'bfsi' not in str(html_path).lower():
                shutil.copy(html_path, dist_path / 'index.html')
                shutil.copy(html_path, dist_path / 'healthcare.html')
            
            # Run Vercel deploy
            result = subprocess.run(
                ['npx', '-y', 'vercel', '--prod', '--yes', '--public', './dist_prospects'],
                capture_output=True,
                text=True,
                cwd=str(Path(__file__).parent)
            )
            
            if result.returncode == 0:
                logger.info("   ✅ Deployed to Vercel successfully")
                if verbose:
                    print("   ✅ Live site updated!")
            else:
                logger.error(f"   ❌ Vercel deploy failed: {result.stderr}")
        except Exception as e:
            logger.error(f"   ❌ Deploy error: {e}")
    
    def _validate_links(self, verbose: bool = False):
        """Validate all source links and fix broken ones."""
        try:
            html_path = self.config['output']['html_file']
            validator = LinkValidator(html_path)
            
            # Validate all links
            results = validator.validate_all()
            
            if verbose:
                print(f"   Checked {results['total']} links")
                print(f"   ✓ Valid: {len(results['valid'])}")
                print(f"   ✗ Broken: {len(results['broken'])}")
            
            # Auto-fix broken links
            if results['broken']:
                fixed = validator.fix_broken_links(results)
                logger.info(f"   Fixed {fixed} broken links")
                if verbose:
                    print(f"   🔧 Fixed {fixed} broken links (replaced with signal badges)")
            else:
                logger.info("   All links valid!")
                if verbose:
                    print("   ✅ All links valid!")
                    
        except Exception as e:
            logger.error(f"   ❌ Link validation error: {e}")
    
    def _save_prospects(self, prospects: list):
        """Save prospects to JSON file."""
        output_path = self.config['output']['prospects_json']
        
        # Load existing prospects if file exists
        existing = []
        if Path(output_path).exists():
            with open(output_path, 'r') as f:
                existing = json.load(f)
        
        # Merge new prospects (avoid duplicates by organization name)
        existing_orgs = {p['organization'] for p in existing}
        for prospect in prospects:
            if prospect['organization'] not in existing_orgs:
                prospect['added_date'] = datetime.now().isoformat()
                prospect['status'] = 'new'
                existing.append(prospect)
        
        with open(output_path, 'w') as f:
            json.dump(existing, f, indent=2)
        
        logger.info(f"   Saved {len(existing)} total prospects to {output_path}")
    
    def _log_activity(self, prospects: list):
        """Log agent activity."""
        log_path = self.config['output']['log_file']
        
        with open(log_path, 'a') as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"Scan completed: {datetime.now().isoformat()}\n")
            f.write(f"Articles scanned: {self.scanner.last_scan_count}\n")
            f.write(f"Prospects qualified: {len(prospects)}\n")
            for p in prospects:
                f.write(f"  - {p['organization']} (Score: {p['qualification_score']})\n")
    
    def _print_summary(self, prospects: list):
        """Print human-readable summary."""
        print("\n" + "="*60)
        print("📊 SCAN SUMMARY")
        print("="*60)
        print(f"Date: {datetime.now().strftime('%B %d, %Y')}")
        print(f"New Prospects Found: {len(prospects)}")
        print()
        
        if prospects:
            print("HIGH-PRIORITY PROSPECTS:")
            print("-"*40)
            for p in sorted(prospects, key=lambda x: x['qualification_score'], reverse=True)[:5]:
                print(f"  🏥 {p['organization']}")
                print(f"     Score: {p['qualification_score']}/100")
                print(f"     Signal: {p['signal'][:60]}...")
                print(f"     Wedge: {p['rackspace_wedge']}")
                print()
        else:
            print("No new prospects found this cycle.")
        
        print("="*60)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Rackspace Healthcare Prospect Scanner Agent'
    )
    parser.add_argument(
        '--dry-run', 
        action='store_true',
        help='Scan and qualify but do not update HTML'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true', 
        help='Print detailed progress'
    )
    parser.add_argument(
        '--config',
        default='agent_config.json',
        help='Path to configuration file'
    )
    
    args = parser.parse_args()
    
    agent = ProspectAgent(config_path=args.config)
    prospects = agent.run(dry_run=args.dry_run, verbose=args.verbose)
    
    print(f"\n✅ Agent completed. Found {len(prospects)} qualified prospects.")


if __name__ == '__main__':
    main()
