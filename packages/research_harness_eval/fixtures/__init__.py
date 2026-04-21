"""Frozen eval fixtures per stage."""

from .build_stage import BUILD_CASES
from .analyze_stage import ANALYZE_CASES
from .write_stage import WRITE_CASES

ALL_CASES = BUILD_CASES + ANALYZE_CASES + WRITE_CASES
