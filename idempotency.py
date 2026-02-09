#!/usr/bin/env python3
"""
Idempotency Manifest
=====================
Hash-based deduplication that ensures running the pipeline N times
produces identical output to running it once.

Each prospect is identified by a deterministic hash of (org_name + source_url).
The manifest stores all seen prospect IDs. Components check the manifest
before inserting, rather than relying on fragile HTML comment parsing.

Usage (imported by other modules):
    from idempotency import IdempotencyManifest
    manifest = IdempotencyManifest()
    if manifest.is_new(org_name, source_url):
        # insert card
        manifest.mark_seen(org_name, source_url)
"""
import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger('Idempotency')

MANIFEST_FILE = 'prospect_manifest.json'


class IdempotencyManifest:
    """Hash-based manifest for prospect deduplication."""
    
    def __init__(self, manifest_path: str = MANIFEST_FILE):
        """Initialize with manifest file path."""
        self.manifest_path = manifest_path
        self.data = self._load()
    
    def _load(self) -> dict:
        """Load manifest from disk."""
        if Path(self.manifest_path).exists():
            try:
                with open(self.manifest_path, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                logger.warning("Manifest file corrupted, starting fresh")
                return {'version': 1, 'prospects': {}}
        return {'version': 1, 'prospects': {}}
    
    def _save(self):
        """Persist manifest to disk."""
        with open(self.manifest_path, 'w') as f:
            json.dump(self.data, f, indent=2, default=str)
    
    @staticmethod
    def _hash(org_name: str, source_url: str) -> str:
        """Generate a deterministic hash for a prospect."""
        key = f"{org_name.strip().lower()}|{source_url.strip().lower()}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]
    
    def is_new(self, org_name: str, source_url: str) -> bool:
        """Check if a prospect has never been seen before."""
        prospect_id = self._hash(org_name, source_url)
        return prospect_id not in self.data['prospects']
    
    def mark_seen(self, org_name: str, source_url: str, score: int = 0):
        """Record a prospect as seen."""
        prospect_id = self._hash(org_name, source_url)
        self.data['prospects'][prospect_id] = {
            'org': org_name,
            'url': source_url,
            'score': score,
            'first_seen': datetime.now().isoformat(),
        }
        self._save()
        logger.debug(f"Marked seen: {org_name} ({prospect_id})")
    
    def filter_new(self, prospects: list) -> list:
        """
        Filter a list of prospects, returning only ones not in the manifest.
        Also marks the returned prospects as seen.
        
        Args:
            prospects: List of prospect dicts with 'organization' and 'source_url'
            
        Returns:
            List of prospects that are genuinely new
        """
        new_prospects = []
        for p in prospects:
            org = p.get('organization', '')
            url = p.get('source_url', '')
            if self.is_new(org, url):
                new_prospects.append(p)
                self.mark_seen(org, url, score=p.get('qualification_score', 0))
            else:
                logger.info(f"   Skipped duplicate: {org}")
        return new_prospects
    
    @property
    def count(self) -> int:
        """Number of unique prospects in manifest."""
        return len(self.data['prospects'])
    
    def summary(self) -> dict:
        """Return manifest summary stats."""
        prospects = self.data['prospects']
        return {
            'total_unique_prospects': len(prospects),
            'manifest_file': self.manifest_path,
        }
