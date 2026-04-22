from __future__ import annotations

import http.client
import urllib.error
from io import BytesIO
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest

from research_harness.paper_source_clients import (
    SemanticScholarProvider,
    _fetch_with_retry,
    _parse_retry_after,
)
from research_harness.paper_sources import SearchQuery


def test_semantic_scholar_provider_uses_supported_fields_and_maps_external_ids() -> (
    None
):
    captured: dict[str, str] = {}

    def fetcher(url: str, headers: dict[str, str]):
        del headers
        captured["url"] = url
        return {
            "data": [
                {
                    "paperId": "paper-123",
                    "title": "Attention Is All You Need",
                    "authors": [{"name": "Ashish Vaswani"}],
                    "year": 2017,
                    "venue": "NeurIPS",
                    "abstract": "transformers",
                    "externalIds": {"DOI": "10.5555/test", "ArXiv": "1706.03762"},
                    "url": "https://www.semanticscholar.org/paper/paper-123",
                    "citationCount": 42,
                    "openAccessPdf": {"url": "https://arxiv.org/pdf/1706.03762.pdf"},
                }
            ]
        }

    provider = SemanticScholarProvider(api_key="test-key", fetcher=fetcher)
    results = provider.search(SearchQuery(query="attention", limit=1))

    fields = parse_qs(urlparse(captured["url"]).query)["fields"][0].split(",")
    assert "doi" not in fields
    assert "paperId" in fields

    assert len(results) == 1
    result = results[0]
    assert result.doi == "10.5555/test"
    assert result.arxiv_id == "1706.03762"
    assert result.s2_id == "paper-123"
    assert result.pdf_candidates[0].url == "https://arxiv.org/pdf/1706.03762.pdf"


class TestFetchWithRetry:
    @patch("research_harness.paper_source_clients.urllib.request.urlopen")
    def test_success_on_first_try(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response(b"hello")
        result = _fetch_with_retry(
            "https://example.com",
            {},
            lambda data: data.decode("utf-8"),
            max_retries=0,
            base_backoff=0,
        )
        assert result == "hello"
        assert mock_urlopen.call_count == 1

    @patch("research_harness.paper_source_clients.urllib.request.urlopen")
    @patch("research_harness.paper_source_clients.time.sleep")
    def test_retries_on_429(self, mock_sleep, mock_urlopen):
        # First call: 429, second call: success
        resp_ok = BytesIO(b'{"ok": true}')
        resp_ok.read = resp_ok.read
        mock_urlopen.side_effect = [
            urllib.error.HTTPError(
                "http://x", 429, "rate limited", http.client.HTTPMessage(), BytesIO(b"")
            ),
            _mock_response(b'{"ok": true}'),
        ]

        result = _fetch_with_retry(
            "http://x",
            {},
            lambda d: d.decode(),
            max_retries=2,
            base_backoff=0.01,
        )
        assert result == '{"ok": true}'
        assert mock_sleep.call_count == 1

    @patch("research_harness.paper_source_clients.urllib.request.urlopen")
    def test_raises_on_non_retryable_http_error(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "http://x",
            404,
            "not found",
            http.client.HTTPMessage(),
            BytesIO(b""),
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            _fetch_with_retry(
                "http://x", {}, lambda d: d, max_retries=2, base_backoff=0.01
            )
        assert exc_info.value.code == 404

    @patch("research_harness.paper_source_clients.urllib.request.urlopen")
    @patch("research_harness.paper_source_clients.time.sleep")
    def test_raises_after_max_retries(self, mock_sleep, mock_urlopen):
        mock_urlopen.side_effect = [
            urllib.error.HTTPError(
                "http://x", 503, "unavailable", http.client.HTTPMessage(), BytesIO(b"")
            )
            for _ in range(4)
        ]
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            _fetch_with_retry(
                "http://x", {}, lambda d: d, max_retries=3, base_backoff=0.01
            )
        assert exc_info.value.code == 503
        assert mock_sleep.call_count == 3

    @patch("research_harness.paper_source_clients.urllib.request.urlopen")
    @patch("research_harness.paper_source_clients.time.sleep")
    def test_post_request_with_data(self, mock_sleep, mock_urlopen):
        mock_urlopen.return_value = _mock_response(b'{"result": "ok"}')
        result = _fetch_with_retry(
            "http://x",
            {"Content-Type": "application/json"},
            lambda d: d.decode(),
            data=b'{"q": "test"}',
            method="POST",
        )
        assert result == '{"result": "ok"}'
        req = mock_urlopen.call_args[0][0]
        assert req.data == b'{"q": "test"}'
        assert req.method == "POST"


class TestParseRetryAfter:
    def test_numeric_retry_after(self):
        exc = _make_http_error(429, retry_after="5")
        assert _parse_retry_after(exc, 1.0) == 5.0

    def test_missing_retry_after_returns_default(self):
        exc = _make_http_error(429)
        assert _parse_retry_after(exc, 2.5) == 2.5

    def test_invalid_retry_after_returns_default(self):
        exc = _make_http_error(429, retry_after="Wed, 21 Oct 2025 07:28:00 GMT")
        assert _parse_retry_after(exc, 3.0) == 3.0

    def test_zero_retry_after_clamps_to_minimum(self):
        exc = _make_http_error(429, retry_after="0")
        assert _parse_retry_after(exc, 1.0) == 0.5


def _mock_response(data: bytes):
    """Create a mock HTTP response context manager."""

    class _Resp:
        def read(self):
            return data

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    return _Resp()


def _make_http_error(
    code: int, retry_after: str | None = None
) -> urllib.error.HTTPError:
    headers = http.client.HTTPMessage()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError("http://x", code, "error", headers, BytesIO(b""))


# ---------------------------------------------------------------------------
# OpenAlex resolve_doi
# ---------------------------------------------------------------------------


class TestOpenAlexResolveDoi:
    def test_resolve_doi_returns_id(self):
        from research_harness.paper_source_clients import OpenAlexProvider

        oa = OpenAlexProvider()

        def fake_fetch(url, headers):
            return {"id": "https://openalex.org/W1234567"}

        with patch.object(oa, "_fetch_json", side_effect=fake_fetch):
            result = oa.resolve_doi("10.1234/test")
        assert result == "W1234567"

    def test_resolve_doi_strips_prefix(self):
        from research_harness.paper_source_clients import OpenAlexProvider

        oa = OpenAlexProvider()

        captured = {}

        def fake_fetch(url, headers):
            captured["url"] = url
            return {"id": "https://openalex.org/W999"}

        with patch.object(oa, "_fetch_json", side_effect=fake_fetch):
            result = oa.resolve_doi("https://doi.org/10.1234/test")
        assert result == "W999"
        assert "doi:10.1234/test" in captured["url"]

    def test_resolve_doi_returns_none_on_error(self):
        from research_harness.paper_source_clients import OpenAlexProvider

        oa = OpenAlexProvider()

        with patch.object(oa, "_fetch_json", side_effect=Exception("network")):
            assert oa.resolve_doi("10.1234/broken") is None

    def test_resolve_doi_returns_none_for_empty(self):
        from research_harness.paper_source_clients import OpenAlexProvider

        oa = OpenAlexProvider()
        assert oa.resolve_doi("") is None
