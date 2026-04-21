"""AST-based code validation for experiment safety.

Validates generated experiment code before sandbox execution:
1. Syntax check (ast.parse)
2. Security scan (dangerous calls, banned modules)
3. Import check (against known-safe packages)
4. Auto-fix for common issues (unbound locals)

Adapted from AutoResearchClaw (MIT license).
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# -- Security rules -----------------------------------------------------------

DANGEROUS_CALLS: frozenset[str] = frozenset({
    "os.system", "os.exec", "os.execl", "os.execle", "os.execlp",
    "os.execv", "os.execve", "os.execvp", "os.execvpe",
    "os.popen", "os.remove", "os.unlink", "os.rmdir",
    "subprocess.call", "subprocess.run", "subprocess.Popen",
    "subprocess.check_call", "subprocess.check_output",
    "shutil.rmtree",
})

DANGEROUS_BUILTINS: frozenset[str] = frozenset({
    "eval", "exec", "compile", "__import__",
})

BANNED_MODULES: frozenset[str] = frozenset({
    "subprocess", "shutil", "socket", "http", "urllib",
    "requests", "ftplib", "smtplib", "ctypes", "signal",
})

SAFE_STDLIB: frozenset[str] = frozenset({
    "os", "sys", "math", "json", "re", "time", "pathlib",
    "csv", "pickle", "dataclasses", "logging", "contextlib",
    "functools", "itertools", "collections", "typing", "enum",
    "abc", "copy", "random", "statistics", "datetime",
    "argparse", "configparser", "io", "hashlib", "glob",
    "tempfile", "textwrap", "warnings", "traceback",
})

COMMON_SCIENCE: frozenset[str] = frozenset({
    "numpy", "np", "pandas", "pd", "scipy", "sklearn",
    "matplotlib", "plt", "seaborn", "sns",
    "torch", "torchvision", "torchaudio",
    "tensorflow", "tf", "keras",
    "transformers", "datasets", "tokenizers", "accelerate",
    "tqdm", "wandb", "tensorboard",
    "gym", "gymnasium", "stable_baselines3",
    "PIL", "cv2", "einops", "flash_attn",
    "peft", "bitsandbytes", "safetensors",
    "yaml", "pyyaml", "toml", "rich",
})


# -- Data structures ----------------------------------------------------------


@dataclass(frozen=True)
class ValidationIssue:
    severity: str  # "error" | "warning"
    category: str  # "syntax" | "security" | "import" | "quality"
    message: str
    line: int | None = None


@dataclass
class CodeValidation:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")

    def summary(self) -> str:
        if self.ok:
            return f"Validation passed ({self.warning_count} warnings)"
        return f"Validation failed: {self.error_count} errors, {self.warning_count} warnings"


# -- Validators ---------------------------------------------------------------


class _SecurityVisitor(ast.NodeVisitor):
    """AST visitor that detects dangerous calls and imports."""

    def __init__(self) -> None:
        self.issues: list[ValidationIssue] = []

    def visit_Call(self, node: ast.Call) -> None:
        func_name = self._get_call_name(node)
        if func_name in DANGEROUS_CALLS:
            self.issues.append(ValidationIssue(
                severity="error",
                category="security",
                message=f"Dangerous call: {func_name}",
                line=node.lineno,
            ))
        if func_name in DANGEROUS_BUILTINS:
            self.issues.append(ValidationIssue(
                severity="error",
                category="security",
                message=f"Dangerous builtin: {func_name}",
                line=node.lineno,
            ))
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            mod = alias.name.split(".")[0]
            if mod in BANNED_MODULES:
                self.issues.append(ValidationIssue(
                    severity="error",
                    category="security",
                    message=f"Banned module: {mod}",
                    line=node.lineno,
                ))
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            mod = node.module.split(".")[0]
            if mod in BANNED_MODULES:
                self.issues.append(ValidationIssue(
                    severity="error",
                    category="security",
                    message=f"Banned module: {mod}",
                    line=node.lineno,
                ))
        self.generic_visit(node)

    @staticmethod
    def _get_call_name(node: ast.Call) -> str:
        if isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                return f"{node.func.value.id}.{node.func.attr}"
        if isinstance(node.func, ast.Name):
            return node.func.id
        return ""


def validate_syntax(code: str) -> list[ValidationIssue]:
    """Check Python syntax via ast.parse."""
    try:
        ast.parse(code)
        return []
    except SyntaxError as exc:
        return [ValidationIssue(
            severity="error",
            category="syntax",
            message=str(exc),
            line=exc.lineno,
        )]


def validate_security(code: str) -> list[ValidationIssue]:
    """Scan AST for dangerous calls and banned modules."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []  # syntax errors caught separately
    visitor = _SecurityVisitor()
    visitor.visit(tree)
    return visitor.issues


def validate_imports(code: str) -> list[ValidationIssue]:
    """Check that all imports are from known-safe packages."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    issues: list[ValidationIssue] = []
    known = SAFE_STDLIB | COMMON_SCIENCE
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name.split(".")[0]
                if mod not in known and mod not in BANNED_MODULES:
                    issues.append(ValidationIssue(
                        severity="warning",
                        category="import",
                        message=f"Unknown package: {mod} (may need pip install)",
                        line=node.lineno,
                    ))
        elif isinstance(node, ast.ImportFrom) and node.module:
            mod = node.module.split(".")[0]
            if mod not in known and mod not in BANNED_MODULES:
                issues.append(ValidationIssue(
                    severity="warning",
                    category="import",
                    message=f"Unknown package: {mod} (may need pip install)",
                    line=node.lineno,
                ))
    return issues


def validate_code(code: str) -> CodeValidation:
    """Run all validation checks and return a combined result."""
    result = CodeValidation()
    result.issues.extend(validate_syntax(code))
    if result.ok:  # only proceed if syntax is valid
        result.issues.extend(validate_security(code))
        result.issues.extend(validate_imports(code))
    return result


def auto_fix_unbound_locals(code: str) -> tuple[str, int]:
    """Insert `var = None` for variables assigned only inside if-branches.

    Returns (fixed_code, number_of_fixes).
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code, 0

    fixes = 0
    lines = code.splitlines(keepends=True)

    # Find variables assigned only in if-branches but used later
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            # Collect assignments in the if body
            if_assigns: set[str] = set()
            for child in ast.walk(node):
                if isinstance(child, ast.Assign):
                    for target in child.targets:
                        if isinstance(target, ast.Name):
                            if_assigns.add(target.id)

            # Check if any are used after the if block
            # (simplified: just add initialization before the if)
            if if_assigns and node.lineno <= len(lines):
                indent = ""
                line = lines[node.lineno - 1]
                indent = line[: len(line) - len(line.lstrip())]
                for var in sorted(if_assigns):
                    init_line = f"{indent}{var} = None  # auto-fix: initialize before if\n"
                    lines.insert(node.lineno - 1, init_line)
                    fixes += 1

    if fixes > 0:
        return "".join(lines), fixes
    return code, 0
