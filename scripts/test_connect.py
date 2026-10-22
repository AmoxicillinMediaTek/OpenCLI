#!/usr/bin/env python3
"""Tests for the /connect panel.

Run with: npm test   (or: python3 scripts/test_connect.py)
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import ai_cli  # noqa: E402
from ai_cli import ApiKeyScreen, ConnectScreen, PROVIDERS  # noqa: E402
from textual.widgets import Button, Input, Label, OptionList  # noqa: E402

failed = 0


def check(label, ok, detail=""):
    global failed
    print(("ok   " if ok else "FAIL ") + label + (("  -> " + str(detail)) if not ok else ""))
    if not ok:
        failed += 1


def labels(screen):
    out = []
    for widget in screen.query(Label):
        text = str(widget.content)
        if text:
            out.append(text)
    return out


async def open_panel(pilot):
    await pilot.press(*"/connect")
    await pilot.press("enter")
    await pilot.pause()


async def main():
    # never write to the real config while testing
    written = []
    ai_cli.save_config = lambda cfg: written.append(dict(cfg))

    app = ai_cli.AIChat()
    app.cfg["api_key"] = "old-key"
    async with app.run_test() as pilot:
        await open_panel(pilot)
        check("/connect opens the panel", isinstance(app.screen, ConnectScreen), type(app.screen).__name__)

        panel = app.screen
        check("the panel is titled", "Connect an integration" in labels(panel), labels(panel))
        check("there is an esc button", len(panel.query("#esc")) == 1)
        check("there is a search box", len(panel.query("#search")) == 1)
        check("no popular section", not any("Popular" in t for t in labels(panel)), labels(panel))

        options = panel.query_one("#providers", OptionList)
        check("the provider list is not empty", options.option_count == len(PROVIDERS), options.option_count)
        ids = [options.get_option_at_index(i).id for i in range(options.option_count)]
        check("openrouter is offered", "openrouter" in ids, ids)
        check("no other provider is offered", len(ids) == 1, ids)

        # escape closes it
        await pilot.press("escape")
        await pilot.pause()
        check("escape closes the panel", not isinstance(app.screen, ConnectScreen), type(app.screen).__name__)

        # the esc button closes it too
        await open_panel(pilot)
        check("the panel opened again", isinstance(app.screen, ConnectScreen))
        await pilot.click("#esc")
        await pilot.pause()
        check("the esc button closes the panel", not isinstance(app.screen, ConnectScreen), type(app.screen).__name__)

        # enter asks for the api key
        await open_panel(pilot)
        await pilot.press("enter")
        await pilot.pause()
        check("enter asks for the api key", isinstance(app.screen, ApiKeyScreen), type(app.screen).__name__)

        key_screen = app.screen
        check("the key screen is titled", "Connect OpenRouter" in labels(key_screen), labels(key_screen))
        check("the key screen has an esc button", len(key_screen.query("#esc")) == 1)
        check("the key screen has a key box", len(key_screen.query("#key")) == 1)
        check("the key screen says submit enter", "submit enter" in labels(key_screen), labels(key_screen))

        # escape leaves the key alone
        await pilot.press("escape")
        await pilot.pause()
        check("escape closes the key screen", not isinstance(app.screen, ApiKeyScreen), type(app.screen).__name__)
        check("the key was not changed", app.cfg["api_key"] == "old-key", app.cfg["api_key"])

        # entering a key connects
        await open_panel(pilot)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press(*"sk-or-v1-testkey")
        await pilot.press("enter")
        await pilot.pause()
        check("both panels closed", not isinstance(app.screen, (ConnectScreen, ApiKeyScreen)), type(app.screen).__name__)
        check("the key was saved", app.cfg["api_key"] == "sk-or-v1-testkey", app.cfg["api_key"])
        check("the provider was saved", app.cfg["provider"] == "openrouter", app.cfg["provider"])
        check("the config was written", written and written[-1]["api_key"] == "sk-or-v1-testkey", written)

    print("")
    if failed:
        print(f"{failed} check(s) failed")
        sys.exit(1)
    print("all checks passed")


asyncio.run(main())
