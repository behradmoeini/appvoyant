from __future__ import annotations

import argparse
from datetime import datetime

from agents.explorer import ExplorerAgent
from agents.planner import PlannerAgent
from agents.reporter import ReporterAgent
from agents.validator import ValidatorAgent
from browser.controller import BrowserController
from core.contracts import ExecutionConfig
from core.execution_loop import ExecutionLoop
from core.logging_utils import configure_logging
from core.state_manager import StateManager


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Autonomous multi-agent web application tester")
    parser.add_argument("--url", required=True, help="Starting URL for exploration")
    parser.add_argument("--max-steps", type=int, default=60, help="Maximum number of loop iterations")
    parser.add_argument("--max-states", type=int, default=120, help="Maximum discovered states before stopping")
    parser.add_argument(
        "--max-actions-per-state",
        type=int,
        default=3,
        help="Cap repeated attempts of the same action in one state",
    )
    parser.add_argument(
        "--no-new-state-limit",
        type=int,
        default=12,
        help="Stop when no new state is discovered for this many steps",
    )
    parser.add_argument("--retry-limit", type=int, default=2, help="Maximum auto-retry count for failed actions")
    parser.set_defaults(headless=True)
    parser.add_argument(
        "--headed",
        dest="headless",
        action="store_false",
        help="Run browser with a visible window",
    )
    parser.add_argument(
        "--output-dir",
        default="output/reports",
        help="Directory for JSON/markdown report output",
    )
    parser.add_argument(
        "--screenshot-dir",
        default="output/screenshots",
        help="Directory for screenshots",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_id = datetime.utcnow().strftime("run_%Y%m%d_%H%M%S")

    config = ExecutionConfig(
        start_url=args.url,
        max_steps=args.max_steps,
        max_states=args.max_states,
        max_actions_per_state=args.max_actions_per_state,
        no_new_state_limit=args.no_new_state_limit,
        retry_limit=args.retry_limit,
        headless=args.headless,
        output_dir=args.output_dir,
        screenshot_dir=args.screenshot_dir,
    )

    logger = configure_logging(log_dir=args.output_dir, run_id=run_id)
    state_manager = StateManager(run_id=run_id, checkpoint_dir=args.output_dir)

    browser = BrowserController(config=config, logger=logger)
    planner = PlannerAgent(no_new_state_limit=config.no_new_state_limit)
    explorer = ExplorerAgent(
        browser=browser,
        state_manager=state_manager,
        start_url=config.start_url,
        max_actions_per_state=config.max_actions_per_state,
        logger=logger,
    )
    validator = ValidatorAgent()
    reporter = ReporterAgent(output_dir=config.output_dir, run_id=run_id, logger=logger)

    loop = ExecutionLoop(
        config=config,
        browser=browser,
        planner=planner,
        explorer=explorer,
        validator=validator,
        reporter=reporter,
        state_manager=state_manager,
        logger=logger,
    )

    artifact = loop.run()
    print(f"Run complete: findings={artifact.finding_count}")
    print(f"JSON report: {artifact.json_path}")
    print(f"Markdown report: {artifact.markdown_path}")


if __name__ == "__main__":
    main()
