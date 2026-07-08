"""Report builder — renders CheckResults to terminal, JSON, HTML, and SARIF."""

from __future__ import annotations

from miraxis.report.fix_report import render_fix_json, render_fix_json_error, render_fix_terminal
from miraxis.report.html_report import render_html
from miraxis.report.json_report import render_json, render_json_load_error
from miraxis.report.sarif import render_sarif
from miraxis.report.terminal import render_terminal
from miraxis.report.trust_score import SCORE_FORMULA_VERSION, compute_trust_score

__all__ = [
    "SCORE_FORMULA_VERSION",
    "compute_trust_score",
    "render_fix_json",
    "render_fix_json_error",
    "render_fix_terminal",
    "render_html",
    "render_json",
    "render_json_load_error",
    "render_sarif",
    "render_terminal",
]
