from __future__ import annotations

import hashlib
from urllib.parse import urlparse

from core.contracts import ValidationFinding, ValidatorInput, ValidatorOutput


class ValidatorAgent:
    """Evaluates execution outcomes and detects anomalies after each action."""

    def validate(self, payload: ValidatorInput) -> ValidatorOutput:
        findings: list[ValidationFinding] = []
        anomalies: list[str] = []
        should_retry = False

        action = payload.action
        previous_state = payload.previous_state
        current_state = payload.current_state

        if not action.success:
            anomalies.append("Action failed to execute")
            findings.append(
                self._build_finding(
                    title=f"Action failed: {action.action_type}",
                    severity="high",
                    expected_behavior="The requested UI action should execute successfully.",
                    actual_behavior=f"Action failed with error: {action.error_message}",
                    payload=payload,
                )
            )
            should_retry = True

        if current_state.console_errors:
            anomalies.append("Console errors detected")
            findings.append(
                self._build_finding(
                    title="Console errors during user flow",
                    severity="medium",
                    expected_behavior="Browser console should remain free from runtime errors during interaction.",
                    actual_behavior="Runtime console errors were emitted while executing the flow.",
                    payload=payload,
                )
            )

        if current_state.network_errors:
            anomalies.append("Network failures detected")
            findings.append(
                self._build_finding(
                    title="Network request failures encountered",
                    severity="medium",
                    expected_behavior="Required network requests should complete successfully.",
                    actual_behavior="One or more requests failed during this flow.",
                    payload=payload,
                )
            )

        state_unchanged = (
            previous_state.state_id == current_state.state_id
            and previous_state.dom_hash == current_state.dom_hash
            and previous_state.url == current_state.url
        )
        if action.action_type in {"click", "submit"} and action.success and state_unchanged:
            anomalies.append("Potential silent failure")
            findings.append(
                self._build_finding(
                    title="Silent failure after interactive action",
                    severity="medium",
                    expected_behavior="Clicking or submitting should trigger navigation, state change, or user feedback.",
                    actual_behavior="No visible DOM, URL, or state transition occurred after the action.",
                    payload=payload,
                )
            )

        if action.action_type not in {"navigate", "go_back", "reload"}:
            prev_host = urlparse(previous_state.url).netloc
            curr_host = urlparse(current_state.url).netloc
            if prev_host and curr_host and prev_host != curr_host:
                anomalies.append("Unexpected host transition")
                findings.append(
                    self._build_finding(
                        title="Unexpected cross-domain transition",
                        severity="high",
                        expected_behavior="In-app interaction should remain within expected domain unless explicitly external.",
                        actual_behavior=f"Action transitioned from {prev_host} to {curr_host} unexpectedly.",
                        payload=payload,
                    )
                )

        if len(current_state.elements) == 0:
            anomalies.append("No interactive elements found")
            findings.append(
                self._build_finding(
                    title="Potential dead-end state",
                    severity="low",
                    expected_behavior="Page should expose at least one interactive element for user continuation.",
                    actual_behavior="No interactive controls were detected in the current state.",
                    payload=payload,
                )
            )

        deduped = self._deduplicate(findings)
        return ValidatorOutput(findings=deduped, anomalies=anomalies, should_retry=should_retry)

    def _build_finding(
        self,
        title: str,
        severity: str,
        expected_behavior: str,
        actual_behavior: str,
        payload: ValidatorInput,
    ) -> ValidationFinding:
        action = payload.action
        reproduction_steps = [
            f"Open {payload.previous_state.url}",
            f"Perform action `{action.action_type}` on `{action.target_selector or '[none]'}` with value `{action.value}`",
            "Observe resulting state and browser signals",
        ]
        action_trace = [
            {
                "step_index": action.step_index,
                "action_type": action.action_type,
                "target_selector": action.target_selector,
                "value": action.value,
                "url_before": action.url_before,
                "url_after": action.url_after,
                "success": action.success,
                "error_message": action.error_message,
            }
        ]
        fingerprint_source = "|".join([title, severity, action.action_type, action.target_selector, action.url_after])
        fingerprint = hashlib.sha1(fingerprint_source.encode("utf-8")).hexdigest()

        screenshots = [payload.previous_state.screenshot_path, payload.current_state.screenshot_path]
        return ValidationFinding(
            title=title,
            severity=severity,
            reproduction_steps=reproduction_steps,
            expected_behavior=expected_behavior,
            actual_behavior=actual_behavior,
            screenshots=screenshots,
            action_trace=action_trace,
            fingerprint=fingerprint,
        )

    @staticmethod
    def _deduplicate(findings: list[ValidationFinding]) -> list[ValidationFinding]:
        seen: set[str] = set()
        deduped: list[ValidationFinding] = []
        for finding in findings:
            if finding.fingerprint in seen:
                continue
            deduped.append(finding)
            seen.add(finding.fingerprint)
        return deduped
