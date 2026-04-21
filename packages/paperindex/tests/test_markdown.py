from paperindex import PaperIndexer
from paperindex.indexing.markdown import structure_to_markdown_outline


def test_markdown_outline(sample_pdf):
    result = PaperIndexer().extract_structure(sample_pdf)
    outline = structure_to_markdown_outline(result.tree)
    assert "- Abstract (1-1)" in outline
    assert "- Method (2-2)" in outline
