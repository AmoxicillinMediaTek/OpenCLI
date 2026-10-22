#!/usr/bin/env python3
"""Make sure the Python packages the AI CLI needs are installed.

Called by the npm postinstall hook. It never fails the install: when it cannot
install anything it just prints the command to run by hand.
"""
import subprocess
import sys

NEEDED = ("textual", "httpx")


def missing():
    """Return the packages that are not importable yet."""
    out = []
    for mod in NEEDED:
        try:
            __import__(mod)
        except Exception:  # noqa: BLE001
            out.append(mod)
    return out


def run(cmd, label):
    print("ai-cli: " + label, flush=True)
    try:
        return subprocess.run(cmd).returncode == 0
    except Exception as exc:  # noqa: BLE001
        print("ai-cli: " + label + " failed: " + str(exc), flush=True)
        return False


def pip_install(pkgs):
    base = [sys.executable, "-m", "pip", "install", "--user", "--disable-pip-version-check"]
    if run(base + pkgs, "installing " + " ".join(pkgs) + " with pip..."):
        return True
    # Newer pip refuses --user on PEP 668 "externally managed" systems.
    return run(
        base + ["--break-system-packages"] + pkgs,
        "installing " + " ".join(pkgs) + " with pip (--break-system-packages)...",
    )


def micropip_install(pkgs):
    """Termux fallback: micropip can install wheels without a compiler."""
    code = (
        "import asyncio, micropip\n"
        "asyncio.run(micropip.install(" + repr(list(pkgs)) + "))\n"
    )
    return run(
        [sys.executable, "-c", code],
        "installing " + " ".join(pkgs) + " with micropip...",
    )


def main():
    need = missing()
    if not need:
        print("ai-cli: python dependencies are ready.")
        return 0

    if pip_install(need) or micropip_install(need):
        return 0

    print("")
    print("ai-cli: could not install the Python dependencies automatically.")
    print("ai-cli: run this yourself, then start the CLI again:")
    print("")
    print("    pip install textual httpx")
    print("")
    return 0


if __name__ == "__main__":
    sys.exit(main())
