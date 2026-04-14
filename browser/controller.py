from __future__ import annotations

import hashlib
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from core.contracts import ActionStep, ActionType, ExecutionConfig, InteractiveElement, PageStateSnapshot


class BrowserController:
    """Thin abstraction over Playwright with deterministic state snapshots."""

    def __init__(self, config: ExecutionConfig, logger) -> None:
        self.config = config
        self.logger = logger

        self._playwright = None
        self.browser = None
        self.context = None
        self.page = None

        self._console_events: list[str] = []
        self._network_events: list[str] = []
        self._page_errors: list[str] = []
        self._console_cursor = 0
        self._network_cursor = 0

        Path(self.config.screenshot_dir).mkdir(parents=True, exist_ok=True)

    def start(self) -> None:
        self._playwright = sync_playwright().start()
        self.browser = self._playwright.chromium.launch(headless=self.config.headless)
        self.context = self.browser.new_context(viewport={"width": 1440, "height": 900}, ignore_https_errors=True)
        self.page = self.context.new_page()
        self.page.set_default_navigation_timeout(self.config.navigation_timeout_ms)
        self.page.set_default_timeout(self.config.action_timeout_ms)

        self.page.on("console", self._on_console)
        self.page.on("requestfailed", self._on_request_failed)
        self.page.on("pageerror", self._on_page_error)
        self.logger.info("Browser started (headless=%s)", self.config.headless)

    def stop(self) -> None:
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
        if self._playwright:
            self._playwright.stop()
        self.logger.info("Browser stopped")

    def goto(self, url: str) -> PageStateSnapshot:
        self.logger.info("Navigating to %s", url)
        self.page.goto(url, wait_until="domcontentloaded")
        self.page.wait_for_timeout(250)
        return self.snapshot(label="initial")

    def snapshot(self, label: str) -> PageStateSnapshot:
        elements = self._extract_interactive_elements()
        dom = self.page.content()
        url = self.page.url
        title = self.page.title()

        structure_fingerprint = "|".join(sorted(f"{e.tag}:{e.selector}:{e.text[:30]}" for e in elements)[:80])
        state_source = f"{url}|{title}|{structure_fingerprint}"
        state_id = hashlib.sha1(state_source.encode("utf-8")).hexdigest()[:16]
        dom_hash = hashlib.sha256(dom.encode("utf-8")).hexdigest()

        screenshot_path = self._capture_screenshot(label)
        console_errors, network_errors = self._consume_error_buffers()

        return PageStateSnapshot(
            state_id=state_id,
            url=url,
            title=title,
            dom_hash=dom_hash,
            elements=elements,
            screenshot_path=screenshot_path,
            console_errors=console_errors,
            network_errors=network_errors,
        )

    def perform_action(
        self,
        step_index: int,
        action_type: ActionType,
        state_before: PageStateSnapshot,
        target_selector: str = "",
        value: str = "",
        description: str = "",
    ) -> tuple[ActionStep, PageStateSnapshot]:
        success = True
        error_message = ""

        try:
            if action_type == "click":
                self.page.locator(target_selector).first.click()
            elif action_type == "type":
                locator = self.page.locator(target_selector).first
                locator.fill(value)
                locator.blur()
            elif action_type == "scroll":
                scroll_amount = int(value) if value else 700
                self.page.mouse.wheel(0, scroll_amount)
            elif action_type == "submit":
                if target_selector:
                    self.page.locator(target_selector).first.click()
                else:
                    self.page.keyboard.press("Enter")
            elif action_type == "navigate":
                destination = value or target_selector
                self.page.goto(destination, wait_until="domcontentloaded")
            elif action_type == "go_back":
                self.page.go_back(wait_until="domcontentloaded")
            elif action_type == "reload":
                self.page.reload(wait_until="domcontentloaded")

            self.page.wait_for_timeout(300)
        except (PlaywrightTimeoutError, PlaywrightError, ValueError) as exc:
            success = False
            error_message = str(exc)
            self.logger.warning("Action failed: %s", error_message)

        after_state = self.snapshot(label=f"step_{step_index:03d}")
        action = ActionStep(
            step_index=step_index,
            action_type=action_type,
            target_selector=target_selector,
            value=value,
            description=description,
            state_before=state_before.state_id,
            state_after=after_state.state_id,
            url_before=state_before.url,
            url_after=after_state.url,
            success=success,
            error_message=error_message,
        )
        return action, after_state

    def recover(self, start_url: str, step_index: int, previous_state: PageStateSnapshot) -> tuple[ActionStep, PageStateSnapshot]:
        self.logger.info("Recovery triggered: return to %s", start_url)
        return self.perform_action(
            step_index=step_index,
            action_type="navigate",
            state_before=previous_state,
            value=start_url,
            description="Recovery navigation to start URL",
        )

    def _capture_screenshot(self, label: str) -> str:
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
        file_path = Path(self.config.screenshot_dir) / f"{label}_{timestamp}.png"
        self.page.screenshot(path=str(file_path), full_page=True)
        return str(file_path)

    def _consume_error_buffers(self) -> tuple[list[str], list[str]]:
        console_slice = self._console_events[self._console_cursor :]
        network_slice = self._network_events[self._network_cursor :]
        self._console_cursor = len(self._console_events)
        self._network_cursor = len(self._network_events)
        return console_slice + self._page_errors, network_slice

    def _on_console(self, message) -> None:
        if message.type == "error":
            self._console_events.append(f"console.error: {message.text}")

    def _on_request_failed(self, request) -> None:
        failure = request.failure
        details = failure["errorText"] if isinstance(failure, dict) and "errorText" in failure else "unknown"
        self._network_events.append(f"requestfailed: {request.method} {request.url} ({details})")

    def _on_page_error(self, exc) -> None:
        self._page_errors.append(f"pageerror: {exc}")

    def _extract_interactive_elements(self) -> list[InteractiveElement]:
        raw_elements: list[dict[str, Any]] = self.page.evaluate(
            """
            () => {
              function toXPath(node) {
                if (!node || node.nodeType !== Node.ELEMENT_NODE) return '';
                if (node.id) return `//*[@id="${node.id.replace(/"/g, '\\"')}"]`;
                const parts = [];
                let current = node;
                while (current && current.nodeType === Node.ELEMENT_NODE) {
                  let index = 1;
                  let sibling = current.previousElementSibling;
                  while (sibling) {
                    if (sibling.tagName === current.tagName) index += 1;
                    sibling = sibling.previousElementSibling;
                  }
                  parts.unshift(`${current.tagName.toLowerCase()}[${index}]`);
                  current = current.parentElement;
                }
                return '/' + parts.join('/');
              }

              const selectors = 'a, button, input, textarea, select, [role="button"], [onclick], summary, [tabindex]';
              const candidates = Array.from(document.querySelectorAll(selectors));

              return candidates
                .map((el) => {
                  const rect = el.getBoundingClientRect();
                  const style = window.getComputedStyle(el);
                  const visible = rect.width > 2 && rect.height > 2 && style.visibility !== 'hidden' && style.display !== 'none';
                  const enabled = !(el.disabled || el.getAttribute('aria-disabled') === 'true');
                  const text = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 120);
                  const form = el.closest('form');

                  return {
                    tag: el.tagName.toLowerCase(),
                    selector: `xpath=${toXPath(el)}`,
                    text,
                    element_type: (el.getAttribute('type') || '').toLowerCase(),
                    name: el.getAttribute('name') || '',
                    placeholder: el.getAttribute('placeholder') || '',
                    aria_label: el.getAttribute('aria-label') || '',
                    href: el.getAttribute('href') || '',
                    role: el.getAttribute('role') || '',
                    form_selector: form ? `xpath=${toXPath(form)}` : '',
                    visible,
                    enabled,
                  };
                })
                .filter((item) => item.visible && item.enabled)
                .slice(0, 250);
            }
            """
        )

        elements: list[InteractiveElement] = []
        for item in raw_elements:
            key_source = "|".join(
                [
                    item.get("tag", ""),
                    item.get("selector", ""),
                    item.get("text", ""),
                    item.get("element_type", ""),
                    item.get("name", ""),
                ]
            )
            key = hashlib.sha1(key_source.encode("utf-8")).hexdigest()[:16]
            elements.append(
                InteractiveElement(
                    key=key,
                    tag=item.get("tag", ""),
                    selector=item.get("selector", ""),
                    text=item.get("text", ""),
                    element_type=item.get("element_type", ""),
                    name=item.get("name", ""),
                    placeholder=item.get("placeholder", ""),
                    aria_label=item.get("aria_label", ""),
                    href=item.get("href", ""),
                    role=item.get("role", ""),
                    form_selector=item.get("form_selector", ""),
                    visible=bool(item.get("visible", True)),
                    enabled=bool(item.get("enabled", True)),
                )
            )

        elements.sort(key=lambda e: (e.tag, e.selector))
        return elements
