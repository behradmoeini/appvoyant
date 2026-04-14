from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from dataclasses import asdict
from pathlib import Path
from typing import Any

from core.contracts import ActionStep, PageStateSnapshot, PersistentState, ValidationFinding


class StateManager:
    """Maintains persistent structured memory and navigation graph."""

    def __init__(self, run_id: str, checkpoint_dir: str) -> None:
        self.run_id = run_id
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

        self.states: dict[str, PageStateSnapshot] = {}
        self.graph: dict[str, list[dict[str, str]]] = defaultdict(list)
        self.action_history: list[ActionStep] = []
        self.form_inputs_used: list[dict[str, str]] = []
        self.issues: list[ValidationFinding] = []

        self._state_sequence: deque[str] = deque(maxlen=20)
        self._explored_keys: dict[str, set[str]] = defaultdict(set)
        self._action_counts: dict[tuple[str, str], int] = defaultdict(int)
        self._parent_action_by_state: dict[str, tuple[str, ActionStep]] = {}

    @staticmethod
    def hash_text(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def register_state(self, snapshot: PageStateSnapshot) -> bool:
        is_new = snapshot.state_id not in self.states
        self.states[snapshot.state_id] = snapshot
        self._state_sequence.append(snapshot.state_id)
        return is_new

    def mark_element_explored(self, state_id: str, key: str) -> None:
        self._explored_keys[state_id].add(key)

    def is_element_explored(self, state_id: str, key: str) -> bool:
        return key in self._explored_keys[state_id]

    def action_attempt_count(self, state_id: str, action_key: str) -> int:
        return self._action_counts[(state_id, action_key)]

    def record_transition(self, action: ActionStep) -> None:
        self.action_history.append(action)
        action_key = self.make_action_key(action.action_type, action.target_selector, action.value)
        self._action_counts[(action.state_before, action_key)] += 1
        self.graph[action.state_before].append(
            {
                "action_type": action.action_type,
                "target_selector": action.target_selector,
                "value": action.value,
                "to_state": action.state_after,
            }
        )
        if action.state_after not in self._parent_action_by_state and action.state_before != action.state_after:
            self._parent_action_by_state[action.state_after] = (action.state_before, action)

    def add_form_input(self, selector: str, value: str) -> None:
        self.form_inputs_used.append({"selector": selector, "value": value})

    def add_issue(self, finding: ValidationFinding) -> None:
        self.issues.append(finding)

    def recent_failures(self, window: int = 8) -> int:
        return sum(1 for step in self.action_history[-window:] if not step.success)

    def has_loop(self, candidate_state_id: str, loop_threshold: int = 3) -> bool:
        occurrences = list(self._state_sequence).count(candidate_state_id)
        return occurrences >= loop_threshold

    def should_skip_action(self, state_id: str, action_key: str, max_attempts: int) -> bool:
        return self.action_attempt_count(state_id, action_key) >= max_attempts

    def replay_sequence(self, target_state_id: str) -> list[ActionStep]:
        if target_state_id not in self.states:
            return []

        sequence: list[ActionStep] = []
        current = target_state_id
        while current in self._parent_action_by_state:
            parent, action = self._parent_action_by_state[current]
            sequence.append(action)
            current = parent
        sequence.reverse()
        return sequence

    @staticmethod
    def make_action_key(action_type: str, selector: str, value: str) -> str:
        raw = f"{action_type}|{selector}|{value}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def summary(self) -> dict[str, Any]:
        latest_state_id = self._state_sequence[-1] if self._state_sequence else ""
        return {
            "known_state_count": len(self.states),
            "latest_state_id": latest_state_id,
            "recent_failures": self.recent_failures(),
            "issue_count": len(self.issues),
        }

    def to_persistent_state(self) -> PersistentState:
        return PersistentState(
            run_id=self.run_id,
            states={state_id: state.to_dict() for state_id, state in self.states.items()},
            graph=dict(self.graph),
            action_history=[a.to_dict() for a in self.action_history],
            form_inputs_used=self.form_inputs_used,
            issues=[finding.to_dict() for finding in self.issues],
        )

    def save_checkpoint(self) -> Path:
        checkpoint_file = self.checkpoint_dir / f"{self.run_id}_memory.json"
        payload = self.to_persistent_state().to_dict()
        checkpoint_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return checkpoint_file
