from __future__ import annotations

from dataclasses import asdict

from agents.explorer import ExplorerAgent
from agents.planner import PlannerAgent
from agents.reporter import ReporterAgent
from agents.validator import ValidatorAgent
from browser.controller import BrowserController
from core.contracts import ExecutionConfig, ExplorerInput, PlannerInput, ValidatorInput
from core.state_manager import StateManager


class ExecutionLoop:
    """Closed-loop orchestration across planner, explorer, validator, and reporter."""

    def __init__(
        self,
        config: ExecutionConfig,
        browser: BrowserController,
        planner: PlannerAgent,
        explorer: ExplorerAgent,
        validator: ValidatorAgent,
        reporter: ReporterAgent,
        state_manager: StateManager,
        logger,
    ) -> None:
        self.config = config
        self.browser = browser
        self.planner = planner
        self.explorer = explorer
        self.validator = validator
        self.reporter = reporter
        self.state_manager = state_manager
        self.logger = logger

    def run(self):
        self.browser.start()
        current_state = self.browser.goto(self.config.start_url)
        self.state_manager.register_state(current_state)

        no_new_state_streak = 0
        retry_count = 0

        try:
            for step_index in range(1, self.config.max_steps + 1):
                planner_input = PlannerInput(
                    step_index=step_index,
                    max_steps=self.config.max_steps,
                    known_state_count=len(self.state_manager.states),
                    no_new_state_streak=no_new_state_streak,
                    pending_issue_count=len(self.state_manager.issues),
                    recent_failures=self.state_manager.recent_failures(),
                    current_state_id=current_state.state_id,
                )
                decision = self.planner.plan(planner_input)
                self.logger.info(
                    "Step %s decision=%s objective=%s reason=%s",
                    step_index,
                    decision.mode,
                    decision.objective,
                    decision.reason,
                )

                if "Terminate" in decision.objective:
                    self.logger.info("Planner requested termination: %s", decision.reason)
                    break

                explorer_output = self.explorer.execute(
                    payload=ExplorerInput(decision=decision, current_state=current_state),
                    step_index=step_index,
                )

                self.state_manager.record_transition(explorer_output.action)

                validator_output = self.validator.validate(
                    ValidatorInput(
                        decision=decision,
                        previous_state=current_state,
                        current_state=explorer_output.new_state,
                        action=explorer_output.action,
                    )
                )
                self.reporter.record_findings(validator_output.findings, self.state_manager)

                if explorer_output.discovered_new_state:
                    no_new_state_streak = 0
                else:
                    no_new_state_streak += 1

                if validator_output.should_retry and retry_count < self.config.retry_limit:
                    retry_count += 1
                    self.explorer.queue_retry()
                else:
                    retry_count = 0

                current_state = explorer_output.new_state

                if len(self.state_manager.states) >= self.config.max_states:
                    self.logger.info("Stopping: max state budget reached (%s)", self.config.max_states)
                    break

                if no_new_state_streak >= self.config.no_new_state_limit:
                    self.logger.info(
                        "Stopping: no new states discovered for %s steps",
                        self.config.no_new_state_limit,
                    )
                    break

            artifact = self.reporter.finalize(self.state_manager)
            self.logger.info(
                "Execution completed with %s findings. JSON=%s",
                artifact.finding_count,
                artifact.json_path,
            )
            return artifact
        finally:
            self.browser.stop()
