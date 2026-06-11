#!/usr/bin/env python3
"""
One-off Backfill: Clean Org Names in Already-Deployed HTML
==========================================================
The org-extraction fix (commit "Fix org extraction…") cleans org names for
FUTURE scans. But prospect cards are append-only static HTML — names baked in
by past scans (e.g. "CharmHealth Launches MCP Server (Industry Signal)") are
never revisited. This script fixes those existing cards once.

Two actions, reusing the SAME canonical normalizer the live pipeline uses
(ProspectQualifier._normalize_org) so backfill and pipeline stay consistent:

  * RENAME — headline-fragment names → canonical account name
             ("CharmHealth Launches MCP Server (Industry Signal)" → "CharmHealth")
  * DROP   — cards that aren't real prospect accounts
             (analyst firms / vendor partner-program announcements, e.g.
              "KLAS Digital Pathology", "AWS Premier Tier Partner …")

Runs fully offline (no GEMINI_API_KEY needed) — normalization is deterministic.

Usage:
    python backfill_org_names.py            # dry run: report only, no writes
    python backfill_org_names.py --apply    # rewrite the HTML files
"""

import argparse
import json
import re
import shutil
from pathlib import Path

from reasoning.qualifier import ProspectQualifier

# Files to clean. index.html is a mirror of healthcare.html — re-mirrored after.
TARGET_FILES = ['dist_prospects/healthcare.html', 'dist_prospects/bfsi.html']

# Substrings that mark a card as NOT a real prospect account. Checked against
# the NORMALIZED name, so clean subjects ("CharmHealth") are unaffected even if
# their original headline mentioned a product ("MCP Server").
_DROP_MARKERS = (
    'klas',                  # KLAS Research — analyst firm, not a buyer
    'premier tier partner',  # AWS/partner-program announcements
    'tier partner',
    'press corner',
    'newswire',
    'webinar',
)
# Pure infrastructure vendors — not prospects when they LEAD the name.
_VENDOR_LEADERS = ('aws ', 'amazon web services ', 'google cloud ',
                   'microsoft azure ', 'azure ', 'oracle cloud ')


def feed_source_labels() -> set:
    """Derive the set of feed-domain labels (e.g. 'finextra', 'fiercehealthcare')
    from both agent configs. The pipeline's last-resort path names a card after
    the source feed's domain ('Finextra (Industry Signal)') — a card named
    after a news feed is a media outlet, not an account, and gets dropped."""
    labels = set()
    for cfg_path in ('agent_config.json', 'bfsi_agent_config.json'):
        if not Path(cfg_path).exists():
            continue
        with open(cfg_path) as f:
            cfg = json.load(f)
        for feed in cfg.get('data_sources', {}).get('rss_feeds', []):
            host = feed['url'].split('/')[2].replace('www.', '')
            labels.add(host.split('.')[0].lower())
    return labels


def is_real_org(name: str, feed_labels: set) -> bool:
    """Conservative gate: True unless the name is clearly a non-account."""
    if not name:
        return False
    low = name.lower()
    if any(m in low for m in _DROP_MARKERS):
        return False
    if any(low.startswith(v) for v in _VENDOR_LEADERS):
        return False
    if low in feed_labels:  # card named after the news feed itself
        return False
    return True


def _card_span(html: str, start: int) -> int:
    """Return the end index of a <div class="prospect-card"> element via
    balanced-div matching."""
    depth = 0
    for m in re.finditer(r'<div\b|</div\s*>', html[start:]):
        if m.group().startswith('</'):
            depth -= 1
            if depth == 0:
                return start + m.end()
        else:
            depth += 1
    return len(html)


def _comment_start(html: str, card_start: int) -> int:
    """If a `<!-- NEW PROSPECT: … -->` comment immediately precedes the card
    (only whitespace between), return its start so it's dropped with the card."""
    c = html.rfind('<!-- NEW PROSPECT:', 0, card_start)
    if c != -1:
        cend = html.find('-->', c) + 3
        if html[cend:card_start].strip() == '':
            return c
    return card_start


def process_file(path: str, normalize, feed_labels: set, apply: bool):
    """Scan one HTML file; return (renames, drops) and optionally rewrite it."""
    html = Path(path).read_text()
    edits = []  # (start, end, replacement) — applied bottom-up
    renames, drops = [], []

    for cm in re.finditer(r'<div class="prospect-card"', html):
        card_start = cm.start()
        card_end = _card_span(html, card_start)
        card = html[card_start:card_end]

        nm = re.search(r'<div class="company-name">(.*?)(<span|</div>)',
                       card, re.DOTALL)
        if not nm:
            continue
        raw = re.sub(r'\s+', ' ', nm.group(1)).strip()
        canonical = normalize(raw)

        # DROP: not a real account
        if not canonical or not is_real_org(canonical, feed_labels):
            drops.append((path, raw))
            edits.append((_comment_start(html, card_start), card_end, ''))
            continue

        # RENAME: name changed after normalization
        if canonical != raw:
            renames.append((path, raw, canonical))
            # 1) the visible company-name text node
            name_abs = card_start + nm.start(1)
            edits.append((name_abs, card_start + nm.end(1), canonical + ' '))
            # 2) the matching name inside the preceding HTML comment
            c = html.rfind('<!-- NEW PROSPECT:', 0, card_start)
            if c != -1:
                cend = html.find('-->', c)
                ctext = html[c:cend]
                if raw in ctext:
                    off = ctext.index(raw)
                    edits.append((c + off, c + off + len(raw), canonical))

    if apply and edits:
        for s, e, repl in sorted(edits, key=lambda x: x[0], reverse=True):
            html = html[:s] + repl + html[e:]
        Path(path).write_text(html)

    return renames, drops


def main():
    parser = argparse.ArgumentParser(description='Backfill clean org names into deployed HTML')
    parser.add_argument('--apply', action='store_true',
                        help='Rewrite HTML files (default: dry-run report only)')
    args = parser.parse_args()

    # Reuse the live pipeline's canonical normalizer.
    with open('agent_config.json') as f:
        config = json.load(f)
    normalize = ProspectQualifier(config)._normalize_org
    feed_labels = feed_source_labels()

    all_renames, all_drops = [], []
    for path in TARGET_FILES:
        if not Path(path).exists():
            print(f"  ⚠️  Skipping missing file: {path}")
            continue
        renames, drops = process_file(path, normalize, feed_labels, args.apply)
        all_renames += renames
        all_drops += drops

    print(f"\n{'APPLIED' if args.apply else 'DRY RUN'} — backfill org names\n" + '=' * 50)
    print(f"\n✏️  RENAME ({len(all_renames)}):")
    for path, raw, new in all_renames:
        print(f"   [{Path(path).name}] {raw!r}\n        → {new!r}")
    print(f"\n🗑️  DROP ({len(all_drops)}):")
    for path, raw in all_drops:
        print(f"   [{Path(path).name}] {raw!r}")

    if args.apply:
        # index.html mirrors healthcare.html
        if Path('dist_prospects/healthcare.html').exists():
            shutil.copy('dist_prospects/healthcare.html', 'dist_prospects/index.html')
            print("\n✅ Re-mirrored healthcare.html → index.html")
        print("✅ HTML files rewritten.")
    else:
        print("\n(Run with --apply to write these changes.)")


if __name__ == '__main__':
    main()
