from __future__ import annotations

from research_harness.paper_source_clients import ArxivProvider
from research_harness.paper_sources import SearchQuery


ARXIV_FEED = """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns='http://www.w3.org/2005/Atom' xmlns:arxiv='http://arxiv.org/schemas/atom'>
  <entry>
    <id>http://arxiv.org/abs/1706.03762v7</id>
    <updated>2017-12-01T00:00:00Z</updated>
    <published>2017-06-12T17:57:12Z</published>
    <title> Attention is All you Need </title>
    <summary> Transformer paper </summary>
    <author><name>Ashish Vaswani</name></author>
    <author><name>Noam Shazeer</name></author>
    <arxiv:doi>10.48550/arXiv.1706.03762</arxiv:doi>
    <link href='http://arxiv.org/abs/1706.03762v7' rel='alternate' type='text/html' />
    <link title='pdf' href='http://arxiv.org/pdf/1706.03762v7' rel='related' type='application/pdf' />
  </entry>
</feed>
"""


def test_arxiv_provider_parses_atom_feed() -> None:
    provider = ArxivProvider(fetcher=lambda url, headers: ARXIV_FEED)
    results = provider.search(SearchQuery(query="attention", limit=1))

    assert len(results) == 1
    result = results[0]
    assert result.title == "Attention is All you Need"
    assert result.arxiv_id == "1706.03762v7"
    assert result.doi == "10.48550/arXiv.1706.03762"
    assert result.authors == ["Ashish Vaswani", "Noam Shazeer"]
    assert result.pdf_candidates[0].url == "http://arxiv.org/pdf/1706.03762v7"
