"""
Tests for idempotency.py — IdempotencyManifest
===============================================
Covers: hashing, is_new, mark_seen, filter_new, persistence, corruption recovery.
"""
import json
import pytest
from idempotency import IdempotencyManifest


class TestHashing:
    """Tests for deterministic hash generation."""

    def test_same_input_same_hash(self):
        h1 = IdempotencyManifest._hash('Org A', 'https://example.com')
        h2 = IdempotencyManifest._hash('Org A', 'https://example.com')
        assert h1 == h2

    def test_case_insensitive(self):
        h1 = IdempotencyManifest._hash('Org A', 'https://EXAMPLE.COM')
        h2 = IdempotencyManifest._hash('org a', 'https://example.com')
        assert h1 == h2

    def test_whitespace_trimmed(self):
        h1 = IdempotencyManifest._hash('  Org A  ', '  https://example.com  ')
        h2 = IdempotencyManifest._hash('Org A', 'https://example.com')
        assert h1 == h2

    def test_different_orgs_different_hash(self):
        h1 = IdempotencyManifest._hash('Org A', 'https://example.com')
        h2 = IdempotencyManifest._hash('Org B', 'https://example.com')
        assert h1 != h2

    def test_hash_length(self):
        h = IdempotencyManifest._hash('Test', 'https://test.com')
        assert len(h) == 16


class TestIsNewAndMarkSeen:
    """Tests for is_new and mark_seen."""

    def test_new_prospect_is_new(self, tmp_path):
        m = IdempotencyManifest(str(tmp_path / 'manifest.json'))
        assert m.is_new('New Org', 'https://new.com') is True

    def test_seen_prospect_not_new(self, tmp_path):
        m = IdempotencyManifest(str(tmp_path / 'manifest.json'))
        m.mark_seen('Org X', 'https://x.com', score=80)
        assert m.is_new('Org X', 'https://x.com') is False

    def test_count_increments(self, tmp_path):
        m = IdempotencyManifest(str(tmp_path / 'manifest.json'))
        assert m.count == 0
        m.mark_seen('A', 'https://a.com')
        assert m.count == 1
        m.mark_seen('B', 'https://b.com')
        assert m.count == 2

    def test_double_mark_no_duplicate(self, tmp_path):
        m = IdempotencyManifest(str(tmp_path / 'manifest.json'))
        m.mark_seen('A', 'https://a.com')
        m.mark_seen('A', 'https://a.com')
        assert m.count == 1


class TestFilterNew:
    """Tests for filter_new batch operation."""

    def test_all_new(self, tmp_path):
        m = IdempotencyManifest(str(tmp_path / 'manifest.json'))
        prospects = [
            {'organization': 'A', 'source_url': 'https://a.com', 'qualification_score': 70},
            {'organization': 'B', 'source_url': 'https://b.com', 'qualification_score': 80},
        ]
        result = m.filter_new(prospects)
        assert len(result) == 2

    def test_filters_duplicates(self, tmp_path):
        m = IdempotencyManifest(str(tmp_path / 'manifest.json'))
        m.mark_seen('A', 'https://a.com')
        prospects = [
            {'organization': 'A', 'source_url': 'https://a.com'},
            {'organization': 'B', 'source_url': 'https://b.com'},
        ]
        result = m.filter_new(prospects)
        assert len(result) == 1
        assert result[0]['organization'] == 'B'

    def test_marks_returned_as_seen(self, tmp_path):
        m = IdempotencyManifest(str(tmp_path / 'manifest.json'))
        prospects = [{'organization': 'X', 'source_url': 'https://x.com'}]
        m.filter_new(prospects)
        assert m.is_new('X', 'https://x.com') is False

    def test_empty_list(self, tmp_path):
        m = IdempotencyManifest(str(tmp_path / 'manifest.json'))
        assert m.filter_new([]) == []


class TestPersistence:
    """Tests for disk persistence and corruption recovery."""

    def test_persists_across_instances(self, tmp_path):
        path = str(tmp_path / 'manifest.json')
        m1 = IdempotencyManifest(path)
        m1.mark_seen('Persistent', 'https://p.com')

        m2 = IdempotencyManifest(path)
        assert m2.is_new('Persistent', 'https://p.com') is False
        assert m2.count == 1

    def test_recovers_from_corrupted_file(self, tmp_path):
        path = tmp_path / 'manifest.json'
        path.write_text('NOT VALID JSON {{{{')
        m = IdempotencyManifest(str(path))
        assert m.count == 0  # Fresh start, no crash

    def test_handles_missing_file(self, tmp_path):
        m = IdempotencyManifest(str(tmp_path / 'doesnt_exist.json'))
        assert m.count == 0
