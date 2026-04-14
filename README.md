# Agentic Web Application Tester

Production-grade autonomous web testing system that explores real applications in a closed loop using a real browser, discovers flows dynamically, validates outcomes, and generates reproducible bug reports.

## Core capabilities

- Real browser execution via Playwright
- Multi-agent architecture with strict responsibility boundaries
- Persistent state graph with loop detection and replay support
- Intelligent, non-random exploration strategy
- Dynamic test input generation (valid, invalid, boundary, empty, long, special characters)
- Detection of navigation failures, UI anomalies, silent failures, and runtime errors
- Structured reporting in both JSON and Markdown

## Architecture

### Planner Agent (`agents/planner.py`)
- Inputs: `PlannerInput`
- Outputs: `PlannerDecision`
- Responsibilities:
  - Select exploration vs exploitation mode
  - Produce the next high-level objective
  - React to stagnation and issue backlog

### Explorer Agent (`agents/explorer.py`)
- Inputs: `ExplorerInput`
- Outputs: `ExplorerOutput`
- Responsibilities:
  - Interact with browser: click, type, submit, scroll, navigate, reload, go-back
  - Discover interactive elements dynamically
  - Build meaningful action plans prioritizing unseen elements and forms

### Validator Agent (`agents/validator.py`)
- Inputs: `ValidatorInput`
- Outputs: `ValidatorOutput`
- Responsibilities:
  - Validate action outcomes
  - Detect anomalies through URL/state/DOM checks and browser signals
  - Identify silent failures, broken transitions, console/network errors

### Reporter Agent (`agents/reporter.py`)
- Inputs: findings + state memory
- Outputs: JSON + Markdown reports
- Responsibilities:
  - Deduplicate issues
  - Emit reproducible issue entries with full action trace
  - Persist run memory and artifacts

## Project structure

```text
agents/
  planner.py
  explorer.py
  validator.py
  reporter.py

browser/
  controller.py

core/
  state_manager.py
  execution_loop.py

output/
  reports/
```

## Setup

1. Create a virtual environment.

```bash
python -m venv .venv
```

2. Activate the environment.

```bash
.venv\Scripts\activate
```

3. Install Python dependencies.

```bash
pip install -r requirements.txt
```

4. Install Playwright browser binaries.

```bash
python -m playwright install chromium
```

## Run

```bash
python main.py --url https://the-internet.herokuapp.com/login --max-steps 40
```

Useful options:

- `--max-states 120`
- `--max-actions-per-state 3`
- `--no-new-state-limit 12`
- `--retry-limit 2`
- `--headed` (run with visible browser)

## Example run against sample website

Command:

```bash
python main.py --url https://the-internet.herokuapp.com/login --max-steps 25 --headed
```

Expected artifacts:

- JSON report: `output/reports/<run_id>/bug_report.json`
- Markdown report: `output/reports/<run_id>/bug_report.md`
- Memory checkpoint: `output/reports/<run_id>_memory.json`
- Screenshots: `output/screenshots/*.png`

A sample report is included under:

- `output/reports/sample_run/bug_report.json`
- `output/reports/sample_run/bug_report.md`

## Determinism and resilience

- Deterministic action ordering (sorted selectors, stable heuristics)
- Explicit loop and stagnation controls
- Retry queue for failed actions
- Structured logging for all decisions and actions
- Graceful recovery to start URL on dead-end states
