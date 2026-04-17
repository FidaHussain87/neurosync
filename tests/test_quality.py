"""Tests for quality.py — episode quality scoring."""

from __future__ import annotations

from neurosync.quality import quality_warning, score_episode_quality


class TestQualityScoring:
    def test_causal_language_high(self):
        content = (
            "The setup_private_endpoint_dns lives in ISMR::Storage::Azure because "
            "the DNS zone is storage-account-specific. ExtComm::Network handles "
            "the actual Azure API calls. This approach was chosen instead of putting "
            "it in ISMR::DNS because storage owns the finalization flow."
        )
        score = score_episode_quality(content)
        assert score >= 5

    def test_activity_log_low(self):
        content = "Edited ISMR/Storage/Azure.pm"
        score = score_episode_quality(content)
        assert score <= 2

    def test_reasoning_episode_high(self):
        content = (
            "Chose ISMR::Storage over ISMR::DNS for private DNS zone creation "
            "because the DNS zone is storage-account-specific and part of the "
            "storage finalization flow. This was a trade-off between domain purity "
            "and practical ownership."
        )
        score = score_episode_quality(content)
        assert score >= 5

    def test_short_penalized(self):
        content = "Fixed bug"
        score = score_episode_quality(content)
        assert score <= 2

    def test_verbose_penalized(self):
        content = "x" * 600
        score = score_episode_quality(content)
        # Long content gets +1 for >50, +1 for >200, -1 for >500 = net +1
        # Plus +1 for not being activity log
        assert score <= 3

    def test_file_references_add(self):
        content = "Updated models.py to add causal fields to Episode dataclass"
        score_with_file = score_episode_quality(content)
        content_no_file = "Updated the model to add causal fields to Episode"
        score_without = score_episode_quality(content_no_file)
        assert score_with_file >= score_without

    def test_warning_none_above_threshold(self):
        assert quality_warning(5, threshold=3) is None

    def test_warning_message_below(self):
        msg = quality_warning(1, threshold=3)
        assert msg is not None
        assert "quality score" in msg.lower()
