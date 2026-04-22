"""Tests for Sprint 4 writing pipeline — writing_checks, latex_compiler, writing primitives."""

from __future__ import annotations

import pytest

from research_harness.execution.writing_checks import (
    AI_BOILERPLATE_PHRASES,
    REVIEW_DIMENSIONS,
    SECTION_WORD_TARGETS,
    WEASEL_WORDS,
    check_ai_boilerplate,
    check_repetition,
    check_section_structure,
    check_weasel_words,
    check_word_count,
    run_all_checks,
)
from research_harness.execution.latex_compiler import (
    TEMPLATES,
    _escape_latex,
    _fix_unicode,
    _section_sort_key,
    assemble_latex,
)


# -- Writing Checks -----------------------------------------------------------


class TestWordCount:
    def test_within_target(self):
        # Introduction target is now 1200-1800
        content = " ".join(["word"] * 1400)  # 1400 words
        result = check_word_count(content, "introduction")
        assert result.passed

    def test_below_target(self):
        content = " ".join(["word"] * 100)  # 100 words, too short for intro
        result = check_word_count(content, "introduction")
        assert not result.passed

    def test_above_target(self):
        content = " ".join(["word"] * 2000)  # 2000 words, too long for intro
        result = check_word_count(content, "introduction")
        assert not result.passed

    def test_custom_target(self):
        content = " ".join(["word"] * 500)
        result = check_word_count(content, "custom_section", target_words=500)
        assert result.passed

    def test_no_target(self):
        content = "any content"
        result = check_word_count(content, "unknown_section_xyz")
        assert result.passed


class TestAIBoilerplate:
    def test_clean_text(self):
        text = (
            "We evaluate our approach on three benchmarks and report accuracy metrics."
        )
        result = check_ai_boilerplate(text)
        assert result.passed

    def test_boilerplate_detected(self):
        text = (
            "In this paper, we propose a novel approach that achieves state-of-the-art results. "
            "Our proposed method leveraging the power of transformers is groundbreaking. "
            "It is worth noting that our paradigm shift paves the way for future research."
        )
        result = check_ai_boilerplate(text)
        assert not result.passed
        assert len(result.items_found) > 3

    def test_few_phrases_ok(self):
        text = "The proposed method achieves good results. In conclusion, we demonstrated improvements."
        result = check_ai_boilerplate(text)
        assert result.passed  # <= 3 phrases allowed


class TestWeaselWords:
    def test_clean_text(self):
        text = "The model achieves 95.2% accuracy on the test set, surpassing the baseline by 3.1 points."
        result = check_weasel_words(text)
        assert result.passed

    def test_hedging_detected(self):
        hedgy = (
            "The results somewhat suggest that perhaps our approach might relatively "
            "improve performance. It seems that the method arguably provides fairly "
            "moderate gains. The improvement appears to be rather marginal."
        )
        result = check_weasel_words(hedgy)
        assert not result.passed
        assert len(result.items_found) > 3


class TestRepetition:
    def test_no_repetition(self):
        text = "First sentence here. Second different sentence. Third unique statement."
        result = check_repetition(text)
        assert result.passed

    def test_repetition_detected(self):
        text = (
            "Our method achieves state of the art results. "
            "The model achieves state of the art performance. "
            "This approach achieves state of the art accuracy. "
            "We show that it achieves state of the art scores."
        )
        result = check_repetition(text)
        assert not result.passed


class TestSectionStructure:
    def test_empty_content(self):
        result = check_section_structure("", "introduction")
        assert not result.passed

    def test_intro_without_citations(self):
        result = check_section_structure(
            "Some text without any citations.", "introduction"
        )
        assert not result.passed

    def test_intro_with_citations(self):
        result = check_section_structure(
            r"Prior work \cite{vaswani2017} showed that transformers are effective.",
            "introduction",
        )
        assert result.passed

    def test_results_no_citations_ok(self):
        result = check_section_structure("Our model achieves 95% accuracy.", "results")
        assert result.passed  # results section doesn't need citations


class TestRunAllChecks:
    def test_returns_all_checks(self):
        content = " ".join(["word"] * 900)
        results = run_all_checks(content, "introduction")
        check_names = {r.check_name for r in results}
        assert "word_count" in check_names
        assert "ai_boilerplate" in check_names
        assert "weasel_words" in check_names
        assert "repetition" in check_names
        assert "section_structure" in check_names


# -- LaTeX Compiler -----------------------------------------------------------


class TestLatexEscape:
    def test_special_chars(self):
        assert _escape_latex("50% accuracy") == r"50\% accuracy"
        assert _escape_latex("A & B") == r"A \& B"
        assert _escape_latex("$100") == r"\$100"


class TestUnicodeFix:
    def test_dashes(self):
        assert _fix_unicode("\u2013") == "--"
        assert _fix_unicode("\u2014") == "---"

    def test_quotes(self):
        assert _fix_unicode("\u201c") == "``"
        assert _fix_unicode("\u201d") == "''"

    def test_greek(self):
        assert _fix_unicode("\u03b1") == r"$\alpha$"

    def test_math(self):
        assert _fix_unicode("\u2264") == r"$\leq$"
        assert _fix_unicode("\u00d7") == r"$\times$"


class TestSectionSortKey:
    def test_known_sections(self):
        assert _section_sort_key("introduction") < _section_sort_key("method")
        assert _section_sort_key("method") < _section_sort_key("experiments")
        assert _section_sort_key("experiments") < _section_sort_key("conclusion")

    def test_unknown_sections(self):
        assert _section_sort_key("custom_thing") == 999


class TestAssembleLatex:
    def test_basic_assembly(self):
        tex, bib = assemble_latex(
            title="Test Paper",
            authors=["Alice", "Bob"],
            abstract="This is a test abstract.",
            sections={
                "introduction": "This is the intro.",
                "method": "This is the method.",
                "conclusion": "This concludes.",
            },
        )
        assert r"\title{Test Paper}" in tex
        assert r"Alice \and Bob" in tex
        assert r"\begin{abstract}" in tex
        assert r"\section{Introduction}" in tex
        assert r"\section{Method}" in tex
        assert r"\section{Conclusion}" in tex
        # Check ordering: intro before method before conclusion
        intro_pos = tex.index("Introduction")
        method_pos = tex.index("Method")
        conclusion_pos = tex.index("Conclusion")
        assert intro_pos < method_pos < conclusion_pos

    def test_empty_sections(self):
        tex, bib = assemble_latex(
            title="Empty",
            authors=[],
            abstract="",
            sections={},
        )
        assert r"\title{Empty}" in tex
        assert "Anonymous" in tex

    def test_bibliography(self):
        bib_entries = [
            "@article{test2024, title={Test}, author={Smith}, year={2024}}",
        ]
        tex, bib = assemble_latex(
            title="T",
            authors=[],
            abstract="",
            sections={},
            bibliography_entries=bib_entries,
        )
        assert "@article{test2024" in bib

    def test_template_selection(self):
        for tmpl_name in TEMPLATES:
            tex, _ = assemble_latex(
                title="T",
                authors=["A"],
                abstract="A",
                sections={},
                template=tmpl_name,
            )
            assert r"\title{T}" in tex or r"\icmltitle{T}" in tex

    def test_unicode_in_content(self):
        tex, _ = assemble_latex(
            title="Test",
            authors=[],
            abstract="Performance \u2264 baseline",
            sections={"results": "Accuracy \u00d7 100"},
        )
        assert r"$\leq$" in tex
        assert r"$\times$" in tex


# -- Writing Primitives (integration) -----------------------------------------


class TestWritingPrimitives:
    def test_outline_generate(self):
        from research_harness.primitives.writing_impls import outline_generate

        result = outline_generate(topic_id=1, project_id=1)
        assert len(result.sections) == 7
        assert result.total_target_words > 0
        assert result.sections[0].section == "introduction"

    def test_section_review_clean(self):
        from research_harness.primitives.writing_impls import section_review

        content = " ".join(["word"] * 900)
        result = section_review(section="introduction", content=content)
        assert len(result.deterministic_checks) == 9
        assert len(result.dimensions) == 10

    def test_section_review_fails_on_boilerplate(self):
        from research_harness.primitives.writing_impls import section_review

        boilerplate = (
            "In this paper, we propose a novel approach. The proposed method "
            "achieves state-of-the-art results. It is worth noting that our "
            "groundbreaking paradigm shift leveraging the power of transformers "
            "paves the way for future work. " * 100
        )
        result = section_review(section="introduction", content=boilerplate)
        assert result.needs_revision
        boilerplate_check = [
            c for c in result.deterministic_checks if c.check_name == "ai_boilerplate"
        ][0]
        assert not boilerplate_check.passed

    def test_section_revise_stub(self):
        from research_harness.primitives.writing_impls import section_revise

        result = section_revise(
            section="introduction",
            content="Original content.",
            review_feedback="Improve clarity.",
        )
        assert result.section == "introduction"
        assert result.word_count > 0

    def test_latex_compile_basic(self, tmp_path):
        from research_harness.primitives.writing_impls import latex_compile

        _result = latex_compile(
            topic_id=1,
            output_dir=str(tmp_path / "output"),
            template="generic",
            sections={
                "introduction": "This is the introduction.",
                "method": "This is the method.",
                "conclusion": "This is the conclusion.",
            },
            title="Test Paper",
            authors=["Alice"],
            abstract="Test abstract.",
        )
        # Even if pdflatex is not installed, the tex file should be written
        tex_file = tmp_path / "output" / "paper.tex"
        assert tex_file.exists()
        tex_content = tex_file.read_text()
        assert r"\title{Test Paper}" in tex_content
        assert r"\section{Introduction}" in tex_content

    def test_latex_compile_with_bib(self, tmp_path):
        from research_harness.primitives.writing_impls import latex_compile

        _result = latex_compile(
            topic_id=1,
            output_dir=str(tmp_path / "output"),
            sections={"introduction": "See \\cite{test2024}."},
            title="T",
            bibliography_entries=[
                "@article{test2024, title={Test}, author={Smith}, year={2024}}"
            ],
        )
        bib_file = tmp_path / "output" / "references.bib"
        assert bib_file.exists()
        assert "@article{test2024" in bib_file.read_text()


# -- Constants sanity checks ---------------------------------------------------


class TestConstants:
    def test_review_dimensions_count(self):
        assert len(REVIEW_DIMENSIONS) == 10

    def test_ai_boilerplate_count(self):
        assert len(AI_BOILERPLATE_PHRASES) >= 75

    def test_weasel_words_count(self):
        assert len(WEASEL_WORDS) >= 30

    def test_section_targets_present(self):
        for section in ["abstract", "introduction", "conclusion"]:
            assert section in SECTION_WORD_TARGETS

    def test_templates_present(self):
        for tmpl in ["neurips", "icml", "iclr", "acl", "generic"]:
            assert tmpl in TEMPLATES


# -- Pre-compilation Validation Gate -------------------------------------------


class TestValidateBeforeCompile:
    """Tests for _validate_before_compile in latex_compiler."""

    def setup_method(self):
        from research_harness.execution.latex_compiler import _validate_before_compile

        self._validate = _validate_before_compile

    def test_clean_document_passes(self):
        tex = r"""\documentclass{article}
\begin{document}
This is clean text with \cite{ref1}.
\end{document}"""
        bib = "@article{ref1, title={T}, author={A}, year={2024}}"
        findings = self._validate(tex, bib)
        errors = [f for f in findings if f.level == "error"]
        assert len(errors) == 0

    def test_missing_cite_key_flagged(self):
        tex = r"""\documentclass{article}
\begin{document}
See \cite{ref1} and \cite{ref_missing}.
\end{document}"""
        bib = "@article{ref1, title={T}, author={A}, year={2024}}"
        findings = self._validate(tex, bib)
        errors = [
            f for f in findings if f.level == "error" and f.category == "cite_missing"
        ]
        assert len(errors) == 1
        assert "ref_missing" in errors[0].message

    def test_multiple_cite_keys_in_one_cite(self):
        tex = r"""\documentclass{article}
\begin{document}
See \cite{ref1, ref2, ref3}.
\end{document}"""
        bib = "@article{ref1, title={T}, author={A}, year={2024}}\n@article{ref2, title={T2}, author={B}, year={2024}}"
        findings = self._validate(tex, bib)
        errors = [
            f for f in findings if f.level == "error" and f.category == "cite_missing"
        ]
        assert len(errors) == 1
        assert "ref3" in errors[0].message

    def test_placeholder_todo_flagged(self):
        tex = r"""\documentclass{article}
\begin{document}
Results show TODO improvement.
\end{document}"""
        findings = self._validate(tex, "")
        warnings = [f for f in findings if f.category == "placeholder"]
        assert len(warnings) >= 1

    def test_placeholder_x_percent_flagged(self):
        tex = r"""\documentclass{article}
\begin{document}
We achieve X\% improvement over baselines.
\end{document}"""
        findings = self._validate(tex, "")
        warnings = [f for f in findings if f.category == "placeholder"]
        assert len(warnings) >= 1

    def test_real_percentage_not_flagged(self):
        tex = r"""\documentclass{article}
\begin{document}
We achieve 4.5\% improvement over baselines.
\end{document}"""
        findings = self._validate(tex, "")
        placeholders = [f for f in findings if f.category == "placeholder"]
        assert len(placeholders) == 0

    def test_unmatched_begin_end(self):
        tex = r"""\documentclass{article}
\begin{document}
\begin{table}
content
\end{figure}
\end{document}"""
        findings = self._validate(tex, "")
        errors = [f for f in findings if f.category == "env_mismatch"]
        assert len(errors) >= 1

    def test_unclosed_environment(self):
        tex = r"""\documentclass{article}
\begin{document}
\begin{itemize}
\item one
\end{document}"""
        findings = self._validate(tex, "")
        errors = [f for f in findings if f.category == "env_mismatch"]
        assert len(errors) >= 1
        assert "itemize" in errors[0].message

    def test_comments_ignored(self):
        tex = r"""\documentclass{article}
\begin{document}
% TODO this is a comment
Real content here.
\end{document}"""
        findings = self._validate(tex, "")
        placeholders = [f for f in findings if f.category == "placeholder"]
        assert len(placeholders) == 0

    def test_outside_document_not_scanned_for_placeholders(self):
        tex = r"""\documentclass{article}
% TODO preamble comment
\begin{document}
Clean content.
\end{document}"""
        findings = self._validate(tex, "")
        placeholders = [f for f in findings if f.category == "placeholder"]
        assert len(placeholders) == 0

    def test_citep_and_citet_checked(self):
        tex = r"""\documentclass{article}
\begin{document}
\citet{ref1} show that \citep{ref_bad} agrees.
\end{document}"""
        bib = "@article{ref1, title={T}, author={A}, year={2024}}"
        findings = self._validate(tex, bib)
        errors = [
            f for f in findings if f.level == "error" and f.category == "cite_missing"
        ]
        assert len(errors) == 1
        assert "ref_bad" in errors[0].message


# -- Post-draft citation audit -------------------------------------------------


class TestAuditDraftCitations:
    """Tests for _audit_draft_citations in llm_primitives."""

    def setup_method(self):
        from research_harness.execution.llm_primitives import _audit_draft_citations

        self._audit = _audit_draft_citations

    def test_valid_citations_no_warnings(self):
        content = "We follow [1] and extend [3] using techniques from [2]."
        warnings = self._audit(content, evidence_count=5)
        assert len(warnings) == 0

    def test_out_of_range_flagged(self):
        content = "Prior work [1] shows that [32] outperforms [5]."
        warnings = self._audit(content, evidence_count=10)
        assert len(warnings) == 1
        assert "[32]" in warnings[0]

    def test_zero_index_flagged(self):
        content = "See [0] for details."
        warnings = self._audit(content, evidence_count=5)
        assert len(warnings) == 1

    def test_empty_content_no_crash(self):
        assert self._audit("", evidence_count=10) == []

    def test_zero_evidence_count_no_audit(self):
        assert self._audit("[99] is cited.", evidence_count=0) == []


# -- Writing lesson helpers ----------------------------------------------------


class TestWritingLessonHelpers:
    """Tests for _load_writing_lessons and _record_writing_lessons_from_draft."""

    def test_load_writing_lessons_returns_empty_without_db(self):
        from research_harness.execution.llm_primitives import _load_writing_lessons

        result = _load_writing_lessons(None, topic_id=1)
        assert result == ""

    def test_record_writing_lessons_no_crash_without_db(self):
        from research_harness.execution.llm_primitives import (
            _record_writing_lessons_from_draft,
        )

        _record_writing_lessons_from_draft(
            None,
            topic_id=1,
            section="intro",
            content="test",
            audit_warnings=[],
            target_words=0,
        )

    def test_record_with_audit_warnings_no_crash_without_db(self):
        from research_harness.execution.llm_primitives import (
            _record_writing_lessons_from_draft,
        )

        _record_writing_lessons_from_draft(
            None,
            topic_id=1,
            section="intro",
            content="test content",
            audit_warnings=["[99] out of range"],
            target_words=0,
        )


# -- Venue Writing Profiles (Sprint 4) -----------------------------------------


class TestVenueWritingProfiles:
    """Tests for venue writing profile persistence and cache."""

    @pytest.fixture
    def db(self, tmp_path):
        from research_harness.storage.db import Database

        db = Database(tmp_path / "test.db")
        db.migrate()
        return db

    def test_persist_and_load(self, db):
        from research_harness.execution.llm_primitives import (
            _persist_venue_profiles,
            _load_cached_venue_profiles,
            WritingPattern,
        )

        patterns = [
            WritingPattern(
                dimension="abstract_hook",
                pattern="empirical gap",
                example="",
                source_paper="",
            ),
            WritingPattern(
                dimension="exp_analysis",
                pattern="paired comparison",
                example="",
                source_paper="",
            ),
        ]
        _persist_venue_profiles(db, "NeurIPS", patterns, 5)

        cached = _load_cached_venue_profiles(db, "NeurIPS")
        assert cached is not None
        assert cached.venue == "NeurIPS"
        assert cached.exemplar_count == 5
        assert len(cached.patterns) == 2
        assert cached.model_used == "cache"

    def test_no_cache_for_unknown_venue(self, db):
        from research_harness.execution.llm_primitives import (
            _load_cached_venue_profiles,
        )

        assert _load_cached_venue_profiles(db, "UNKNOWN_VENUE") is None

    def test_upsert_overwrites(self, db):
        from research_harness.execution.llm_primitives import (
            _persist_venue_profiles,
            _load_cached_venue_profiles,
            WritingPattern,
        )

        p1 = [
            WritingPattern(dimension="hook", pattern="old", example="", source_paper="")
        ]
        _persist_venue_profiles(db, "KDD", p1, 3)

        p2 = [
            WritingPattern(dimension="hook", pattern="new", example="", source_paper="")
        ]
        _persist_venue_profiles(db, "KDD", p2, 8)

        cached = _load_cached_venue_profiles(db, "KDD")
        assert cached is not None
        assert cached.patterns[0].pattern == "new"
        assert cached.exemplar_count == 8

    def test_venue_guidance(self, db):
        from research_harness.execution.llm_primitives import (
            _persist_venue_profiles,
            WritingPattern,
        )
        from research_harness.evolution.writing_skill import WritingSkillAggregator

        patterns = [
            WritingPattern(
                dimension="abstract_hook",
                pattern="state gap then solve",
                example="",
                source_paper="",
            ),
        ]
        _persist_venue_profiles(db, "ICML", patterns, 4)

        agg = WritingSkillAggregator(db)
        guidance = agg.get_venue_guidance("ICML")
        assert "ICML" in guidance
        assert "abstract_hook" in guidance
        assert "state gap then solve" in guidance

    def test_venue_guidance_empty(self, db):
        from research_harness.evolution.writing_skill import WritingSkillAggregator

        agg = WritingSkillAggregator(db)
        assert agg.get_venue_guidance("NONEXISTENT") == ""


class TestOutlineGenerateContribGuard:
    """outline_generate must refuse to run with empty contributions to avoid hallucination."""

    @pytest.fixture
    def db(self, tmp_path):
        from research_harness.storage.db import Database

        db = Database(tmp_path / "test.db")
        db.migrate()
        return db

    def test_refuses_without_contributions(self, db):
        from research_harness.execution.llm_primitives import outline_generate

        with pytest.raises(ValueError, match="requires paper contributions"):
            outline_generate(db=db, topic_id=1, project_id=1, contributions="")

    def test_refuses_with_whitespace_only_contributions(self, db):
        from research_harness.execution.llm_primitives import outline_generate

        with pytest.raises(ValueError, match="requires paper contributions"):
            outline_generate(db=db, topic_id=1, project_id=1, contributions="   \n  ")
