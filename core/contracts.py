from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal

Severity = Literal["low", "medium", "high"]
PlannerMode = Literal["explore", "exploit"]
ActionType = Literal["navigate", "click", "type", "scroll", "submit", "go_back", "reload"]


@dataclass(slots=True)
class InteractiveElement:
    key: str
    tag: str
    selector: str
    text: str = ""
    element_type: str = ""
    name: str = ""
    placeholder: str = ""
    aria_label: str = ""
    href: str = ""
    role: str = ""
    form_selector: str = ""
    visible: bool = True
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PageStateSnapshot:
    state_id: str
    url: str
    title: str
    dom_hash: str
    elements: list[InteractiveElement]
    screenshot_path: str
    console_errors: list[str]
    network_errors: list[str]
    captured_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["elements"] = [e.to_dict() for e in self.elements]
        return payload


@dataclass(slots=True)
class ActionStep:
    step_index: int
    action_type: ActionType
    target_selector: str
    value: str
    description: str
    state_before: str
    state_after: str
    url_before: str
    url_after: str
    success: bool
    error_message: str = ""
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PlannerInput:
    step_index: int
    max_steps: int
    known_state_count: int
    no_new_state_streak: int
    pending_issue_count: int
    recent_failures: int
    current_state_id: str


@dataclass(slots=True)
class PlannerDecision:
    objective: str
    mode: PlannerMode
    reason: str
    preferred_actions: list[ActionType]


@dataclass(slots=True)
class ExplorerInput:
    decision: PlannerDecision
    current_state: PageStateSnapshot


@dataclass(slots=True)
class ExplorerOutput:
    action: ActionStep
    new_state: PageStateSnapshot
    discovered_new_state: bool
    recovery_used: bool


@dataclass(slots=True)
class ValidationFinding:
    title: str
    severity: Severity
    reproduction_steps: list[str]
    expected_behavior: str
    actual_behavior: str
    screenshots: list[str]
    action_trace: list[dict[str, Any]]
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ValidatorInput:
    decision: PlannerDecision
    previous_state: PageStateSnapshot
    current_state: PageStateSnapshot
    action: ActionStep


@dataclass(slots=True)
class ValidatorOutput:
    findings: list[ValidationFinding]
    anomalies: list[str]
    should_retry: bool


@dataclass(slots=True)
class ReportArtifact:
    json_path: str
    markdown_path: str
    finding_count: int


@dataclass(slots=True)
class ExecutionConfig:
    start_url: str
    max_steps: int = 60
    max_states: int = 120
    max_actions_per_state: int = 3
    no_new_state_limit: int = 12
    retry_limit: int = 2
    headless: bool = True
    navigation_timeout_ms: int = 12000
    action_timeout_ms: int = 5000
    output_dir: str = "output/reports"
    screenshot_dir: str = "output/screenshots"


@dataclass(slots=True)
class PersistentState:
    run_id: str
    states: dict[str, dict[str, Any]]
    graph: dict[str, list[dict[str, Any]]]
    action_history: list[dict[str, Any]]
    form_inputs_used: list[dict[str, str]]
    issues: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
