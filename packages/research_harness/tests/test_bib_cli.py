import json

from research_harness.cli import main


def test_bib_set_show_export_with_provenance(runner, tmp_path):
    assert runner.invoke(main, ['topic', 'init', 'demo']).exit_code == 0
    ingest = runner.invoke(main, ['--json', 'paper', 'ingest', '--title', 'Sample Paper', '--topic', 'demo'])
    assert ingest.exit_code == 0
    bibtex = '@inproceedings{sample2026,\n  title={Sample Paper},\n  author={Doe, Jane},\n  booktitle={KDD},\n  year={2026}\n}'
    set_result = runner.invoke(
        main,
        ['--json', 'bib', 'set', '--paper-id', '1', '--key', 'sample2026', '--source', 'dblp', '--verified-by', 'codex', '--bibtex', bibtex],
    )
    assert set_result.exit_code == 0
    payload = json.loads(set_result.output)
    assert payload['source'] == 'dblp'
    assert payload['verified_by'] == 'codex'

    show_result = runner.invoke(main, ['--json', 'bib', 'show', '1'])
    assert show_result.exit_code == 0
    show_payload = json.loads(show_result.output)
    assert show_payload['bibtex_key'] == 'sample2026'
    assert show_payload['source'] == 'dblp'

    output = tmp_path / 'demo.bib'
    export_result = runner.invoke(main, ['bib', 'export', '--topic', 'demo', '--output', str(output)])
    assert export_result.exit_code == 0
    assert output.exists()
    assert 'Sample Paper' in output.read_text()
