from __future__ import annotations

from research_harness.pdf_download import (
    PaperDownloadCandidate,
    build_candidate_urls,
    preferred_filename,
)


def test_arxiv_id_generates_pdf_url() -> None:
    candidate = PaperDownloadCandidate(paper_id=1, title="Test", arxiv_id="2302.01523")
    urls = build_candidate_urls(candidate)
    assert "https://arxiv.org/pdf/2302.01523.pdf" in urls


def test_arxiv_abs_url_expands_to_pdf() -> None:
    candidate = PaperDownloadCandidate(
        paper_id=1, title="Test", url="https://arxiv.org/abs/2302.01523"
    )
    urls = build_candidate_urls(candidate)
    assert "https://arxiv.org/pdf/2302.01523.pdf" in urls


def test_ieee_doi_generates_stamp_url() -> None:
    candidate = PaperDownloadCandidate(
        paper_id=20,
        title="IEEE Paper",
        doi="10.1109/SSCI.2017.8285393",
    )
    urls = build_candidate_urls(candidate)
    assert any("stamp.jsp" in url and "arnumber=8285393" in url for url in urls), (
        f"Expected IEEE stamp URL with arnumber=8285393, got: {urls}"
    )


def test_acm_doi_generates_acm_pdf_url() -> None:
    candidate = PaperDownloadCandidate(
        paper_id=13,
        title="KDD Paper",
        doi="10.1145/3637528.3671592",
    )
    urls = build_candidate_urls(candidate)
    assert any("dl.acm.org/doi/pdf" in url for url in urls)


def test_springer_doi_generates_pdf_url() -> None:
    candidate = PaperDownloadCandidate(
        paper_id=21,
        title="Springer Paper",
        doi="10.1007/978-3-030-12345-6_1",
    )
    urls = build_candidate_urls(candidate)
    assert any("link.springer.com/content/pdf" in url for url in urls)


def test_elsevier_doi_generates_sciencedirect_url() -> None:
    candidate = PaperDownloadCandidate(
        paper_id=22,
        title="Elsevier Paper",
        doi="10.1016/j.ejor.2021.08.019",
    )
    urls = build_candidate_urls(candidate)
    assert any("sciencedirect.com" in url for url in urls)


def test_informs_doi_generates_informs_url() -> None:
    candidate = PaperDownloadCandidate(
        paper_id=23,
        title="INFORMS Paper",
        doi="10.1287/isre.2017.0724",
    )
    urls = build_candidate_urls(candidate)
    assert any("pubsonline.informs.org" in url for url in urls)


def test_doi_always_generates_doi_org_redirect() -> None:
    candidate = PaperDownloadCandidate(
        paper_id=24, title="Any Paper", doi="10.9999/test"
    )
    urls = build_candidate_urls(candidate)
    assert any("doi.org/10.9999/test" in url for url in urls)


def test_unpaywall_oa_url_returns_none_on_error(monkeypatch) -> None:
    from research_harness.pdf_download import _unpaywall_oa_url
    import urllib.request
    import urllib.error

    def mock_urlopen(*args, **kwargs):
        raise urllib.error.URLError("mock error")

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)
    assert _unpaywall_oa_url("10.1234/test") is None


def test_scihub_url_disabled_by_default() -> None:
    from research_harness.pdf_download import _scihub_url
    import os

    old = os.environ.pop("SCIHUB_MIRRORS", None)
    try:
        assert _scihub_url("10.1145/12345") is None
    finally:
        if old is not None:
            os.environ["SCIHUB_MIRRORS"] = old


def test_scihub_url_enabled_with_env(monkeypatch) -> None:
    from research_harness.pdf_download import _scihub_url

    monkeypatch.setenv("SCIHUB_MIRRORS", "https://sci-hub.se,https://sci-hub.st")
    result = _scihub_url("10.1145/12345")
    assert result == "https://sci-hub.se/10.1145/12345"


def test_scihub_after_oa_before_publisher(monkeypatch) -> None:
    """Sci-Hub should appear after OA sources but before publisher URLs."""
    monkeypatch.setenv("SCIHUB_MIRRORS", "https://sci-hub.se")
    monkeypatch.setattr(
        "research_harness.pdf_download._unpaywall_oa_url", lambda doi: None
    )

    candidate = PaperDownloadCandidate(
        paper_id=30,
        title="Test Paper",
        doi="10.1145/3637528.3671526",
    )
    urls = build_candidate_urls(candidate)
    scihub_idx = next(i for i, u in enumerate(urls) if "sci-hub" in u)
    acm_idx = next(i for i, u in enumerate(urls) if "dl.acm.org" in u)
    doi_idx = next(i for i, u in enumerate(urls) if "doi.org/10.1145" in u)
    # Sci-Hub before publisher URLs
    assert scihub_idx < acm_idx, (
        f"Sci-Hub ({scihub_idx}) should be before ACM ({acm_idx})"
    )
    assert scihub_idx < doi_idx, (
        f"Sci-Hub ({scihub_idx}) should be before doi.org ({doi_idx})"
    )


def test_extract_scihub_pdf_url() -> None:
    from research_harness.acquisition.downloader import _extract_scihub_pdf_url

    html = b'<html><body><iframe src="//moscow.sci-hub.se/downloads/2021/paper.pdf#view=FitH"></iframe></body></html>'
    result = _extract_scihub_pdf_url(html)
    assert result is not None
    assert result.startswith("https://")
    assert ".pdf" in result


def test_extract_scihub_pdf_url_object_tag() -> None:
    """Current sci-hub.st uses <object data=...> instead of iframe."""
    from research_harness.acquisition.downloader import _extract_scihub_pdf_url

    html = b'<div class="pdf"><object type="application/pdf" data="/storage/2024/7562/abc123/paper.pdf#navpanes=0"></object></div>'
    result = _extract_scihub_pdf_url(html)
    assert result == "/storage/2024/7562/abc123/paper.pdf"


def test_extract_scihub_pdf_url_meta_citation() -> None:
    """Current sci-hub.st also includes citation_pdf_url meta tag."""
    from research_harness.acquisition.downloader import _extract_scihub_pdf_url

    html = (
        b'<meta name="citation_pdf_url" content="/storage/2024/7562/abc/shen2019.pdf">'
    )
    result = _extract_scihub_pdf_url(html)
    assert result == "/storage/2024/7562/abc/shen2019.pdf"


def test_extract_scihub_pdf_url_returns_none_for_no_match() -> None:
    from research_harness.acquisition.downloader import _extract_scihub_pdf_url

    assert _extract_scihub_pdf_url(b"<html><body>no pdf here</body></html>") is None
    assert _extract_scihub_pdf_url(b"") is None


def test_identifier_inference_with_both_arxiv_and_doi(monkeypatch) -> None:
    monkeypatch.setattr(
        "research_harness.pdf_download._unpaywall_oa_url", lambda doi: None
    )
    candidate = PaperDownloadCandidate(
        paper_id=13,
        title="Spending Programmed Bidding",
        venue="KDD 2024",
        doi="10.1145/3637528.3671592",
        arxiv_id="2405.12345",
    )
    urls = build_candidate_urls(candidate)
    assert "https://arxiv.org/pdf/2405.12345.pdf" in urls
    assert "https://dl.acm.org/doi/pdf/10.1145/3637528.3671592" in urls
    assert preferred_filename(candidate).startswith("13_Spending_Programmed_Bidding")


def test_preferred_filename() -> None:
    candidate = PaperDownloadCandidate(paper_id=5, title="Hello World: A Study!")
    assert preferred_filename(candidate) == "5_Hello_World_A_Study.pdf"
