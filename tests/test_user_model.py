"""Tests for user_model.py — topic familiarity tracking."""

from __future__ import annotations


class TestUserModel:
    def test_initial_familiarity(self, user_model):
        assert user_model.get_familiarity("unknown_topic") == 0.0

    def test_record_exposure(self, user_model):
        uk = user_model.record_exposure("pytest", project="neurosync")
        assert uk.times_seen == 1
        assert uk.familiarity > 0.0

    def test_exposure_increases_familiarity(self, user_model):
        user_model.record_exposure("pytest")
        f1 = user_model.get_familiarity("pytest")
        user_model.record_exposure("pytest")
        f2 = user_model.get_familiarity("pytest")
        assert f2 > f1

    def test_explained_grows_faster(self, user_model):
        user_model.record_exposure("topic_a", explained=False)
        f_seen = user_model.get_familiarity("topic_a")
        user_model.record_exposure("topic_b", explained=True)
        f_explained = user_model.get_familiarity("topic_b")
        assert f_explained > f_seen

    def test_get_familiar_topics(self, user_model):
        # Build up familiarity
        for _ in range(20):
            user_model.record_exposure("well_known", explained=True)
        user_model.record_exposure("new_topic")
        familiar = user_model.get_familiar_topics(threshold=0.9)
        assert "well_known" in familiar
        assert "new_topic" not in familiar

    def test_should_explain(self, user_model):
        assert user_model.should_explain("new_topic") is True
        for _ in range(20):
            user_model.record_exposure("old_topic", explained=True)
        assert user_model.should_explain("old_topic") is False

    def test_list_knowledge(self, user_model):
        user_model.record_exposure("a")
        user_model.record_exposure("b")
        knowledge = user_model.list_knowledge()
        assert len(knowledge) == 2
