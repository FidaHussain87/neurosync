"""Tests for the Self-Learning Memory Layer (Layer 9)."""

from __future__ import annotations

import os
import shutil
import tempfile

import pytest

from neurosync.config import NeuroSyncConfig
from neurosync.db import Database


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp(prefix="ns_selflearn_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def config(tmp_dir):
    return NeuroSyncConfig(
        data_dir=tmp_dir,
        sqlite_path=os.path.join(tmp_dir, "test.sqlite3"),
        chroma_path=os.path.join(tmp_dir, "chroma"),
    )


@pytest.fixture
def db(config):
    database = Database(config)
    yield database
    database.close()


# ---------------------------------------------------------------------------
# TestSchemaV11
# ---------------------------------------------------------------------------


class TestSchemaV11:
    def test_recall_log_table_exists(self, db):
        conn = db._get_conn()
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='recall_log'"
        ).fetchone()
        assert row is not None

    def test_memory_usefulness_table_exists(self, db):
        conn = db._get_conn()
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_usefulness'"
        ).fetchone()
        assert row is not None

    def test_distilled_knowledge_table_exists(self, db):
        conn = db._get_conn()
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='distilled_knowledge'"
        ).fetchone()
        assert row is not None

    def test_schema_version_is_11(self, db):
        from neurosync.db import CURRENT_SCHEMA_VERSION
        assert CURRENT_SCHEMA_VERSION == 11
        conn = db._get_conn()
        v = conn.execute("SELECT version FROM schema_version").fetchone()[0]
        assert v == 11


# ---------------------------------------------------------------------------
# TestRecallLogCRUD
# ---------------------------------------------------------------------------


class TestRecallLogCRUD:
    def _insert(self, db, recall_id="r1", session_id="s1"):
        db.insert_recall_log(
            recall_id=recall_id,
            session_id=session_id,
            recalled_at="2026-01-01T10:00:00",
            context_hash="abc123",
            theory_ids=["t1", "t2"],
            episode_ids=["e1"],
            tokens_used=120,
        )

    def test_insert_recall_log(self, db):
        self._insert(db)
        row = db.get_recall_log("r1")
        assert row is not None
        assert row["session_id"] == "s1"
        assert row["outcome"] == "pending"
        assert row["correction_count"] == 0

    def test_update_recall_log_outcome(self, db):
        self._insert(db)
        db.update_recall_log_outcome("r1", "clean", 0, "2026-01-01T11:00:00")
        row = db.get_recall_log("r1")
        assert row["outcome"] == "clean"
        assert row["outcome_at"] == "2026-01-01T11:00:00"

    def test_increment_recall_log_corrections(self, db):
        self._insert(db)
        db.increment_recall_log_corrections("r1")
        db.increment_recall_log_corrections("r1")
        row = db.get_recall_log("r1")
        assert row["correction_count"] == 2

    def test_get_recall_log_by_session(self, db):
        self._insert(db, "r1", "s1")
        self._insert(db, "r2", "s1")
        self._insert(db, "r3", "s99")
        rows = db.get_recall_log_by_session("s1")
        assert len(rows) == 2
        assert all(r["session_id"] == "s1" for r in rows)

    def test_get_recall_log_missing(self, db):
        assert db.get_recall_log("nonexistent") is None


# ---------------------------------------------------------------------------
# TestUsefulnessCRUD
# ---------------------------------------------------------------------------


class TestUsefulnessCRUD:
    def test_upsert_and_get(self, db):
        db.upsert_usefulness(
            entity_id="t1",
            entity_type="theory",
            alpha=2.0,
            beta=1.0,
            recall_count=5,
            last_recalled="2026-01-01T00:00:00",
            last_outcome="clean",
            score=2.0 / 3.0,
            now="2026-01-01T00:00:00",
        )
        row = db.get_usefulness("t1", "theory")
        assert row is not None
        assert row["alpha"] == pytest.approx(2.0)
        assert row["recall_count"] == 5
        assert row["last_outcome"] == "clean"

    def test_upsert_updates_existing(self, db):
        db.upsert_usefulness("t1", "theory", 1.0, 1.0, 1, "2026-01-01T00:00:00", "", 0.5, "2026-01-01T00:00:00")
        db.upsert_usefulness("t1", "theory", 3.0, 1.0, 2, "2026-01-01T01:00:00", "clean", 0.75, "2026-01-01T01:00:00")
        row = db.get_usefulness("t1", "theory")
        assert row["alpha"] == pytest.approx(3.0)
        assert row["recall_count"] == 2

    def test_get_missing_returns_none(self, db):
        assert db.get_usefulness("ghost", "theory") is None

    def test_bulk_update(self, db):
        records = [
            {"entity_id": f"t{i}", "entity_type": "theory", "alpha": 1.0, "beta": 1.0,
             "recall_count": i, "last_recalled": "2026-01-01T00:00:00", "last_outcome": "",
             "score": 0.5, "now": "2026-01-01T00:00:00"}
            for i in range(5)
        ]
        db.bulk_update_usefulness(records)
        for i in range(5):
            row = db.get_usefulness(f"t{i}", "theory")
            assert row is not None
            assert row["recall_count"] == i

    def test_list_low_usefulness(self, db):
        db.upsert_usefulness("low", "theory", 1.0, 9.0, 15, "2026-01-01T00:00:00", "corrected", 0.1, "2026-01-01T00:00:00")
        db.upsert_usefulness("high", "theory", 9.0, 1.0, 15, "2026-01-01T00:00:00", "clean", 0.9, "2026-01-01T00:00:00")
        db.upsert_usefulness("few", "theory", 1.0, 9.0, 3, "2026-01-01T00:00:00", "corrected", 0.1, "2026-01-01T00:00:00")
        rows = db.list_low_usefulness(entity_type="theory", max_score=0.2, min_recall_count=10)
        ids = [r["entity_id"] for r in rows]
        assert "low" in ids
        assert "high" not in ids
        assert "few" not in ids  # recall_count < 10

    def test_list_usefulness_for_entities(self, db):
        db.upsert_usefulness("t1", "theory", 2.0, 1.0, 5, "2026-01-01T00:00:00", "clean", 0.67, "2026-01-01T00:00:00")
        db.upsert_usefulness("t2", "theory", 1.0, 2.0, 3, "2026-01-01T00:00:00", "mixed", 0.33, "2026-01-01T00:00:00")
        result = db.list_usefulness_for_entities(["t1", "t2", "t99"], "theory")
        assert "t1" in result
        assert "t2" in result
        assert "t99" not in result


# ---------------------------------------------------------------------------
# TestDistilledKnowledgeCRUD
# ---------------------------------------------------------------------------


class TestDistilledKnowledgeCRUD:
    def test_insert_distilled(self, db):
        db.insert_distilled(
            distilled_id="d1",
            source_theory_id="theory_a",
            distilled_content="Never throw exceptions. Return Result<T,E>.",
            original_tokens=200,
            distilled_tokens=12,
            compression_ratio=0.94,
            similarity_score=0.85,
            distilled_at="2026-01-01T00:00:00",
        )
        row = db.get_distilled_for_theory("theory_a")
        assert row is not None
        assert "Never throw" in row["distilled_content"]
        assert row["active"] == 1

    def test_insert_deactivates_previous(self, db):
        db.insert_distilled("d1", "theory_a", "Old content.", 100, 10, 0.9, 0.8, "2026-01-01T00:00:00")
        db.insert_distilled("d2", "theory_a", "New content.", 100, 8, 0.92, 0.88, "2026-01-01T01:00:00")
        active = db.get_distilled_for_theory("theory_a")
        assert active["id"] == "d2"
        # Old one should be inactive
        conn = db._get_conn()
        old = conn.execute("SELECT active FROM distilled_knowledge WHERE id = 'd1'").fetchone()
        assert old["active"] == 0

    def test_list_active_distilled(self, db):
        db.insert_distilled("d1", "th1", "Content A.", 100, 10, 0.9, 0.8, "2026-01-01T00:00:00")
        db.insert_distilled("d2", "th2", "Content B.", 150, 12, 0.92, 0.85, "2026-01-01T01:00:00")
        rows = db.list_active_distilled()
        ids = [r["id"] for r in rows]
        assert "d1" in ids
        assert "d2" in ids

    def test_increment_distilled_recall(self, db):
        db.insert_distilled("d1", "th1", "Content.", 100, 10, 0.9, 0.8, "2026-01-01T00:00:00")
        db.increment_distilled_recall("d1", positive=True)
        db.increment_distilled_recall("d1", positive=False)
        conn = db._get_conn()
        row = conn.execute("SELECT recall_count, positive_count FROM distilled_knowledge WHERE id='d1'").fetchone()
        assert row["recall_count"] == 2
        assert row["positive_count"] == 1


# ---------------------------------------------------------------------------
# TestUsefulnessScorer
# ---------------------------------------------------------------------------


class TestUsefulnessScorer:
    def test_get_returns_default_for_new_entity(self, db):
        from neurosync.selflearn.usefulness import UsefulnessScorer
        scorer = UsefulnessScorer(db)
        rec = scorer.get("new_entity", "theory")
        assert rec.alpha == pytest.approx(1.0)
        assert rec.beta == pytest.approx(1.0)
        assert rec.score == pytest.approx(0.5)

    def test_reward_increases_alpha(self, db):
        from neurosync.selflearn.usefulness import UsefulnessRecord
        rec = UsefulnessRecord("t1", "theory")
        rec.reward(1.0)
        assert rec.alpha == pytest.approx(2.0)
        assert rec.score == pytest.approx(2.0 / 3.0)

    def test_penalize_increases_beta(self, db):
        from neurosync.selflearn.usefulness import UsefulnessRecord
        rec = UsefulnessRecord("t1", "theory")
        rec.penalize(0.6)
        assert rec.beta == pytest.approx(1.6)
        assert rec.score == pytest.approx(1.0 / 2.6)

    def test_on_recall_increments_count(self, db):
        from neurosync.selflearn.usefulness import UsefulnessScorer
        scorer = UsefulnessScorer(db)
        scorer.on_recall(["t1", "t2"], "theory")
        row1 = db.get_usefulness("t1", "theory")
        row2 = db.get_usefulness("t2", "theory")
        assert row1["recall_count"] == 1
        assert row2["recall_count"] == 1

    def test_on_correction_increases_beta(self, db):
        from neurosync.selflearn.usefulness import UsefulnessScorer
        scorer = UsefulnessScorer(db)
        scorer.on_recall(["t1"], "theory")
        scorer.on_correction(["t1"], "theory")
        row = db.get_usefulness("t1", "theory")
        # beta should be > 1.0 (started at 1.0, correction added 0.6)
        assert row["beta"] > 1.0
        assert row["score"] < 0.5  # penalised

    def test_on_session_end_clean_rewards(self, db):
        from neurosync.selflearn.usefulness import UsefulnessScorer
        scorer = UsefulnessScorer(db)
        scorer.on_recall(["t1"], "theory")
        scorer.on_session_end(["t1"], "theory", outcome="clean", correction_count=0)
        row = db.get_usefulness("t1", "theory")
        # alpha should have been incremented (clean reward)
        assert row["alpha"] > 1.0
        assert row["last_outcome"] == "clean"

    def test_on_session_end_corrected_penalises(self, db):
        from neurosync.selflearn.usefulness import UsefulnessScorer
        scorer = UsefulnessScorer(db)
        scorer.on_recall(["t1"], "theory")
        scorer.on_session_end(["t1"], "theory", outcome="corrected", correction_count=2)
        row = db.get_usefulness("t1", "theory")
        assert row["beta"] > 1.0
        assert row["last_outcome"] == "corrected"

    def test_thompson_sample_within_bounds(self, db):
        from neurosync.selflearn.usefulness import UsefulnessRecord
        rec = UsefulnessRecord("t1", "theory", alpha=5.0, beta=2.0)
        for _ in range(20):
            s = rec.thompson_sample()
            assert 0.0 <= s <= 1.0

    def test_get_bulk_mixed_known_and_unknown(self, db):
        from neurosync.selflearn.usefulness import UsefulnessScorer
        scorer = UsefulnessScorer(db)
        scorer.on_recall(["t1"], "theory")
        result = scorer.get_bulk(["t1", "t_unknown"], "theory")
        assert "t1" in result
        assert "t_unknown" in result
        assert result["t_unknown"].score == pytest.approx(0.5)  # default prior


# ---------------------------------------------------------------------------
# TestOutcomeTracker
# ---------------------------------------------------------------------------


class TestOutcomeTracker:
    def test_on_recall_creates_log_entry(self, db):
        from neurosync.selflearn.outcome_tracker import OutcomeTracker
        tracker = OutcomeTracker(db)
        rid = tracker.on_recall("s1", ["t1"], ["e1"], 100)
        row = db.get_recall_log(rid)
        assert row is not None
        assert row["outcome"] == "pending"
        assert row["tokens_used"] == 100

    def test_on_correction_increments_count(self, db):
        from neurosync.selflearn.outcome_tracker import OutcomeTracker
        tracker = OutcomeTracker(db)
        rid = tracker.on_recall("s1", ["t1"], [], 50)
        tracker.on_correction("s1")
        tracker.on_correction("s1")
        row = db.get_recall_log(rid)
        assert row["correction_count"] == 2

    def test_on_session_end_clean_outcome(self, db):
        from neurosync.selflearn.outcome_tracker import OutcomeTracker
        tracker = OutcomeTracker(db)
        rid = tracker.on_recall("s1", ["t1"], [], 80)
        finalised = tracker.on_session_end("s1")
        assert len(finalised) == 1
        assert finalised[0].correction_count == 0
        row = db.get_recall_log(rid)
        assert row["outcome"] == "clean"

    def test_on_session_end_corrected_outcome(self, db):
        from neurosync.selflearn.outcome_tracker import OutcomeTracker
        tracker = OutcomeTracker(db)
        rid = tracker.on_recall("s1", ["t1"], [], 80)
        for _ in range(4):
            tracker.on_correction("s1")
        tracker.on_session_end("s1")
        row = db.get_recall_log(rid)
        assert row["outcome"] == "corrected"
        assert row["correction_count"] == 4

    def test_on_session_end_mixed_outcome(self, db):
        from neurosync.selflearn.outcome_tracker import OutcomeTracker
        tracker = OutcomeTracker(db)
        rid = tracker.on_recall("s1", ["t1"], [], 80)
        tracker.on_correction("s1")
        tracker.on_correction("s1")
        tracker.on_session_end("s1")
        row = db.get_recall_log(rid)
        assert row["outcome"] == "mixed"

    def test_multiple_sessions_isolated(self, db):
        from neurosync.selflearn.outcome_tracker import OutcomeTracker
        tracker = OutcomeTracker(db)
        r1 = tracker.on_recall("s1", ["t1"], [], 80)
        r2 = tracker.on_recall("s2", ["t2"], [], 80)
        tracker.on_correction("s1")
        tracker.on_session_end("s1")
        tracker.on_session_end("s2")
        assert db.get_recall_log(r1)["outcome"] == "mixed"
        assert db.get_recall_log(r2)["outcome"] == "clean"

    def test_get_session_correction_count(self, db):
        from neurosync.selflearn.outcome_tracker import OutcomeTracker
        tracker = OutcomeTracker(db)
        tracker.on_recall("s1", ["t1"], [], 80)
        assert tracker.get_session_correction_count("s1") == 0
        tracker.on_correction("s1")
        assert tracker.get_session_correction_count("s1") == 1

    def test_get_active_theory_ids(self, db):
        from neurosync.selflearn.outcome_tracker import OutcomeTracker
        tracker = OutcomeTracker(db)
        tracker.on_recall("s1", ["t1", "t2"], [], 80)
        ids = tracker.get_active_theory_ids("s1")
        assert "t1" in ids
        assert "t2" in ids

    def test_session_cleared_after_end(self, db):
        from neurosync.selflearn.outcome_tracker import OutcomeTracker
        tracker = OutcomeTracker(db)
        tracker.on_recall("s1", ["t1"], [], 80)
        tracker.on_session_end("s1")
        # No more active recalls for this session
        assert tracker.get_session_correction_count("s1") == 0
        assert tracker.get_active_theory_ids("s1") == []


# ---------------------------------------------------------------------------
# TestReranker
# ---------------------------------------------------------------------------


class TestReranker:
    def _make_candidates(self, n=5):
        return [
            {
                "id": f"t{i}",
                "relevance": (n - i) / n,
                "tokens": 50 + i * 10,
                "content": f"Theory {i} content here.",
                "metadata": {},
            }
            for i in range(n)
        ]

    def test_rerank_returns_ranked_items(self, db):
        from neurosync.selflearn.reranker import Reranker
        from neurosync.selflearn.usefulness import UsefulnessScorer
        scorer = UsefulnessScorer(db)
        reranker = Reranker(scorer)
        candidates = self._make_candidates(5)
        result = reranker.rerank(candidates, entity_type="theory")
        assert len(result) == 5
        # All should be ranked items
        from neurosync.selflearn.reranker import RankedItem
        assert all(isinstance(r, RankedItem) for r in result)

    def test_combined_score_in_range(self, db):
        from neurosync.selflearn.reranker import Reranker
        from neurosync.selflearn.usefulness import UsefulnessScorer
        scorer = UsefulnessScorer(db)
        reranker = Reranker(scorer)
        result = reranker.rerank(self._make_candidates(3))
        for item in result:
            assert 0.0 <= item.combined_score <= 1.0

    def test_low_usefulness_filtered_after_observations(self, db):
        from neurosync.selflearn.reranker import Reranker
        from neurosync.selflearn.usefulness import UsefulnessScorer
        scorer = UsefulnessScorer(db)
        # Create a very low-usefulness score with ≥5 observations
        db.upsert_usefulness("bad_theory", "theory", 1.0, 50.0, 10, "2026-01-01T00:00:00", "corrected", 0.02, "2026-01-01T00:00:00")
        candidates = [{"id": "bad_theory", "relevance": 0.9, "tokens": 50, "content": "X", "metadata": {}}]
        result = Reranker(scorer).rerank(candidates)
        # Should be filtered out (score 0.02 < MIN_USEFULNESS=0.15 and recall_count=10 ≥ 5)
        assert len(result) == 0

    def test_new_entity_not_filtered(self, db):
        from neurosync.selflearn.reranker import Reranker
        from neurosync.selflearn.usefulness import UsefulnessScorer
        scorer = UsefulnessScorer(db)
        # New entity with 0 observations — should NOT be filtered even with low score
        candidates = [{"id": "new_t", "relevance": 0.7, "tokens": 50, "content": "New theory.", "metadata": {}}]
        result = Reranker(scorer).rerank(candidates)
        assert len(result) == 1

    def test_value_density(self, db):
        from neurosync.selflearn.reranker import RankedItem
        item = RankedItem(
            entity_id="t1", entity_type="theory",
            relevance=0.8, usefulness_score=0.9,
            thompson_sample=0.85, tokens=100,
            content="X", metadata={},
        )
        expected_density = item.combined_score / 100
        assert item.value_density == pytest.approx(expected_density)

    def test_empty_candidates_returns_empty(self, db):
        from neurosync.selflearn.reranker import Reranker
        from neurosync.selflearn.usefulness import UsefulnessScorer
        scorer = UsefulnessScorer(db)
        assert Reranker(scorer).rerank([]) == []


# ---------------------------------------------------------------------------
# TestBudgetPacker
# ---------------------------------------------------------------------------


class TestBudgetPacker:
    def _make_ranked(self, items_spec):
        from neurosync.selflearn.reranker import RankedItem
        return [
            RankedItem(
                entity_id=f"t{i}",
                entity_type="theory",
                relevance=spec["relevance"],
                usefulness_score=spec["usefulness"],
                thompson_sample=0.5,
                tokens=spec["tokens"],
                content=f"Content for t{i}",
                metadata={},
            )
            for i, spec in enumerate(items_spec)
        ]

    def test_fits_within_budget(self, db):
        from neurosync.selflearn.budget_packer import BudgetPacker
        packer = BudgetPacker()
        ranked = self._make_ranked([
            {"relevance": 0.9, "usefulness": 0.9, "tokens": 100},
            {"relevance": 0.8, "usefulness": 0.8, "tokens": 200},
            {"relevance": 0.7, "usefulness": 0.7, "tokens": 300},
        ])
        result = packer.pack(ranked, budget=250)
        assert result.total_tokens <= 250

    def test_selects_highest_density_items(self, db):
        from neurosync.selflearn.budget_packer import BudgetPacker
        packer = BudgetPacker()
        # t0: high value density (0.8 combined / 50 tokens = 0.016)
        # t1: low value density (0.5 combined / 500 tokens = 0.001)
        ranked = self._make_ranked([
            {"relevance": 1.0, "usefulness": 1.0, "tokens": 50},  # high density
            {"relevance": 0.5, "usefulness": 0.5, "tokens": 500},  # low density
        ])
        result = packer.pack(ranked, budget=200)
        ids = [item.entity_id for item in result.items]
        assert "t0" in ids  # high density should be selected
        assert "t1" not in ids  # doesn't fit (500 > 200 - 50 = 150)

    def test_must_include_bypasses_budget_check(self, db):
        from neurosync.selflearn.budget_packer import BudgetPacker
        packer = BudgetPacker()
        ranked = self._make_ranked([
            {"relevance": 0.5, "usefulness": 0.5, "tokens": 400},
        ])
        result = packer.pack(ranked, budget=100, must_include=["t0"])
        ids = [item.entity_id for item in result.items]
        assert "t0" in ids  # must_include overrides budget

    def test_empty_input_returns_empty_result(self, db):
        from neurosync.selflearn.budget_packer import BudgetPacker, PackedResult
        packer = BudgetPacker()
        result = packer.pack([], budget=500)
        assert isinstance(result, PackedResult)
        assert result.items == []
        assert result.total_tokens == 0

    def test_utilization_computed(self, db):
        from neurosync.selflearn.budget_packer import BudgetPacker
        packer = BudgetPacker()
        ranked = self._make_ranked([
            {"relevance": 0.9, "usefulness": 0.9, "tokens": 100},
        ])
        result = packer.pack(ranked, budget=500)
        assert result.utilization == pytest.approx(100 / 500)

    def test_pack_raw_dict_items(self, db):
        from neurosync.selflearn.budget_packer import BudgetPacker
        packer = BudgetPacker()
        items = [
            {"id": "a", "combined_score": 0.9, "tokens": 80},
            {"id": "b", "combined_score": 0.5, "tokens": 500},
        ]
        result = packer.pack_raw(items, budget=200)
        ids = [r["id"] for r in result]
        assert "a" in ids
        assert "b" not in ids


# ---------------------------------------------------------------------------
# TestDistiller
# ---------------------------------------------------------------------------


class TestDistiller:
    _VERBOSE = (
        "When writing API endpoints, always validate input at the boundary before "
        "processing. Never trust user-supplied data. Use typed request models to "
        "enforce constraints. Return consistent error responses. Avoid silent failures — "
        "raise or return explicit error states so callers know what went wrong. "
        "This pattern prevents injection attacks and simplifies debugging because "
        "validation errors are surfaced immediately rather than propagating deep into "
        "the call stack where they're harder to trace. Always use structured logging "
        "with request IDs so correlating errors across services is straightforward."
    )

    def test_distill_verbose_theory(self, db):
        from neurosync.selflearn.distiller import Distiller
        distiller = Distiller(db)
        result = distiller.distill_theory("t_verbose", self._VERBOSE)
        assert result is not None
        assert result["distilled_tokens"] < result["original_tokens"]
        assert result["compression_ratio"] > 0

    def test_short_content_returns_none(self, db):
        from neurosync.selflearn.distiller import Distiller
        distiller = Distiller(db)
        result = distiller.distill_theory("t_short", "Always validate input.")
        assert result is None  # too short to need distillation

    def test_distilled_content_stored_in_db(self, db):
        from neurosync.selflearn.distiller import Distiller
        distiller = Distiller(db)
        distiller.distill_theory("t_store", self._VERBOSE)
        row = db.get_distilled_for_theory("t_store")
        assert row is not None
        assert row["active"] == 1
        assert len(row["distilled_content"]) > 0

    def test_get_or_distill_returns_distilled(self, db):
        from neurosync.selflearn.distiller import Distiller
        distiller = Distiller(db)
        content = distiller.get_or_distill("t_getord", self._VERBOSE)
        # Should return distilled version (shorter than original)
        assert len(content) <= len(self._VERBOSE)

    def test_get_or_distill_returns_original_if_short(self, db):
        from neurosync.selflearn.distiller import Distiller
        distiller = Distiller(db)
        short = "Always use UTC timestamps."
        result = distiller.get_or_distill("t_short2", short)
        assert result == short

    def test_extract_imperatives_finds_never_always(self):
        from neurosync.selflearn.distiller import _extract_imperatives
        text = "Always use UTC timestamps in all storage. Never store passwords in plaintext."
        imperatives = _extract_imperatives(text)
        assert len(imperatives) >= 1
        combined = " ".join(imperatives)
        assert "UTC" in combined or "Never" in combined or "Always" in combined

    def test_jaccard_similarity(self):
        from neurosync.selflearn.distiller import _jaccard_similarity
        a = "always validate user input before processing"
        b = "validate input before processing"
        sim = _jaccard_similarity(a, b)
        assert sim > 0.5  # high overlap

        low_sim = _jaccard_similarity("cats and dogs", "quantum physics research")
        assert low_sim < 0.2


# ---------------------------------------------------------------------------
# TestPruner
# ---------------------------------------------------------------------------


class TestPruner:
    def _create_theory(self, db, theory_id, contradiction_count=2, confirmation_count=0):
        """Helper: insert a theory row directly for pruner testing."""
        conn = db._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO theories
               (id, content, confidence, active, contradiction_count,
                confirmation_count, scope, first_observed, last_confirmed)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (theory_id, f"Theory {theory_id} content here and more text to make it real.",
             0.3, 1, contradiction_count, confirmation_count,
             "craft", "2026-01-01T00:00:00", "2026-01-01T00:00:00")
        )
        conn.commit()

    def test_finds_low_usefulness_candidates(self, db):
        from neurosync.selflearn.pruner import Pruner
        self._create_theory(db, "bad_theory", contradiction_count=2, confirmation_count=0)
        db.upsert_usefulness(
            "bad_theory", "theory", 1.0, 15.0, 15,
            "2026-01-01T00:00:00", "corrected", 0.06, "2026-01-01T00:00:00"
        )
        pruner = Pruner(db)
        candidates = pruner.find_candidates()
        ids = [c.entity_id for c in candidates]
        assert "bad_theory" in ids

    def test_high_usefulness_not_flagged(self, db):
        from neurosync.selflearn.pruner import Pruner
        self._create_theory(db, "good_theory", contradiction_count=1, confirmation_count=0)
        db.upsert_usefulness(
            "good_theory", "theory", 8.0, 2.0, 15,
            "2026-01-01T00:00:00", "clean", 0.8, "2026-01-01T00:00:00"
        )
        pruner = Pruner(db)
        candidates = pruner.find_candidates()
        ids = [c.entity_id for c in candidates]
        assert "good_theory" not in ids

    def test_insufficient_recall_not_flagged(self, db):
        from neurosync.selflearn.pruner import Pruner
        self._create_theory(db, "new_theory", contradiction_count=2, confirmation_count=0)
        db.upsert_usefulness(
            "new_theory", "theory", 1.0, 9.0, 3,  # only 3 recalls
            "2026-01-01T00:00:00", "corrected", 0.1, "2026-01-01T00:00:00"
        )
        pruner = Pruner(db)
        candidates = pruner.find_candidates()
        ids = [c.entity_id for c in candidates]
        assert "new_theory" not in ids

    def test_build_prune_insights_format(self, db):
        from neurosync.selflearn.pruner import Pruner
        self._create_theory(db, "prune_me", contradiction_count=2, confirmation_count=0)
        db.upsert_usefulness(
            "prune_me", "theory", 1.0, 15.0, 15,
            "2026-01-01T00:00:00", "corrected", 0.06, "2026-01-01T00:00:00"
        )
        pruner = Pruner(db)
        insights = pruner.build_prune_insights()
        assert len(insights) >= 1
        insight = insights[0]
        assert "id" in insight
        assert insight["insight_type"] == "self_learning"
        assert insight["category"] == "retirement_candidate"
        assert "prune_me" in insight["content"]


# ---------------------------------------------------------------------------
# TestSelfLearningLayer
# ---------------------------------------------------------------------------


class TestSelfLearningLayer:
    def test_init(self, db):
        from neurosync.selflearn import SelfLearningLayer
        layer = SelfLearningLayer(db)
        assert layer is not None

    def test_on_recall_records_log(self, db):
        from neurosync.selflearn import SelfLearningLayer
        layer = SelfLearningLayer(db)
        rid = layer.on_recall("s1", ["t1", "t2"], ["e1"], 150, context="test")
        assert rid is not None
        row = db.get_recall_log(rid)
        assert row is not None
        assert row["session_id"] == "s1"

    def test_on_correction_penalises_theories(self, db):
        from neurosync.selflearn import SelfLearningLayer
        layer = SelfLearningLayer(db)
        layer.on_recall("s1", ["t1"], [], 80)
        layer.on_correction("s1")
        row = db.get_usefulness("t1", "theory")
        # beta should have increased from correction
        assert row is not None
        assert row["beta"] > 1.0

    def test_on_session_end_clean(self, db):
        from neurosync.selflearn import SelfLearningLayer
        layer = SelfLearningLayer(db)
        layer.on_recall("s1", ["t1"], [], 80)
        summary = layer.on_session_end("s1")
        assert summary["outcome"] == "clean"
        assert summary["total_corrections"] == 0

    def test_on_session_end_corrected(self, db):
        from neurosync.selflearn import SelfLearningLayer
        layer = SelfLearningLayer(db)
        layer.on_recall("s1", ["t1"], [], 80)
        layer.on_correction("s1")
        layer.on_correction("s1")
        layer.on_correction("s1")
        summary = layer.on_session_end("s1")
        assert summary["outcome"] == "corrected"
        assert summary["total_corrections"] == 3

    def test_on_session_end_mixed(self, db):
        from neurosync.selflearn import SelfLearningLayer
        layer = SelfLearningLayer(db)
        layer.on_recall("s1", ["t1"], [], 80)
        layer.on_correction("s1")
        summary = layer.on_session_end("s1")
        assert summary["outcome"] == "mixed"

    def test_get_ranked_theories_returns_list(self, db):
        from neurosync.selflearn import SelfLearningLayer
        layer = SelfLearningLayer(db)
        theories = [
            {"id": "t1", "content": "Always validate input before processing. Never trust user data. Return explicit errors.", "relevance": 0.9, "metadata": {}},
            {"id": "t2", "content": "Use UTC timestamps everywhere. Avoid local time.", "relevance": 0.7, "metadata": {}},
        ]
        result = layer.get_ranked_theories(theories, token_budget=500)
        assert isinstance(result, list)

    def test_get_ranked_theories_empty(self, db):
        from neurosync.selflearn import SelfLearningLayer
        layer = SelfLearningLayer(db)
        assert layer.get_ranked_theories([]) == []

    def test_session_isolation(self, db):
        from neurosync.selflearn import SelfLearningLayer
        layer = SelfLearningLayer(db)
        layer.on_recall("sA", ["t1"], [], 80)
        layer.on_recall("sB", ["t2"], [], 80)
        layer.on_correction("sA")
        sumA = layer.on_session_end("sA")
        sumB = layer.on_session_end("sB")
        assert sumA["outcome"] == "mixed"
        assert sumB["outcome"] == "clean"
