from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from core.contracts import ReportArtifact, ValidationFinding
from core.state_manager import StateManager


class ReporterAgent:
    """Produces structured JSON and Markdown bug reports."""

    def __init__(self, output_dir: str, run_id: str, logger) -> None:
        self.output_dir = Path(output_dir) / run_id
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.logger = logger

        self._findings: list[ValidationFinding] = []
        self._seen_fingerprints: set[str] = set()

    def record_findings(self, findings: list[ValidationFinding], state_manager: StateManager) -> int:
        new_count = 0
        full_trace = [step.to_dict() for step in state_manager.action_history]

        for finding in findings:
            if finding.fingerprint in self._seen_fingerprints:
                continue

            finding.action_trace = full_trace.copy()
            self._findings.append(finding)
            self._seen_fingerprints.add(finding.fingerprint)
            state_manager.add_issue(finding)
            new_count += 1

        if new_count:
            self.logger.info("Reporter logged %s new findings", new_count)
        return new_count

    def finalize(self, state_manager: StateManager) -> ReportArtifact:
        json_path = self.output_dir / "bug_report.json"
        markdown_path = self.output_dir / "bug_report.md"
        memory_path = state_manager.save_checkpoint()

        payload = {
            "run_id": self.run_id,
            "generated_at": datetime.utcnow().isoformat(),
            "summary": {
                "total_findings": len(self._findings),
                "total_states": len(state_manager.states),
                "total_actions": len(state_manager.action_history),
            },
            "issues": [self._finding_to_issue(finding) for finding in self._findings],
            "memory_checkpoint": str(memory_path),
        }
        json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        markdown_path.write_text(self._render_markdown(payload), encoding="utf-8")

        self.logger.info("Reports written: %s and %s", json_path, markdown_path)
        return ReportArtifact(json_path=str(json_path), markdown_path=str(markdown_path), finding_count=len(self._findings))

    @staticmethod
    def _finding_to_issue(finding: ValidationFinding) -> dict[str, Any]:
        return {
            "title": finding.title,
            "severity": finding.severity,
            "reproduction_steps": finding.reproduction_steps,
            "expected_behavior": finding.expected_behavior,
            "actual_behavior": finding.actual_behavior,
            "screenshots": finding.screenshots,
            "action_trace": finding.action_trace,
        }

    def _render_markdown(self, payload: dict[str, Any]) -> str:
        lines: list[str] = []
        lines.append(f"# Agentic Web Tester Report - {payload['run_id']}")
        lines.append("")
        summary = payload["summary"]
        lines.append("## Summary")
        lines.append("")
        lines.append(f"- Total findings: **{summary['total_findings']}**")
        lines.append(f"- Total states explored: **{summary['total_states']}**")
        lines.append(f"- Total actions executed: **{summary['total_actions']}**")
        lines.append("")

        issues = payload["issues"]
        if not issues:
            lines.append("No issues detected within the configured exploration budget.")
            lines.append("")
            return "\n".join(lines)

        lines.append("## Findings")
        lines.append("")
        for index, issue in enumerate(issues, start=1):
            lines.append(f"### {index}. {issue['title']} ({issue['severity']})")
            lines.append("")
            lines.append("**Reproduction steps**")
            for step in issue["reproduction_steps"]:
                lines.append(f"1. {step}")
            lines.append("")
            lines.append("**Expected behavior**")
            lines.append(issue["expected_behavior"])
            lines.append("")
            lines.append("**Actual behavior**")
            lines.append(issue["actual_behavior"])
            lines.append("")
            lines.append("**Screenshots**")
            for screenshot in issue["screenshots"]:
                lines.append(f"- `{screenshot}`")
            lines.append("")
            lines.append("**Action trace length**")
            lines.append(f"- {len(issue['action_trace'])} steps captured")
            lines.append("")

        return "\n".join(lines)
