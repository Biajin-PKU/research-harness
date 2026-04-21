"""Tests for venue tier lookup and scoring."""

from __future__ import annotations

from research_harness.primitives.venue_tiers import (
    CCFTier,
    CASQuartile,
    VenueTier,
    get_venue_tier,
    meets_tier_threshold,
    normalize_venue_name,
    venue_tier_label,
    venue_tier_score,
)


def test_neurips_is_a_star() -> None:
    tier = get_venue_tier("NeurIPS")
    assert tier.ccf == CCFTier.A_STAR
    assert tier.score == 100


def test_icml_is_a_star() -> None:
    tier = get_venue_tier("ICML")
    assert tier.ccf == CCFTier.A_STAR
    assert tier.score == 100


def test_cvpr_is_ccf_a() -> None:
    tier = get_venue_tier("CVPR")
    assert tier.ccf == CCFTier.A
    assert tier.score == 90


def test_eccv_is_ccf_b() -> None:
    tier = get_venue_tier("ECCV")
    assert tier.ccf == CCFTier.B
    assert tier.score == 70


def test_unknown_venue_returns_empty() -> None:
    tier = get_venue_tier("Unknown Workshop 2024")
    assert tier.ccf == CCFTier.NONE
    assert tier.cas == CASQuartile.NONE
    assert tier.score == 0


def test_tpami_has_ccf_and_cas() -> None:
    tier = get_venue_tier("TPAMI")
    assert tier.ccf == CCFTier.A
    assert tier.cas == CASQuartile.Q1
    assert tier.score == 90


def test_pattern_recognition_cas_q1_boosts() -> None:
    tier = get_venue_tier("Pattern Recognition")
    assert tier.ccf == CCFTier.B
    assert tier.cas == CASQuartile.Q1
    # CAS-Q1 (85) > CCF-B (70), so score = 85
    assert tier.score == 85


def test_normalize_strips_year() -> None:
    assert normalize_venue_name("NeurIPS 2023") == normalize_venue_name("neurips")


def test_normalize_strips_proceedings_prefix() -> None:
    normalized = normalize_venue_name("Proceedings of AAAI")
    assert "aaai" in normalized


def test_normalize_strips_ordinals() -> None:
    normalized = normalize_venue_name("38th AAAI Conference")
    assert "38th" not in normalized
    assert "aaai" in normalized


def test_meets_threshold_ccf_b() -> None:
    assert meets_tier_threshold("NeurIPS", "ccf_b") is True
    assert meets_tier_threshold("CVPR", "ccf_b") is True
    assert meets_tier_threshold("ECCV", "ccf_b") is True


def test_fails_threshold_ccf_a() -> None:
    assert meets_tier_threshold("ECCV", "ccf_a") is False


def test_meets_threshold_cas_q2() -> None:
    assert meets_tier_threshold("TPAMI", "cas_q2") is True
    assert meets_tier_threshold("Neural Networks", "cas_q2") is True


def test_empty_threshold_always_passes() -> None:
    assert meets_tier_threshold("Unknown Workshop", "") is True


def test_venue_tier_score_numeric() -> None:
    assert venue_tier_score("NeurIPS") == 100
    assert venue_tier_score("CVPR") == 90
    assert venue_tier_score("ECCV") == 70
    assert venue_tier_score("Unknown") == 0


def test_venue_tier_label_combined() -> None:
    label = venue_tier_label("TPAMI")
    assert "CCF-A" in label
    assert "CAS-Q1" in label


def test_venue_tier_label_empty_for_unknown() -> None:
    assert venue_tier_label("Unknown Workshop") == ""


def test_full_name_lookup() -> None:
    tier = get_venue_tier("IEEE/CVF Conference on Computer Vision and Pattern Recognition")
    assert tier.ccf == CCFTier.A
    assert tier.score == 90


def test_substring_match_fallback() -> None:
    # "European Conference on Computer Vision" should match ECCV entry
    tier = get_venue_tier("European Conference on Computer Vision")
    assert tier.ccf == CCFTier.B


def test_kdd_is_ccf_a() -> None:
    assert venue_tier_score("KDD") == 90


def test_emnlp_is_ccf_b() -> None:
    assert venue_tier_score("EMNLP") == 70


def test_accv_is_ccf_c() -> None:
    assert venue_tier_score("ACCV") == 40
