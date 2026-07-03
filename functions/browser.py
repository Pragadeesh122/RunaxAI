import json
import os
import logging
import asyncio
import base64
import tempfile
from datetime import datetime
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from clients import llm_client
from prompts.browser_agent import BROWSER_AGENT, BROWSER_VISION_FALLBACK
from llm.response_utils import extract_first_text

logger = logging.getLogger("browser-agent")

# Screenshots are transient inputs for the vision fallback, not artifacts.
# They must live under tempdir: the prod containers run with a read-only
# root filesystem where only /tmp is writable, so a repo-relative path
# (the old "browser_screenshots") fails with EROFS.
SCREENSHOTS_DIR = os.getenv(
    "BROWSER_SCREENSHOTS_DIR",
    os.path.join(tempfile.gettempdir(), "browser_screenshots"),
)
ACTION_TIMEOUT = 5000  # 5s per action — fail fast, don't hang
MAX_ACTIONS = 15  # safety limit to prevent infinite loops
DEFAULT_HEADLESS = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() != "false"

SCHEMA = {
    "type": "function",
    "function": {
        "name": "browser_task",
        "description": (
            "Control a real browser to visit websites, fill out forms, click buttons, "
            "and extract information from any page. Use this when you need to interact "
            "with a website directly — login forms, multi-step forms, dynamic pages, "
            "or anything that requires actual browser interaction. Do not use it for a simple "
            "page read when crawl_website is enough. Run it step-by-step rather than in parallel "
            "with other dependent tools. It returns a plain-text action history and outcome summary."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to navigate to",
                },
                "goal": {
                    "type": "string",
                    "description": (
                        "What to accomplish on the page, e.g. "
                        "'Fill the contact form with name=test, email=test@test.com and submit it'"
                    ),
                },
            },
            "required": ["url", "goal"],
        },
    },
}

CACHEABLE = False
POLICY = {
    "execution_mode": "sequential_first",
    "max_parallel_instances": 1,
    "requires_fresh_input": True,
    "dedupe_key_fields": ("url", "goal"),
    "verification_only_after_result": True,
}


def _decide_next(goal: str, ax_tree: str, history: list[str]) -> dict:
    """Ask LLM what to do next given the current page state."""
    history_str = "\n".join(f"  {i + 1}. {h}" for i, h in enumerate(history))

    user = f"""Goal: {goal}

Actions taken so far:
{history_str if history else "  (none yet — this is the first action)"}

Current page accessibility tree:
{ax_tree}

What is the next action to take?"""

    response = llm_client.chat.completions.create(
        model="claude-haiku-4-5",
        messages=[
            {"role": "system", "content": BROWSER_AGENT},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
    )

    return json.loads(extract_first_text(response, "{}"))


async def _locate(page, action: dict):
    """Resolve an action to a Playwright locator."""
    role = action.get("role", "")
    name = action.get("name", "")

    if role and name:
        return page.get_by_role(role, name=name)
    if role:
        return page.get_by_role(role)
    raise ValueError(f"action missing role: {action}")


async def _execute(page, action: dict) -> str:
    """Execute a single action with a short timeout."""
    act = action.get("action", "")
    value = action.get("value", "")

    locator = await _locate(page, action)

    match act:
        case "fill":
            await locator.fill(value, timeout=ACTION_TIMEOUT)
            return f"filled {action['role']}[{action['name']}] with '{value}'"

        case "click":
            await locator.click(timeout=ACTION_TIMEOUT)
            await page.wait_for_load_state("networkidle", timeout=ACTION_TIMEOUT)
            return f"clicked {action['role']}[{action['name']}]"

        case "select":
            await locator.select_option(value, timeout=ACTION_TIMEOUT)
            return f"selected '{value}' in {action['role']}[{action['name']}]"

        case "check":
            await locator.check(timeout=ACTION_TIMEOUT)
            return f"checked {action['role']}[{action['name']}]"

        case _:
            raise ValueError(f"unknown action: {act}")


async def _save_screenshot(page, label: str) -> str:
    """Save a screenshot to disk."""
    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_label = "".join(c if c.isalnum() or c in "-_" else "_" for c in label[:40])
    path = os.path.join(SCREENSHOTS_DIR, f"{timestamp}_{safe_label}.png")
    await page.screenshot(path=path, type="png")
    logger.info(f"screenshot saved: {path}")
    return path


async def _vision_fallback(page, goal: str, history: list[str], error: str) -> dict:
    """Screenshot → vision model → action when AX tree approach fails."""
    path = await _save_screenshot(page, "vision_fallback")
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    history_str = "\n".join(f"  {i + 1}. {h}" for i, h in enumerate(history))

    response = llm_client.chat.completions.create(
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    },
                    {
                        "type": "text",
                        "text": BROWSER_VISION_FALLBACK.format(
                            goal=goal,
                            history=history_str if history else "  (none)",
                            error=error,
                        ),
                    },
                ],
            }
        ],
        response_format={"type": "json_object"},
    )

    return json.loads(extract_first_text(response, "{}"))


async def _run_browser_task(url: str, goal: str) -> str:
    """Autonomous browser agent — loops: snapshot → decide → act until done."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=DEFAULT_HEADLESS,
            ignore_default_args=["--enable-automation"],
            # --disable-dev-shm-usage: k8s pods get a 64MB /dev/shm by
            # default; Chromium crashes on heavy pages unless it falls back
            # to /tmp for shared memory.
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()
        history = []

        try:
            logger.info(f"navigating to {url}")
            await page.goto(url, wait_until="networkidle", timeout=15000)

            for step in range(MAX_ACTIONS):
                # Snapshot the current page
                ax_tree = await page.locator(":root").aria_snapshot()

                # Ask LLM what to do next
                action = _decide_next(goal, ax_tree, history)
                logger.info(
                    f"action {step + 1}: {action.get('action')} {action.get('role', '')}"
                    f"[{action.get('name', '')}] — {action.get('reasoning', '')[:80]}"
                )

                # Check if done
                if action.get("action") == "done":
                    summary = action.get("summary", "goal completed")
                    logger.info(f"done: {summary}")
                    history.append(f"DONE — {summary}")
                    await _save_screenshot(page, "done")
                    break

                # Execute the action
                try:
                    result = await _execute(page, action)
                    history.append(result)
                    # Only screenshot after navigation (click), not after fills
                    if action.get("action") == "click":
                        await _save_screenshot(page, f"action_{step + 1}")
                    await page.wait_for_timeout(500)

                except Exception as e:
                    error_msg = str(e)
                    logger.warning(f"action failed: {error_msg}")
                    history.append(
                        f"FAILED: {action.get('action')} {action.get('role', '')}[{action.get('name', '')}] — {error_msg}"
                    )

                    # Try vision fallback
                    try:
                        fallback_action = await _vision_fallback(
                            page, goal, history, error_msg
                        )
                        if fallback_action.get("action") == "done":
                            history.append(
                                f"DONE — {fallback_action.get('summary', '')}"
                            )
                            break
                        result = await _execute(page, fallback_action)
                        history.append(f"(via screenshot) {result}")
                        await _save_screenshot(page, f"action_{step + 1}_fallback")
                    except Exception as e2:
                        logger.error(f"vision fallback also failed: {e2}")
                        history.append(f"FAILED (fallback): {e2}")
            else:
                logger.warning(f"hit max actions ({MAX_ACTIONS})")

        except PlaywrightTimeout:
            history.append(f"navigation timeout: {url} took too long to load")
        except Exception as e:
            logger.error(f"browser session failed: {e}")
            history.append(f"browser error: {e}")
        finally:
            await browser.close()

    return "\n".join(history)


def browser_task(url: str, goal: str) -> str:
    """Sync wrapper — bridges async Playwright into sync tool execution."""
    return asyncio.run(_run_browser_task(url, goal))
