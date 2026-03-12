"""
Playwright-based Computer implementation for ADK ComputerUseToolset.

Adapted from: https://github.com/google/adk-python/tree/main/contributing/samples/computer_use

This module provides a browser interface that the Gemini Computer Use model
can control via screenshots, clicks, typing, and scrolling.
"""

import asyncio
import time
from typing import Literal, Optional

from google.adk.tools.computer_use.base_computer import (
    BaseComputer,
    ComputerEnvironment,
    ComputerState,
)
from playwright.async_api import async_playwright
import termcolor
from typing_extensions import override

PLAYWRIGHT_KEY_MAP = {
    "backspace": "Backspace",
    "tab": "Tab",
    "return": "Enter",
    "enter": "Enter",
    "shift": "Shift",
    "control": "Control",
    "alt": "Alt",
    "escape": "Escape",
    "space": "Space",
    "pageup": "PageUp",
    "pagedown": "PageDown",
    "end": "End",
    "home": "Home",
    "left": "ArrowLeft",
    "up": "ArrowUp",
    "right": "ArrowRight",
    "down": "ArrowDown",
    "insert": "Insert",
    "delete": "Delete",
    "f1": "F1", "f2": "F2", "f3": "F3", "f4": "F4",
    "f5": "F5", "f6": "F6", "f7": "F7", "f8": "F8",
    "f9": "F9", "f10": "F10", "f11": "F11", "f12": "F12",
    "command": "Meta",
}


class PlaywrightComputer(BaseComputer):
    """Controls Chromium via Playwright for the ADK ComputerUseToolset."""

    def __init__(
        self,
        screen_size: tuple[int, int],
        initial_url: str = "https://www.google.com",
        user_data_dir: Optional[str] = None,
    ):
        self._initial_url = initial_url
        self._screen_size = screen_size
        self._user_data_dir = user_data_dir

    @override
    async def initialize(self):
        self._playwright = await async_playwright().start()
        browser_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-gpu",
        ]

        if self._user_data_dir:
            self._context = await self._playwright.chromium.launch_persistent_context(
                self._user_data_dir,
                headless=False,
                args=browser_args,
            )
            self._browser = self._context.browser
        else:
            self._browser = await self._playwright.chromium.launch(
                args=browser_args,
                headless=False,
            )
            self._context = await self._browser.new_context()

        if not self._context.pages:
            self._page = await self._context.new_page()
            await self._page.goto(self._initial_url)
        else:
            self._page = self._context.pages[0]

        await self._page.set_viewport_size({
            "width": self._screen_size[0],
            "height": self._screen_size[1],
        })
        termcolor.cprint("Playwright browser started.", color="green", attrs=["bold"])

    @override
    async def environment(self):
        return ComputerEnvironment.ENVIRONMENT_BROWSER

    @override
    async def close(self, exc_type, exc_val, exc_tb):
        if self._context:
            await self._context.close()
        try:
            if self._browser:
                await self._browser.close()
        except Exception:
            pass
        await self._playwright.stop()

    async def click_at(self, x: int, y: int):
        await self._page.mouse.click(x, y)
        await self._page.wait_for_load_state()
        return await self.current_state()

    async def hover_at(self, x: int, y: int):
        await self._page.mouse.move(x, y)
        await self._page.wait_for_load_state()
        return await self.current_state()

    async def type_text_at(
        self, x: int, y: int, text: str,
        press_enter: bool = True, clear_before_typing: bool = True,
    ) -> ComputerState:
        await self._page.mouse.click(x, y)
        await self._page.wait_for_load_state()
        if clear_before_typing:
            await self.key_combination(["Control", "A"])
            await self.key_combination(["Delete"])
        await self._page.keyboard.type(text)
        await self._page.wait_for_load_state()
        if press_enter:
            await self.key_combination(["Enter"])
        await self._page.wait_for_load_state()
        return await self.current_state()

    async def scroll_document(self, direction: Literal["up", "down", "left", "right"]) -> ComputerState:
        if direction == "down":
            return await self.key_combination(["PageDown"])
        elif direction == "up":
            return await self.key_combination(["PageUp"])
        else:
            amount = self._screen_size[0] // 2
            sign = "-" if direction == "left" else ""
            await self._page.evaluate(f"window.scrollBy({sign}{amount}, 0)")
            await self._page.wait_for_load_state()
            return await self.current_state()

    async def scroll_at(self, x: int, y: int, direction: Literal["up", "down", "left", "right"], magnitude: int) -> ComputerState:
        await self._page.mouse.move(x, y)
        dx, dy = 0, 0
        if direction == "up": dy = -magnitude
        elif direction == "down": dy = magnitude
        elif direction == "left": dx = -magnitude
        elif direction == "right": dx = magnitude
        await self._page.mouse.wheel(dx, dy)
        await self._page.wait_for_load_state()
        return await self.current_state()

    async def wait(self, seconds: int) -> ComputerState:
        await asyncio.sleep(seconds)
        return await self.current_state()

    async def go_back(self) -> ComputerState:
        await self._page.go_back()
        await self._page.wait_for_load_state()
        return await self.current_state()

    async def go_forward(self) -> ComputerState:
        await self._page.go_forward()
        await self._page.wait_for_load_state()
        return await self.current_state()

    async def navigate(self, url: str) -> ComputerState:
        await self._page.goto(url)
        await self._page.wait_for_load_state()
        return await self.current_state()

    async def key_combination(self, keys: list[str]) -> ComputerState:
        keys = [PLAYWRIGHT_KEY_MAP.get(k.lower(), k) for k in keys]
        for key in keys[:-1]:
            await self._page.keyboard.down(key)
        await self._page.keyboard.press(keys[-1])
        for key in reversed(keys[:-1]):
            await self._page.keyboard.up(key)
        return await self.current_state()

    async def drag_and_drop(self, x: int, y: int, dest_x: int, dest_y: int) -> ComputerState:
        await self._page.mouse.move(x, y)
        await self._page.mouse.down()
        await self._page.mouse.move(dest_x, dest_y)
        await self._page.mouse.up()
        return await self.current_state()

    async def current_state(self) -> ComputerState:
        await self._page.wait_for_load_state()
        time.sleep(0.5)
        screenshot_bytes = await self._page.screenshot(type="png", full_page=False)
        return ComputerState(screenshot=screenshot_bytes, url=self._page.url)

    async def screen_size(self) -> tuple[int, int]:
        return self._screen_size
