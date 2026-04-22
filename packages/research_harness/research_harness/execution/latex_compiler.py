"""LaTeX compiler — assemble and compile papers with conference templates.

Supports: NeurIPS, ICML, ICLR, ACL, EMNLP templates.
Features: BibTeX assembly from paper pool, pdflatex 3-pass, auto-fix
(escape special chars, missing packages, Unicode fallback).
"""

from __future__ import annotations

import json as _json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# -- Author field parsing -----------------------------------------------------


def parse_authors_field(raw: str | None) -> list[str]:
    """Parse the ``papers.authors`` DB field into a clean list of author names.

    The field appears in four formats across the pool:
    - ``'[]'`` or ``None`` or ``''`` — empty
    - ``'""'`` — empty (artifact from some ingest paths)
    - ``'["A", "B", ...]'`` — clean JSON array
    - ``'"[\\"A\\", \\"B\\", ...]"'`` — JSON-string-wrapped JSON array
    - ``'A; B; C'`` — legacy semicolon-separated
    """
    if not raw or raw in ("[]", '""', "null", '""'):
        return []

    text = raw.strip()

    # Unwrap outer JSON string quotes: '"[...]"' → '[...]'
    if text.startswith('"') and text.endswith('"'):
        try:
            text = _json.loads(text)
            if isinstance(text, str):
                text = text.strip()
        except (ValueError, TypeError):
            pass

    # Try JSON array
    if isinstance(text, str) and text.startswith("["):
        try:
            parsed = _json.loads(text)
            if isinstance(parsed, list):
                return [str(a).strip() for a in parsed if str(a).strip()]
        except (ValueError, TypeError):
            pass

    # Semicolon-separated fallback
    if isinstance(text, str) and ";" in text:
        return [a.strip() for a in text.split(";") if a.strip()]

    # Single author
    if isinstance(text, str) and text.strip():
        return [text.strip()]

    return []


def authors_to_bibtex(raw: str | None) -> str:
    """Convert DB authors field to BibTeX ``author`` value (``A and B and C``)."""
    names = parse_authors_field(raw)
    return " and ".join(names) if names else "Anonymous"


# -- Conference templates ------------------------------------------------------

TEMPLATES: dict[str, str] = {
    "neurips": r"""\documentclass{article}
\usepackage[preprint]{neurips_2024}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{hyperref}
\usepackage{url}
\usepackage{booktabs}
\usepackage{amsfonts}
\usepackage{amsmath}
\usepackage{nicefrac}
\usepackage{microtype}
\usepackage{graphicx}
\usepackage{natbib}

\title{%(title)s}
\author{%(authors)s}

\begin{document}
\maketitle

%(abstract_block)s

%(body)s

\bibliographystyle{plainnat}
\bibliography{references}

\end{document}
""",
    "icml": r"""\documentclass[accepted]{icml2024}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{hyperref}
\usepackage{url}
\usepackage{booktabs}
\usepackage{amsfonts}
\usepackage{amsmath}
\usepackage{graphicx}
\usepackage{natbib}

\icmltitlerunning{%(title)s}

\begin{document}
\twocolumn[
\icmltitle{%(title)s}
\icmlsetsymbol{equal}{*}
\begin{icmlauthorlist}
%(icml_authors)s
\end{icmlauthorlist}
]

%(abstract_block)s

%(body)s

\bibliography{references}
\bibliographystyle{icml2024}

\end{document}
""",
    "iclr": r"""\documentclass{article}
\usepackage{iclr2025_conference}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{hyperref}
\usepackage{url}
\usepackage{booktabs}
\usepackage{amsfonts}
\usepackage{amsmath}
\usepackage{graphicx}
\usepackage{natbib}

\title{%(title)s}
\author{%(authors)s}

\begin{document}
\maketitle

%(abstract_block)s

%(body)s

\bibliography{references}
\bibliographystyle{iclrnatbib}

\end{document}
""",
    "acl": r"""\documentclass[11pt]{article}
\usepackage{acl}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{hyperref}
\usepackage{url}
\usepackage{booktabs}
\usepackage{amsfonts}
\usepackage{amsmath}
\usepackage{graphicx}
\usepackage{natbib}

\title{%(title)s}
\author{%(authors)s}

\begin{document}
\maketitle

%(abstract_block)s

%(body)s

\bibliography{references}
\bibliographystyle{acl_natbib}

\end{document}
""",
    # Generic fallback — works without any special .sty files
    "generic": r"""\documentclass[11pt,a4paper]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage[margin=1in]{geometry}
\usepackage{hyperref}
\usepackage{url}
\usepackage{booktabs}
\usepackage{amsfonts}
\usepackage{amsmath}
\usepackage{graphicx}
\usepackage{natbib}

\title{%(title)s}
\author{%(authors)s}

\begin{document}
\maketitle

%(abstract_block)s

%(body)s

\bibliographystyle{plainnat}
\bibliography{references}

\end{document}
""",
    # arXiv preprint style — single column, generous margins, no external .sty
    # This is the recommended default since draft papers typically go to arXiv first.
    "arxiv": r"""\documentclass[11pt]{article}
\usepackage[margin=1in]{geometry}
\usepackage{times}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{hyperref}
\usepackage{url}
\usepackage{booktabs}
\usepackage{amsfonts}
\usepackage{amsmath}
\usepackage{amssymb}
\usepackage{nicefrac}
\usepackage{microtype}
\usepackage{graphicx}
\usepackage{multirow}
\usepackage{xcolor}
\usepackage{colortbl}
\usepackage{natbib}
\usepackage{float}
\usepackage[normalem]{ulem}

\title{%(title)s}
\author{%(authors)s}
\date{}

\begin{document}
\maketitle

%(abstract_block)s

%(body)s

\bibliographystyle{plainnat}
\bibliography{references}

\end{document}
""",
}

# Section ordering for paper assembly
SECTION_ORDER = [
    "introduction",
    "related_work",
    "related work",
    "background",
    "preliminaries",
    "method",
    "methodology",
    "approach",
    "experiments",
    "experiment",
    "experimental_setup",
    "results",
    "main_results",
    "ablation",
    "ablation_study",
    "analysis",
    "discussion",
    "limitations",
    "conclusion",
    "conclusions",
    "acknowledgments",
    "appendix",
]


@dataclass
class ValidationFinding:
    """A single finding from pre-compilation validation."""

    level: str  # "error" or "warning"
    category: str  # "cite_missing", "placeholder", "env_mismatch", "figure_missing"
    message: str
    line_number: int = 0


@dataclass
class CompileResult:
    """Result of LaTeX compilation."""

    success: bool = False
    pdf_path: str = ""
    log_summary: str = ""
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    pages: int = 0
    auto_fixes: list[str] = field(default_factory=list)
    validation_findings: list[ValidationFinding] = field(default_factory=list)


def _escape_latex(text: str) -> str:
    """Escape special LaTeX characters in plain text."""
    replacements = [
        ("&", r"\&"),
        ("%", r"\%"),
        ("$", r"\$"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("{", r"\{"),
        ("}", r"\}"),
        ("~", r"\textasciitilde{}"),
        ("^", r"\textasciicircum{}"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def _fix_unicode(text: str) -> str:
    """Replace common Unicode characters with LaTeX equivalents."""
    replacements = [
        ("\u2013", "--"),  # en-dash
        ("\u2014", "---"),  # em-dash
        ("\u2018", "`"),  # left single quote
        ("\u2019", "'"),  # right single quote
        ("\u201c", "``"),  # left double quote
        ("\u201d", "''"),  # right double quote
        ("\u2026", r"\ldots"),  # ellipsis
        ("\u00e9", r"\'e"),  # é
        ("\u00e8", r"\`e"),  # è
        ("\u00fc", r"\"u"),  # ü
        ("\u00f6", r"\"o"),  # ö
        ("\u00e4", r"\"a"),  # ä
        ("\u03b1", r"$\alpha$"),
        ("\u03b2", r"$\beta$"),
        ("\u03b3", r"$\gamma$"),
        ("\u03b4", r"$\delta$"),
        ("\u2264", r"$\leq$"),
        ("\u2265", r"$\geq$"),
        ("\u00d7", r"$\times$"),
        ("\u2192", r"$\rightarrow$"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def _section_sort_key(section_name: str) -> int:
    """Return sort index for a section name."""
    lower = section_name.lower().strip()
    try:
        return SECTION_ORDER.index(lower)
    except ValueError:
        return 999  # unknown sections go to the end


def _format_authors_latex(authors: list[str], template: str) -> str:
    """Format author list for the given template."""
    if not authors:
        return "Anonymous"

    if template == "icml":
        # ICML uses \icmlauthor format
        lines = []
        for a in authors:
            lines.append(f"\\icmlauthor{{{a}}}{{aff1}}")
        return "\n".join(lines)

    return " \\and ".join(authors)


def _strip_leading_section_header(content: str, sec_name: str) -> str:
    """Remove a leading ``\\section{...}`` and ``\\label{...}`` if already present.

    LLM-generated drafts sometimes include their own section header; since
    ``assemble_latex`` always prepends one, the duplicate must be removed.
    Also strips plain-text headers like ``Section 3 Method: ...`` or ``3.1 Problem Formulation``.
    """
    stripped = content.lstrip()

    # Remove leading \section{...} (possibly with \label{...} on the next line)
    m = re.match(
        r"\\section\*?\{[^}]*\}\s*(?:\\label\{[^}]*\}\s*)?",
        stripped,
    )
    if m:
        stripped = stripped[m.end() :].lstrip()

    # Remove plain-text headers like "Section 3 Method: ..." at the very start
    m = re.match(
        r"Section\s+\d+[\s.:]+[^\n]*\n",
        stripped,
        re.IGNORECASE,
    )
    if m:
        stripped = stripped[m.end() :].lstrip()

    return stripped


def assemble_latex(
    title: str,
    authors: list[str],
    abstract: str,
    sections: dict[str, str],
    bibliography_entries: list[str] | None = None,
    template: str = "generic",
) -> tuple[str, str]:
    """Assemble LaTeX document from sections.

    Returns (tex_content, bib_content) tuple.
    """
    tmpl = TEMPLATES.get(template, TEMPLATES["generic"])

    # Sort sections
    sorted_sections = sorted(sections.items(), key=lambda x: _section_sort_key(x[0]))

    # Build body
    body_parts: list[str] = []
    for sec_name, content in sorted_sections:
        display_name = sec_name.replace("_", " ").title()
        content = _fix_unicode(content)
        content = _strip_leading_section_header(content, sec_name)
        body_parts.append(
            f"\\section{{{display_name}}}\n\\label{{sec:{sec_name.lower().replace(' ', '_')}}}\n\n{content}\n"
        )

    body = "\n".join(body_parts)

    # Abstract block
    abstract_block = ""
    if abstract:
        abstract = _fix_unicode(abstract)
        abstract_block = f"\\begin{{abstract}}\n{abstract}\n\\end{{abstract}}\n"

    # Format authors
    authors_str = _format_authors_latex(authors, template)
    icml_authors = _format_authors_latex(authors, "icml") if template == "icml" else ""

    tex = tmpl % {
        "title": _fix_unicode(title) if title else "Untitled",
        "authors": authors_str,
        "icml_authors": icml_authors,
        "abstract_block": abstract_block,
        "body": body,
    }

    # Build bibliography
    bib = "\n\n".join(bibliography_entries) if bibliography_entries else ""

    return tex, bib


def _validate_before_compile(
    tex_content: str,
    bib_content: str,
    output_dir: str = "",
) -> list[ValidationFinding]:
    """Pre-compilation validation gate.

    Catches deterministic errors before invoking the TeX engine:
    1. ``\\cite{key}`` references not present in bib_content
    2. Placeholder patterns (X%, TODO, TBD, [?], ??) in body text
    3. Unmatched ``\\begin{env}`` / ``\\end{env}`` pairs
    4. Missing ``\\includegraphics`` targets (when output_dir is provided)
    """
    findings: list[ValidationFinding] = []
    lines = tex_content.splitlines()

    # --- 1. Citation key audit ---
    bib_keys: set[str] = set()
    if bib_content:
        for m in re.finditer(r"@\w+\{(\w+)\s*,", bib_content):
            bib_keys.add(m.group(1))

    for lineno, line in enumerate(lines, start=1):
        for m in re.finditer(r"\\cite[tp]?\{([^}]+)\}", line):
            for key in m.group(1).split(","):
                key = key.strip()
                if key and key not in bib_keys:
                    findings.append(
                        ValidationFinding(
                            level="error",
                            category="cite_missing",
                            message=f"\\cite{{{key}}} not found in references.bib",
                            line_number=lineno,
                        )
                    )

    # --- 2. Placeholder detection ---
    # Only scan body text (between \begin{document} and \end{document})
    in_body = False
    placeholder_re = re.compile(
        r"(?<![\\])\b(?:TODO|TBD|FIXME|XXX)\b"  # explicit markers
        r"|(?<![\\0-9.])\b[XY]\\?%"  # X% or Y% (not 4.5%)
        r"|\[\?\]"  # [?]
        r"|\?\?(?!\?)",  # ?? but not ???
        re.IGNORECASE,
    )
    for lineno, line in enumerate(lines, start=1):
        if r"\begin{document}" in line:
            in_body = True
            continue
        if r"\end{document}" in line:
            in_body = False
            continue
        if not in_body:
            continue
        # Skip comment lines
        stripped = line.lstrip()
        if stripped.startswith("%"):
            continue
        for m in placeholder_re.finditer(line):
            findings.append(
                ValidationFinding(
                    level="warning",
                    category="placeholder",
                    message=f"Possible placeholder: '{m.group()}' in body text",
                    line_number=lineno,
                )
            )

    # --- 3. Unmatched \begin/\end environments ---
    env_stack: list[tuple[str, int]] = []
    env_re = re.compile(r"\\(begin|end)\{(\w+\*?)\}")
    for lineno, line in enumerate(lines, start=1):
        stripped = line.lstrip()
        if stripped.startswith("%"):
            continue
        for m in env_re.finditer(line):
            action, env_name = m.group(1), m.group(2)
            if action == "begin":
                env_stack.append((env_name, lineno))
            elif action == "end":
                if env_stack and env_stack[-1][0] == env_name:
                    env_stack.pop()
                elif env_stack:
                    opened = env_stack.pop()
                    findings.append(
                        ValidationFinding(
                            level="error",
                            category="env_mismatch",
                            message=(
                                f"\\end{{{env_name}}} at line {lineno} does not match "
                                f"\\begin{{{opened[0]}}} at line {opened[1]}"
                            ),
                            line_number=lineno,
                        )
                    )
                else:
                    findings.append(
                        ValidationFinding(
                            level="error",
                            category="env_mismatch",
                            message=f"\\end{{{env_name}}} without matching \\begin",
                            line_number=lineno,
                        )
                    )
    for env_name, lineno in env_stack:
        if env_name == "document":
            continue  # sometimes \end{document} is absent in partial content
        findings.append(
            ValidationFinding(
                level="error",
                category="env_mismatch",
                message=f"\\begin{{{env_name}}} at line {lineno} never closed",
                line_number=lineno,
            )
        )

    # --- 4. Missing \includegraphics targets ---
    if output_dir:
        out = Path(output_dir)
        for lineno, line in enumerate(lines, start=1):
            for m in re.finditer(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", line):
                fig_path = m.group(1)
                candidates = [
                    out / fig_path,
                    out / f"{fig_path}.png",
                    out / f"{fig_path}.pdf",
                    out / f"{fig_path}.jpg",
                ]
                if not any(c.exists() for c in candidates):
                    findings.append(
                        ValidationFinding(
                            level="warning",
                            category="figure_missing",
                            message=f"\\includegraphics target '{fig_path}' not found in {output_dir}",
                            line_number=lineno,
                        )
                    )

    return findings


def compile_latex(
    tex_content: str,
    bib_content: str,
    output_dir: str,
    filename: str = "paper",
) -> CompileResult:
    """Compile LaTeX to PDF using pdflatex + bibtex (3-pass).

    Falls back to generic template if conference .sty is missing.
    """
    result = CompileResult()
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # --- Pre-compilation validation gate ---
    validation = _validate_before_compile(tex_content, bib_content, output_dir)
    result.validation_findings = validation
    val_errors = [f for f in validation if f.level == "error"]
    val_warnings = [f for f in validation if f.level == "warning"]
    for f in val_warnings:
        result.warnings.append(f"[pre-compile] {f.category}: {f.message}")
    if val_errors:
        for f in val_errors:
            result.errors.append(f"[pre-compile] {f.category}: {f.message}")
        logger.warning(
            "Pre-compile validation found %d error(s) — proceeding with compilation "
            "but output may have issues: %s",
            len(val_errors),
            "; ".join(f.message for f in val_errors[:5]),
        )

    tex_file = out_path / f"{filename}.tex"
    bib_file = out_path / "references.bib"
    pdf_file = out_path / f"{filename}.pdf"

    # Write files
    tex_file.write_text(tex_content, encoding="utf-8")
    if bib_content:
        bib_file.write_text(bib_content, encoding="utf-8")

    # Engine preference: pdflatex > tectonic > skip
    engine = None
    if shutil.which("pdflatex"):
        engine = "pdflatex"
    elif shutil.which("tectonic"):
        engine = "tectonic"

    if not engine:
        result.log_summary = (
            "No LaTeX engine found — .tex/.bib written but not compiled"
        )
        result.warnings.append("Neither pdflatex nor tectonic available on this system")
        result.success = True  # files written successfully
        result.pdf_path = ""
        return result

    env = os.environ.copy()
    env["TEXINPUTS"] = f".:{out_path}:"

    # Use tectonic for single-pass auto-download compilation when pdflatex is not present
    if engine == "tectonic":
        try:
            proc = subprocess.run(
                ["tectonic", "--keep-logs", f"{filename}.tex"],
                cwd=str(out_path),
                capture_output=True,
                text=True,
                timeout=180,
                env=env,
            )
        except subprocess.TimeoutExpired:
            result.errors.append("tectonic timed out")
            return result
        log_file = out_path / f"{filename}.log"
        if log_file.exists():
            _parse_log(log_file.read_text(encoding="utf-8", errors="replace"), result)
        if pdf_file.exists():
            result.success = True
            result.pdf_path = str(pdf_file)
        else:
            # Auto-fix: retry with arxiv template if .sty missing
            stderr_text = (proc.stderr or "") + (proc.stdout or "")
            if "File " in stderr_text and ".sty' not found" in stderr_text:
                result.auto_fixes.append("Switched to arxiv template (missing .sty)")
                tex_content_fixed = re.sub(
                    r"\\documentclass\[.*?\]\{article\}\s*\\usepackage[^\n]*\{[a-z_\d]+\}",
                    r"\\documentclass[11pt]{article}\n\\usepackage[margin=1in]{geometry}",
                    tex_content,
                    count=1,
                )
                tex_file.write_text(tex_content_fixed, encoding="utf-8")
                proc = subprocess.run(
                    ["tectonic", "--keep-logs", f"{filename}.tex"],
                    cwd=str(out_path),
                    capture_output=True,
                    text=True,
                    timeout=180,
                    env=env,
                )
                if pdf_file.exists():
                    result.success = True
                    result.pdf_path = str(pdf_file)
                    return result
            result.errors.append("tectonic produced no PDF")
        return result

    # 3-pass compilation: pdflatex → bibtex → pdflatex → pdflatex
    passes = ["pdflatex", "bibtex", "pdflatex", "pdflatex"]
    for i, cmd in enumerate(passes):
        if cmd == "bibtex":
            if not bib_content:
                continue
            args = [cmd, filename]
        else:
            args = [
                cmd,
                "-interaction=nonstopmode",
                "-halt-on-error",
                f"{filename}.tex",
            ]

        try:
            proc = subprocess.run(
                args,
                cwd=str(out_path),
                capture_output=True,
                text=True,
                timeout=60,
                env=env,
            )
        except subprocess.TimeoutExpired:
            result.errors.append(f"Pass {i + 1} ({cmd}) timed out")
            break
        except FileNotFoundError:
            if cmd == "bibtex":
                result.warnings.append("bibtex not found, skipping bibliography")
                continue
            result.errors.append(f"{cmd} not found")
            break

        # Parse log for warnings/errors on final pass
        if i == len(passes) - 1 or proc.returncode != 0:
            log_file = out_path / f"{filename}.log"
            if log_file.exists():
                log_text = log_file.read_text(encoding="utf-8", errors="replace")
                _parse_log(log_text, result)

            if proc.returncode != 0 and cmd == "pdflatex" and i == 0:
                # Try auto-fix: switch to generic template
                if "! LaTeX Error: File" in (proc.stdout + proc.stderr):
                    result.auto_fixes.append(
                        "Switched to generic template (missing .sty)"
                    )
                    # Rewrite with generic template
                    tex_content_fixed = re.sub(
                        r"\\documentclass.*?\n",
                        r"\\documentclass[11pt,a4paper]{article}\n",
                        tex_content,
                    )
                    tex_file.write_text(tex_content_fixed, encoding="utf-8")
                    continue

    # Check for PDF
    if pdf_file.exists():
        result.success = True
        result.pdf_path = str(pdf_file)
        # Count pages
        try:
            proc = subprocess.run(
                ["pdfinfo", str(pdf_file)],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in proc.stdout.splitlines():
                if line.startswith("Pages:"):
                    result.pages = int(line.split(":")[1].strip())
        except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
            pass
    else:
        result.success = False
        result.log_summary = "PDF not generated"

    return result


def _parse_log(log_text: str, result: CompileResult) -> None:
    """Parse pdflatex log file for warnings and errors."""
    for line in log_text.splitlines():
        if line.startswith("! "):
            result.errors.append(line.strip())
        elif "Warning:" in line and len(line) < 200:
            result.warnings.append(line.strip())

    # Keep log summary short
    if result.errors:
        result.log_summary = (
            f"{len(result.errors)} error(s), {len(result.warnings)} warning(s)"
        )
    elif result.warnings:
        result.log_summary = f"No errors, {len(result.warnings)} warning(s)"
    else:
        result.log_summary = "Clean compilation"
