"""Tests for starter_packs.py."""

from __future__ import annotations

from neurosync.starter_pack_loader import list_packs, load_starter_pack


class TestStarterPacks:
    def test_list_packs(self):
        packs = list_packs()
        assert "python_developer" in packs
        assert "perl_developer" in packs
        assert "cloud_infra" in packs
        assert "web_fullstack" in packs

    def test_load_unknown_pack(self, semantic):
        result = load_starter_pack("nonexistent", semantic)
        assert "error" in result

    def test_load_python_developer_pack(self, semantic):
        result = load_starter_pack("python_developer", semantic)
        assert result["theories_created"] > 0
        assert result["pack"] == "python_developer"
        # Verify theories were actually created
        theories = semantic.list_theories()
        assert len(theories) > 0

    def test_load_perl_developer_pack(self, semantic):
        result = load_starter_pack("perl_developer", semantic)
        assert result["theories_created"] > 0

    def test_duplicate_detection(self, semantic):
        result1 = load_starter_pack("python_developer", semantic)
        created_first = result1["theories_created"]
        result2 = load_starter_pack("python_developer", semantic)
        # Second load should skip most/all (detected as duplicates)
        assert result2["theories_skipped"] >= created_first - 1  # Allow 1 margin
