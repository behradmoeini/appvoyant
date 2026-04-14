from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from browser.controller import BrowserController
from core.contracts import ActionType, ExplorerInput, ExplorerOutput, InteractiveElement
from core.state_manager import StateManager


@dataclass(slots=True)
class PlannedAction:
    action_type: ActionType
    selector: str = ""
    value: str = ""
    description: str = ""
    element_key: str = ""


class ExplorerAgent:
    """Discovers actionable elements and executes meaningful user-like flows."""

    def __init__(
        self,
        browser: BrowserController,
        state_manager: StateManager,
        start_url: str,
        max_actions_per_state: int,
        logger,
    ) -> None:
        self.browser = browser
        self.state_manager = state_manager
        self.start_url = start_url
        self.max_actions_per_state = max_actions_per_state
        self.logger = logger
        self.pending_actions: deque[PlannedAction] = deque()

    def queue_retry(self) -> None:
        self.pending_actions.appendleft(
            PlannedAction(
                action_type="reload",
                description="Retry by reloading current page after a failed action",
                element_key="__retry_reload__",
            )
        )

    def execute(self, payload: ExplorerInput, step_index: int) -> ExplorerOutput:
        current_state = payload.current_state
        if not self.pending_actions:
            self.pending_actions.extend(self._build_plan(payload))

        selected: PlannedAction | None = None
        while self.pending_actions:
            candidate = self.pending_actions.popleft()
            action_key = self.state_manager.make_action_key(candidate.action_type, candidate.selector, candidate.value)
            if not self.state_manager.should_skip_action(
                current_state.state_id,
                action_key,
                max_attempts=self.max_actions_per_state,
            ):
                selected = candidate
                break

        recovery_used = False
        if selected is None:
            self.logger.info("No new action candidate found, recovery to start URL")
            selected = PlannedAction(
                action_type="navigate",
                value=self.start_url,
                description="Recover from dead-end and return to start URL",
                element_key="__recovery__",
            )
            recovery_used = True

        action, new_state = self.browser.perform_action(
            step_index=step_index,
            action_type=selected.action_type,
            state_before=current_state,
            target_selector=selected.selector,
            value=selected.value,
            description=selected.description,
        )

        if selected.action_type == "type" and selected.selector:
            self.state_manager.add_form_input(selected.selector, selected.value)

        if selected.element_key:
            self.state_manager.mark_element_explored(current_state.state_id, selected.element_key)

        discovered_new_state = self.state_manager.register_state(new_state)
        return ExplorerOutput(
            action=action,
            new_state=new_state,
            discovered_new_state=discovered_new_state,
            recovery_used=recovery_used,
        )

    def _build_plan(self, payload: ExplorerInput) -> list[PlannedAction]:
        current_state = payload.current_state
        unseen = [
            e for e in current_state.elements if not self.state_manager.is_element_explored(current_state.state_id, e.key)
        ]

        inputs = [e for e in unseen if e.tag in {"input", "textarea", "select"}]
        submits = [e for e in unseen if self._is_submit_like(e)]
        clickables = [
            e
            for e in unseen
            if e.tag in {"a", "button", "summary"} or e.role == "button" or e.href
        ]

        plan: list[PlannedAction] = []

        for element in sorted(inputs, key=lambda x: x.selector):
            values = self._generate_values(element, payload.decision.mode)
            for value in values:
                plan.append(
                    PlannedAction(
                        action_type="type",
                        selector=element.selector,
                        value=value,
                        description=f"Populate field {element.selector} with generated test input",
                        element_key=element.key,
                    )
                )

        for element in sorted(submits, key=lambda x: x.selector):
            plan.append(
                PlannedAction(
                    action_type="submit",
                    selector=element.selector,
                    description=f"Submit form via {element.selector}",
                    element_key=element.key,
                )
            )

        for element in sorted(clickables, key=lambda x: x.selector):
            if element.tag in {"input", "textarea", "select"}:
                continue
            plan.append(
                PlannedAction(
                    action_type="click",
                    selector=element.selector,
                    description=f"Click interactive element {element.selector}",
                    element_key=element.key,
                )
            )

        if not plan:
            plan.append(
                PlannedAction(
                    action_type="scroll",
                    value="750",
                    description="Scroll to discover lazy-loaded elements",
                    element_key="__scroll__",
                )
            )
            plan.append(
                PlannedAction(
                    action_type="go_back",
                    description="Navigate back to previous state after dead-end",
                    element_key="__go_back__",
                )
            )

        return plan

    @staticmethod
    def _is_submit_like(element: InteractiveElement) -> bool:
        submit_labels = {"submit", "login", "sign in", "register", "save", "continue", "search"}
        merged = " ".join(
            [
                (element.element_type or "").lower(),
                (element.text or "").lower(),
                (element.name or "").lower(),
                (element.aria_label or "").lower(),
            ]
        )
        return any(token in merged for token in submit_labels)

    @staticmethod
    def _generate_values(element: InteractiveElement, mode: str) -> list[str]:
        signature = " ".join(
            [
                element.element_type.lower(),
                element.name.lower(),
                element.placeholder.lower(),
                element.aria_label.lower(),
                element.text.lower(),
            ]
        )

        if "email" in signature:
            base = ["tester@example.com", "invalid-email", ""]
        elif "password" in signature:
            base = ["StrongPass123!", "123", ""]
        elif "phone" in signature or "tel" in signature:
            base = ["2125550188", "abcd", ""]
        elif "number" in signature or element.element_type == "number":
            base = ["0", "-1", "9999999999", ""]
        elif "search" in signature:
            base = ["smoke test", "!@#$%^&*()", ""]
        else:
            base = ["sample", "x" * 256, "<script>alert(1)</script>", ""]

        if mode == "explore":
            return base[:2]
        return base
