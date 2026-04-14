from __future__ import annotations

from core.contracts import PlannerDecision, PlannerInput


class PlannerAgent:
    """Chooses high-level objectives and exploration mode."""

    def __init__(self, no_new_state_limit: int) -> None:
        self.no_new_state_limit = no_new_state_limit

    def plan(self, payload: PlannerInput) -> PlannerDecision:
        remaining_budget = payload.max_steps - payload.step_index

        if payload.no_new_state_streak >= self.no_new_state_limit:
            return PlannerDecision(
                objective="Terminate: no new states discovered within budget",
                mode="exploit",
                reason="Stagnation threshold reached",
                preferred_actions=["go_back", "reload", "navigate"],
            )

        if payload.recent_failures > 1 or payload.pending_issue_count > 0:
            return PlannerDecision(
                objective="Validate and reproduce observed anomalies",
                mode="exploit",
                reason="Recent failures or pending findings require confirmation",
                preferred_actions=["reload", "click", "submit", "type"],
            )

        if remaining_budget <= 5:
            return PlannerDecision(
                objective="Cover high-value unexplored paths before budget ends",
                mode="explore",
                reason="Execution budget nearly exhausted",
                preferred_actions=["click", "submit", "type", "scroll"],
            )

        return PlannerDecision(
            objective="Expand state graph by prioritizing unseen interactive elements",
            mode="explore",
            reason="Healthy exploration phase",
            preferred_actions=["type", "submit", "click", "scroll"],
        )
