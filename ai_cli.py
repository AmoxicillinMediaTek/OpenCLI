#!/usr/bin/env python3
"""
Enzo - a Textual chat app for Termux / Acode that talks to OpenRouter.

Install with npm:
    npm install -g @enzorenz/enzocli

Or with pip:
    pkg install python
    python -m pip install textual httpx

Run (cd into the project you want the AI to see FIRST):
    cd ~/my-project
    enzo

Add your API key inside the app:
    /key sk-or-v1-xxxxxxxx
(or set the OPENROUTER_API_KEY environment variable, or edit the config file)
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Termux: rich's markdown support needs markdown-it-py. Install it on first
# run when it is missing. Other platforms just skip this block.
try:  # pragma: no cover - Termux only
    import markdown_it  # noqa: F401
except ImportError:
    try:
        import asyncio as _asyncio
        import micropip as _micropip

        _asyncio.run(_micropip.install("markdown-it-py"))
    except Exception:  # noqa: BLE001
        pass

import httpx
from rich.markdown import Markdown as RichMarkdown
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Header, Input, Label, OptionList, Rule, Static
from textual.widgets.option_list import Option
from textual.binding import Binding
from textual.timer import Timer

API_URL = "https://openrouter.ai/api/v1/chat/completions"
IMAGES_URL = "https://openrouter.ai/api/v1/images"
MODELS_URL = "https://openrouter.ai/api/v1/models"
CONFIG_PATH = Path.home() / ".config" / "ai-cli" / "config.json"

# Providers the /connect panel offers. Each one needs a name, a short blurb,
# where to get a key, and the urls to talk to.
PROVIDERS: dict[str, dict] = {
    "openrouter": {
        "name": "OpenRouter",
        "blurb": "openrouter.ai",
        "key_hint": "sk-or-v1-...",
        "key_url": "https://openrouter.ai/settings/keys",
        "chat": "https://openrouter.ai/api/v1/chat/completions",
        "images": "https://openrouter.ai/api/v1/images",
        "models": "https://openrouter.ai/api/v1/models",
    },
}
DEFAULT_PROVIDER = "openrouter"

# The directory the AI works in. /cd moves it; the AI can only read inside it.
ROOT = Path.cwd().resolve()


def set_root(path: Path) -> None:
    """Point the sandbox and the AI at a new working directory."""
    global ROOT
    ROOT = path


def set_provider(name: str) -> dict:
    """Switch to another provider and return its settings."""
    global API_URL, IMAGES_URL, MODELS_URL
    provider = PROVIDERS.get(name) or PROVIDERS[DEFAULT_PROVIDER]
    API_URL = provider["chat"]
    IMAGES_URL = provider["images"]
    MODELS_URL = provider["models"]
    return provider

MAX_TOOL_ROUNDS = 12       # max back-and-forth tool steps per question
MAX_LIST_ENTRIES = 300     # max entries returned by list_directory
MAX_LIST_DEPTH = 3         # max depth for recursive listings
MAX_READ_BYTES = 1_000_000  # never read more than this from disk
MAX_READ_CHARS = 20_000    # max characters returned to the AI per read
MAX_OUTPUT_CHARS = 20_000  # max command output returned / displayed
MAX_THINK_CHARS = 6_000   # max characters of reasoning text shown in the chat
RENDER_INTERVAL = 0.08   # seconds between repaints while text streams in
DEFAULT_CMD_TIMEOUT = 60   # seconds a shell command may run by default
MAX_CMD_TIMEOUT = 300      # upper bound for the timeout parameter
AUTO_COMPACT_THRESHOLD = 30_000  # compact context when history exceeds this many chars
AUTO_COMPACT_KEEP = 4        # number of recent history messages to keep intact
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".idea"}

# Slash commands shown in the suggestion dropdown (order = display order)
COMMANDS = [
    ("/help", "list all commands"),
    ("/model", "show or set the model"),
    ("/models", "search available models"),
    ("/key", "show or set the API key"),
    ("/system", "show or set the system prompt"),
    ("/tools", "AI file & command access: /tools on|off"),
    ("/dir", "show working directory and file access"),
    ("/cd", "change the directory the AI works in"),
    ("/clear", "clear the conversation"),
    ("/interrupt", "stop the current AI reply"),
    ("/restart", "restart the CLI"),
    ("/update", "update Enzo from npm"),
    ("/connect", "connect another provider"),
    ("/autocompact", "auto-compact context: on|off"),
    ("/exit", "quit (also /quit)"),
]
ARG_COMMANDS = {"/tools", "/key", "/model", "/system", "/models", "/autocompact", "/cd"}

# Tools whose result is worth showing to the user in the chat (short / important).
SHOW_RESULT_TOOLS = {"run_command", "write_file", "delete_path", "rename_path", "make_directory"}

DEFAULT_CONFIG = {
    "api_key": "",
    "provider": DEFAULT_PROVIDER,
    "model": "openrouter/free",
    "system": "You are a capable coding assistant. Keep answers concise and readable in a small terminal. "
              "When asked to change files or run commands, do it with your tools instead of only describing it.",
    "tools": True,
    "autocompact": True,
}

HELP_TEXT = """**Commands**
- `/key <api-key>`   save your OpenRouter API key
- `/model <id>`      set the model (e.g. `openai/gpt-4o-mini`)
- `/models <query>`  search available models
- `/system <text>`   set the system prompt
- `/dir`             show the directory the AI works in
- `/cd <dir>`        work in another directory (also `..`)
- `/tools on|off`    let the AI read/write files and run commands in that directory
- `/interrupt`       stop the AI while it is replying
- `/clear`           clear the conversation
- `/restart`         restart the CLI
- `/update`         install the latest Enzo from npm
- `/connect`       connect another provider
- `/autocompact on|off`   auto-compact context when it gets large
- `/help`            show this help
- `/exit` or `/quit` leave the CLI"""


def access_label(on: bool) -> str:
    return "**on** (read, write & commands)" if on else "**off**"


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    try:
        cfg.update(json.loads(CONFIG_PATH.read_text()))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    env_key = os.environ.get("OPENROUTER_API_KEY")
    if env_key and not cfg["api_key"]:
        cfg["api_key"] = env_key
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    try:
        CONFIG_PATH.chmod(0o600)  # keep the key private
    except OSError:
        pass


# --------------------------------------------------------------------------
# Directory tools (read-only, sandboxed to ROOT)
# --------------------------------------------------------------------------
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": (
                "List files and folders in a directory of the user's project. "
                "Paths are relative to the project root. Use recursive=true to see a tree."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path, default '.'"},
                    "recursive": {"type": "boolean", "description": "List subfolders too (max 3 levels)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read a text file from the user's project. Returns numbered lines. "
                "Use start_line/end_line to read part of a large file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to the project root"},
                    "start_line": {"type": "integer", "description": "First line to read (1-based)"},
                    "end_line": {"type": "integer", "description": "Last line to read (inclusive)"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Create a new file or overwrite an existing one in the user's project. "
                "Read a file first if you only want to change part of it. "
                "Missing parent folders are created automatically."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to the project root"},
                    "content": {"type": "string", "description": "Full text content to write"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "make_directory",
            "description": "Create a folder (and any missing parent folders) in the user's project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Folder path relative to the project root"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rename_path",
            "description": "Rename or move a file or folder. Fails if the destination already exists.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Existing file/folder path relative to the project root"},
                    "new_path": {"type": "string", "description": "New path relative to the project root"},
                },
                "required": ["path", "new_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_path",
            "description": (
                "Permanently delete a file or folder (folders are removed with everything inside). "
                "Use with care - there is no undo."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relative to the project root"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Run a shell command inside the project directory and return its output. "
                "Non-interactive only: no password prompts, no full-screen editors."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The shell command to run"},
                    "timeout": {
                        "type": "integer",
                        "description": f"Seconds to wait before killing it (1-{MAX_CMD_TIMEOUT}, default {DEFAULT_CMD_TIMEOUT})",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": (
                "Generate an image from a text prompt and save it to the project directory."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Text description of the image"},
                    "filename": {"type": "string", "description": "Filename relative to project root, e.g. images/out.png"},
                    "model": {"type": "string", "description": "Image model, default bytedance-seed/seedream-4.5"},
                    "output_format": {"type": "string", "description": "png, jpeg, webp"}
                },
                "required": ["prompt", "filename"]
            }
        }
    },
]



def safe_path(p: str) -> Path:
    """Resolve p inside ROOT, refusing anything that escapes it (incl. via symlinks)."""
    target = (ROOT / (p or ".")).resolve()
    if target != ROOT and ROOT not in target.parents:
        raise ValueError("path is outside the working directory")
    try:
        if target == CONFIG_PATH.resolve():
            raise ValueError("access to the CLI config file is blocked")
    except OSError:
        pass
    return target


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n}B"


def tool_list_directory(path: str = ".", recursive: bool = False) -> str:
    base = safe_path(path)
    if not base.exists():
        raise FileNotFoundError(f"{path} does not exist")
    if not base.is_dir():
        raise NotADirectoryError(f"{path} is not a directory")

    lines: list[str] = []
    truncated = False

    def walk(d: Path, depth: int) -> None:
        nonlocal truncated
        try:
            entries = sorted(d.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except (PermissionError, OSError):
            return
        for e in entries:
            if len(lines) >= MAX_LIST_ENTRIES:
                truncated = True
                return
            rel = e.relative_to(ROOT) if e.is_relative_to(ROOT) else e
            if e.is_dir():
                lines.append(f"{rel}/")
                if (
                    recursive
                    and depth < MAX_LIST_DEPTH
                    and e.name not in SKIP_DIRS
                    and not e.is_symlink()
                ):
                    walk(e, depth + 1)
            else:
                try:
                    size = human_size(e.stat().st_size)
                except OSError:
                    size = "?"
                lines.append(f"{rel}  ({size})")

    walk(base, 1)
    shown = "." if base == ROOT else str(base.relative_to(ROOT))
    if not lines:
        return f"{shown}/ is empty"
    out = f"Contents of {shown}/:\n" + "\n".join(lines)
    if truncated:
        out += f"\n... truncated at {MAX_LIST_ENTRIES} entries"
    return out


def tool_read_file(path: str, start_line: int = 1, end_line: int | None = None) -> str:
    target = safe_path(path)
    if not target.exists():
        raise FileNotFoundError(f"{path} does not exist")
    if not target.is_file():
        raise IsADirectoryError(f"{path} is not a file (use list_directory)")

    with open(target, "rb") as f:
        data = f.read(MAX_READ_BYTES + 1)
    if b"\x00" in data[:2048]:
        raise ValueError("binary file, cannot display")
    clipped_disk = len(data) > MAX_READ_BYTES
    text = data[:MAX_READ_BYTES].decode("utf-8", errors="replace")

    all_lines = text.splitlines()
    total = len(all_lines)
    start = max(1, int(start_line or 1))
    end = min(total, int(end_line)) if end_line else total
    if total and start > total:
        raise ValueError(f"start_line {start} is beyond the end of the file ({total} lines)")

    out_lines = []
    used = 0
    last = start - 1
    for n in range(start, end + 1):
        row = f"{n}: {all_lines[n - 1]}"
        if used + len(row) > MAX_READ_CHARS:
            break
        out_lines.append(row)
        used += len(row) + 1
        last = n

    shown = str(target.relative_to(ROOT))
    header = f"{shown} (lines {start}-{last} of {total})"
    body = "\n".join(out_lines) if out_lines else "(empty file)"
    notes = ""
    if last < end:
        notes += f"\n... output truncated; continue with start_line={last + 1}"
    if clipped_disk:
        notes += "\n... file is very large; only the first 1 MB was read"
    return f"{header}\n{body}{notes}"


def tool_write_file(path: str, content: str | None = None) -> str:
    content = "" if content is None else str(content)
    target = safe_path(path)
    if target.is_dir():
        raise IsADirectoryError(f"{path} is a folder, not a file")
    target.parent.mkdir(parents=True, exist_ok=True)
    existed = target.exists()
    with open(target, "w", encoding="utf-8", newline="") as f:
        f.write(content)
    lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
    action = "overwrote" if existed else "created"
    return f"{action} {target.relative_to(ROOT)} ({lines} lines, {human_size(len(content.encode('utf-8')))})"


def tool_make_directory(path: str) -> str:
    target = safe_path(path)
    existed = target.exists()
    target.mkdir(parents=True, exist_ok=True)
    rel = target.relative_to(ROOT)
    return f"{'already exists' if existed else 'created'} directory {rel}"


def tool_rename_path(path: str, new_path: str) -> str:
    src = safe_path(path)
    if src == ROOT:
        raise ValueError("cannot rename the project root")
    if not new_path or not str(new_path).strip():
        raise ValueError("'new_path' is required")
    dst = safe_path(str(new_path))
    if not src.exists() and not src.is_symlink():
        raise FileNotFoundError(f"{path} does not exist")
    if dst == src:
        raise ValueError("source and destination are the same")
    if dst.exists() or dst.is_symlink():
        raise FileExistsError(f"{new_path} already exists; delete it first if you want to replace it")
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    return f"renamed {src.relative_to(ROOT)} -> {dst.relative_to(ROOT)}"


def tool_delete_path(path: str) -> str:
    target = safe_path(path)
    if target == ROOT:
        raise ValueError("refusing to delete the project root")
    if not target.exists() and not target.is_symlink():
        raise FileNotFoundError(f"{path} does not exist")
    rel = target.relative_to(ROOT)
    if target.is_dir() and not target.is_symlink():
        shutil.rmtree(target)
        return f"deleted directory {rel} (with all contents)"
    target.unlink()
    return f"deleted {rel}"


def tool_run_command(command: str, timeout: int | None = None) -> str:
    command = str(command or "").strip()
    if not command:
        raise ValueError("command is required")
    try:
        timeout = max(1, min(int(timeout or DEFAULT_CMD_TIMEOUT), MAX_CMD_TIMEOUT))
    except (TypeError, ValueError):
        timeout = DEFAULT_CMD_TIMEOUT
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") + (e.stderr or "")
        if isinstance(out, bytes):
            out = out.decode("utf-8", errors="replace")
        out = out[:MAX_OUTPUT_CHARS].rstrip()
        head = f"(timed out after {timeout}s and was killed)"
        return f"{head}\n{out}" if out else head

    text = proc.stdout or ""
    if proc.stderr:
        text = (text + ("\n" if text else "") + "[stderr]\n" + proc.stderr).strip()
    if len(text) > MAX_OUTPUT_CHARS:
        half = MAX_OUTPUT_CHARS // 2
        text = text[:half] + f"\n... output truncated at {MAX_OUTPUT_CHARS} chars ...\n" + text[-half:]
    return f"{text}\n[exit code {proc.returncode}]" if text else f"(no output)\n[exit code {proc.returncode}]"


def tool_generate_image(prompt: str, filename: str, model: str = "bytedance-seed/seedream-4.5", output_format: str = "png") -> str:
    if not prompt:
        raise ValueError("prompt is required")
    if not filename:
        raise ValueError("filename is required")
    target = safe_path(filename)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"model": model, "prompt": prompt, "output_format": output_format}
    headers = {
        "Authorization": f"Bearer {load_config().get('api_key','')}",
        "Content-Type": "application/json",
    }
    import httpx
    try:
        r = httpx.post(IMAGES_URL, headers=headers, json=payload, timeout=120.0)
        r.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"Image generation failed: {e}")
    data = r.json()
    if not data.get("data"):
        raise RuntimeError("No image data returned")
    b64 = data["data"][0].get("b64_json") or data["data"][0].get("url")
    if not b64:
        raise RuntimeError("Image data missing")
    # b64 may be data url
    if b64.startswith("data:"):
        b64 = b64.split(",",1)[1]
    import base64
    try:
        img_bytes = base64.b64decode(b64)
    except Exception:
        # maybe url
        import urllib.request
        with urllib.request.urlopen(b64) as resp:
            img_bytes = resp.read()
    target.write_bytes(img_bytes)
    rel = target.relative_to(ROOT)
    return f"saved image to {rel} ({human_size(len(img_bytes))})"

def run_tool(name: str, args_json: str) -> str:
    try:
        args = json.loads(args_json or "{}")
        if not isinstance(args, dict):
            raise ValueError("arguments must be an object")
    except (json.JSONDecodeError, ValueError) as e:
        return f"Error: invalid arguments ({e})"
    try:
        if name == "list_directory":
            return tool_list_directory(args.get("path", "."), bool(args.get("recursive", False)))
        if name == "read_file":
            if "path" not in args:
                return "Error: 'path' is required"
            return tool_read_file(args["path"], args.get("start_line", 1), args.get("end_line"))
        if name == "write_file":
            if "path" not in args:
                return "Error: 'path' is required"
            return tool_write_file(args["path"], args.get("content", ""))
        if name == "make_directory":
            if "path" not in args:
                return "Error: 'path' is required"
            return tool_make_directory(args["path"])
        if name == "rename_path":
            if "path" not in args or "new_path" not in args:
                return "Error: 'path' and 'new_path' are required"
            return tool_rename_path(args["path"], args["new_path"])
        if name == "delete_path":
            if "path" not in args:
                return "Error: 'path' is required"
            return tool_delete_path(args["path"])
        if name == "run_command":
            if "command" not in args:
                return "Error: 'command' is required"
            return tool_run_command(args["command"], args.get("timeout"))
        if name == "generate_image":
            if "prompt" not in args or "filename" not in args:
                return "Error: 'prompt' and 'filename' are required"
            return tool_generate_image(args["prompt"], args["filename"], args.get("model","bytedance-seed/seedream-4.5"), args.get("output_format","png"))
        return f"Error: unknown tool '{name}'"
    except Exception as e:  # noqa: BLE001
        return f"Error: {e}"


def describe_call(name: str, args_json: str) -> str:
    try:
        args = json.loads(args_json or "{}")
        inner = ", ".join(f"{k}={v}" for k, v in args.items())
    except Exception:  # noqa: BLE001
        inner = args_json or ""
    if len(inner) > 70:
        inner = inner[:67] + "..."
    return f"{name}({inner})"


def format_tool_result(name: str, args_json: str, result: str) -> str:
    """Render a tool result for the chat, e.g. the command with its output."""
    if name == "run_command":
        try:
            cmd = json.loads(args_json or "{}").get("command", "")
        except Exception:  # noqa: BLE001
            cmd = ""
        return f"{ROOT}$ {cmd}\n{result}"
    return result


def extract_reasoning(delta: dict) -> str:
    """Pull the model's reasoning text out of a streaming delta.

    OpenRouter sends it as `reasoning`; some providers use `reasoning_content`
    or a list of `reasoning_details`. Only one source is read, otherwise the
    same text would be counted twice.
    """
    for key in ("reasoning", "reasoning_content"):
        val = delta.get(key)
        if isinstance(val, str) and val:
            return val
    details = delta.get("reasoning_details")
    if isinstance(details, list):
        out = ""
        for item in details:
            if isinstance(item, dict):
                text = item.get("text") or item.get("summary") or ""
                if isinstance(text, str) and text:
                    out += text
        if out:
            return out
    return ""


def installed_package_name() -> str:
    """Work out which npm package this copy of the app belongs to.

    The app lives in <global>/@scope/name/ai_cli.py when npm installed it, so
    the package.json next to it holds the name.
    """
    try:
        here = Path(__file__).resolve()
    except OSError:
        return ""
    for parent in here.parents:
        manifest = parent / "package.json"
        if not manifest.is_file():
            continue
        try:
            data = json.loads(manifest.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        name = data.get("name")
        if isinstance(name, str) and name:
            return name
    return ""


class TextStream:
    """Collects streamed text and repairs providers that resend the whole answer.

    Some providers send the full answer in every chunk instead of only the new
    part. Appending that blindly repeats words ("TheThe") and glues them
    together ("TheLets"). This skips the part we already have.
    """

    def __init__(self) -> None:
        self.text = ""

    def feed(self, chunk: str) -> str:
        """Add a chunk of text and return the complete text so far."""
        if not chunk:
            return self.text
        if len(chunk) >= len(self.text):
            # the chunk may repeat what we already have, so skip that part
            overlap = self._overlap(self.text, chunk)
            if overlap:
                self.text += chunk[overlap:]
                return self.text
        self.text += chunk
        return self.text

    @staticmethod
    def _overlap(text: str, chunk: str) -> int:
        """Length of the longest suffix of text that is also a prefix of chunk."""
        for size in range(min(len(text), len(chunk)), 0, -1):
            if text.endswith(chunk[:size]):
                return size
        return 0


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------
class Message(Static):
    """A single chat bubble."""

    DEFAULT_CSS = """
    Message {
        padding: 0 1;
        margin: 0 0 1 0;
        width: 100%;
    }
    Message.user {
        background: $boost;
        border-left: thick $accent;
    }
    Message.assistant {
        border-left: thick $success;
    }
    Message.system {
        color: $text-muted;
        border-left: thick $warning;
    }
    Message.tool {
        color: $text-muted;
        border-left: thick $primary;
        margin: 0 0 0 0;
    }
    Message.error {
        color: $error;
        border-left: thick $error;
    }
    """

    def __init__(self, role: str, text: str = "") -> None:
        super().__init__(classes=role)
        # NOTE: don't name these `role`/`content` - Textual's Static uses `content`
        self.msg_role = role
        self.raw_text = text
        self._dirty = False
        self._timer: Timer | None = None
        self.render_text()

    def render_text(self) -> None:
        if self.msg_role == "user":
            self.update(Text.assemble(Text("You\n", style="bold cyan"), Text(self.raw_text)))
        elif self.msg_role in ("error", "tool"):
            self.update(Text(self.raw_text))
        elif self.msg_role == "assistant":
            self.update(RichMarkdown(self.raw_text or "…"))
        else:
            self.update(RichMarkdown(self.raw_text))

    def append(self, chunk: str) -> None:
        self.set_text(self.raw_text + chunk)

    def set_text(self, text: str) -> None:
        """Set the text. The repaint is throttled so streaming stays smooth."""
        self.raw_text = text
        self._dirty = True
        if self._timer is None:
            self._timer = self.set_interval(RENDER_INTERVAL, self._flush)

    def flush(self) -> None:
        """Repaint right now and stop the timer."""
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        if self._dirty:
            self._dirty = False
            self.render_text()

    def _flush(self) -> None:
        if self._dirty:
            self._dirty = False
            self.render_text()
        elif self._timer is not None:
            self._timer.stop()
            self._timer = None


class Thinking(Static):
    """Live 'thinking' indicator with the model's reasoning shown below it."""

    DEFAULT_CSS = """
    Thinking {
        padding: 0 1;
        margin: 0 0 1 0;
        width: 100%;
        color: $text-muted;
        border-left: thick $accent;
        text-style: italic;
    }
    """

    SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self) -> None:
        super().__init__(classes="thinking")
        self.reasoning = ""
        self._stream = TextStream()
        self.started = time.monotonic()
        self.finished = False
        self.dirty = False
        self._frame = 0
        self._update_view()

    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def set_reasoning(self, chunk: str) -> None:
        """Add a piece of the model's reasoning (shown under the indicator)."""
        self.reasoning = self._stream.feed(chunk)
        self.dirty = True

    def tick(self) -> None:
        """Animate the spinner and refresh the elapsed time."""
        if self.finished:
            return
        self._frame += 1
        self._update_view()

    def finish(self) -> bool:
        """Stop the spinner. Returns True if the block is worth keeping."""
        if not self.finished:
            self.finished = True
            self._update_view()
        return bool(self.reasoning.strip())

    def _update_view(self) -> None:
        secs = self.elapsed()
        if self.finished:
            head = f"💭 Thought for {secs:.1f}s" if self.reasoning.strip() else f"✓ Done in {secs:.1f}s"
        else:
            head = f"{self.SPINNER[self._frame % len(self.SPINNER)]} Thinking… {secs:.1f}s"
        body = self.reasoning
        if len(body) > MAX_THINK_CHARS:
            body = body[:MAX_THINK_CHARS] + "\n… (thinking truncated)"
        if body.strip():
            indented = "\n".join("  " + line for line in body.splitlines())
            self.update(Text.assemble(Text(head + "\n", style="bold"), Text(indented, style="italic")))
        else:
            self.update(Text(head, style="bold"))



class ImageGenerating(Static):
    DEFAULT_CSS = """
    ImageGenerating {
        padding: 0 1;
        margin: 0 0 1 0;
        width: 100%;
        color: $text-muted;
        border-left: thick $primary;
        text-style: italic;
    }
    """
    SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    def __init__(self) -> None:
        super().__init__(classes="image-generating")
        self.started = time.monotonic()
        self._frame = 0
        self._update_view()
    def elapsed(self) -> float:
        return time.monotonic() - self.started
    def tick(self) -> None:
        self._frame += 1
        self._update_view()
    def finish(self) -> None:
        self.remove()
    def _update_view(self) -> None:
        secs = self.elapsed()
        head = f"{self.SPINNER[self._frame % len(self.SPINNER)]} Generating image… {secs:.1f}s"
        self.update(Text(head, style="bold"))

class PromptInput(Input):
    """Message input with a slash-command dropdown shown above it."""

    BINDINGS = [
        Binding("down", "suggest_down", show=False),
        Binding("up", "suggest_up", show=False),
        Binding("tab", "suggest_tab", show=False),
        Binding("escape", "suggest_escape", show=False),
        Binding("enter", "suggest_enter", show=False),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._just_accepted = False  # ignore the Changed event caused by accept()

    # ---------- suggestion helpers ----------
    def _suggestions(self) -> OptionList:
        return self.app.query_one("#suggestions", OptionList)

    def hide_suggestions(self) -> None:
        lst = self._suggestions()
        lst.clear_options()
        lst.display = False

    def update_suggestions(self) -> None:
        if self._just_accepted:
            self._just_accepted = False
            self.hide_suggestions()
            return
        value = self.value.lstrip()
        if not value.startswith("/") or " " in value:
            self.hide_suggestions()
            return
        query = value[1:].lower()
        matches = [(cmd, desc) for cmd, desc in COMMANDS if cmd[1:].startswith(query)]
        if not matches:
            self.hide_suggestions()
            return
        lst = self._suggestions()
        lst.clear_options()
        for cmd, desc in matches:
            lst.add_option(Option(f"{cmd}  {desc}", id=cmd))
        lst.display = True
        lst.highlighted = 0

    def accept(self, cmd: str) -> None:
        """Fill the input with cmd (plus a space if it takes arguments)."""
        self._just_accepted = True
        self.value = cmd + (" " if cmd in ARG_COMMANDS else "")
        self.cursor_position = len(self.value)
        self.hide_suggestions()
        self.focus()

    def _complete_highlighted(self) -> None:
        lst = self._suggestions()
        if not lst.option_count:
            return
        idx = lst.highlighted if lst.highlighted is not None else 0
        option = lst.get_option_at_index(min(idx, lst.option_count - 1))
        if option is not None and option.id:
            self.accept(option.id)

    # ---------- keys ----------
    def action_suggest_down(self) -> None:
        if self._suggestions().display:
            self._suggestions().action_cursor_down()

    def action_suggest_up(self) -> None:
        if self._suggestions().display:
            self._suggestions().action_cursor_up()

    def action_suggest_tab(self) -> None:
        if self._suggestions().display:
            self._complete_highlighted()

    def action_suggest_escape(self) -> None:
        if self._suggestions().display:
            self.hide_suggestions()

    async def action_suggest_enter(self) -> None:
        # Dropdown open: Enter completes unless the text is already an exact
        # command, in which case it submits.
        lst = self._suggestions()
        if lst.display and not any(cmd == self.value.strip() for cmd, _ in COMMANDS):
            self._complete_highlighted()
            return
        await self.action_submit()


class PanelScreen(ModalScreen):
    """Shared look for the small panels that /connect opens.

    A title on the left, an "esc" button on the right, a rule and then the
    body of the panel.
    """

    DEFAULT_CSS = """
    ConnectScreen, ApiKeyScreen {
        align: center middle;
        background: $background 60%;
    }
    ConnectScreen > Vertical, ApiKeyScreen > Vertical {
        width: 56;
        height: auto;
        max-height: 90%;
        background: $surface;
        border: round $primary;
        padding: 1 2;
    }
    ConnectScreen .head, ApiKeyScreen .head {
        height: 1;
    }
    ConnectScreen .title, ApiKeyScreen .title {
        width: 1fr;
        height: 1;
        content-align: left middle;
        text-style: bold;
    }
    ConnectScreen #esc, ApiKeyScreen #esc {
        width: 5;
        min-width: 5;
        height: 1;
        border: none;
        padding: 0 1;
        background: $surface;
        color: $text-muted;
    }
    ConnectScreen #esc:hover, ApiKeyScreen #esc:hover {
        background: $boost;
        color: $text;
    }
    ConnectScreen Rule, ApiKeyScreen Rule {
        margin: 1 0 0 0;
    }
    ConnectScreen #search, ApiKeyScreen #key {
        margin: 0 0 0 0;
    }
    ConnectScreen #providers {
        height: auto;
        max-height: 10;
        border: none;
        margin: 0 0 1 0;
        background: $surface;
    }
    ConnectScreen #providers:focus {
        border: none;
    }
    ConnectScreen .hint, ApiKeyScreen .hint {
        height: auto;
        color: $text-muted;
    }
    """

    BINDINGS = [Binding("escape", "close_panel", "Close")]

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "esc":
            self.dismiss(None)

    def on_click(self, event) -> None:
        # a click on the dimmed area outside the panel closes it
        if event.widget is self:
            self.dismiss(None)

    def action_close_panel(self) -> None:
        self.dismiss(None)


class ConnectScreen(PanelScreen):
    """The /connect panel: pick a provider to talk to."""

    def compose(self) -> ComposeResult:
        with Vertical():
            with Horizontal(classes="head"):
                yield Label("Connect an integration", classes="title")
                yield Button("esc", id="esc")
            yield Rule()
            yield Input(placeholder="search", id="search")
            yield OptionList(id="providers")
            yield Label("", id="hint", classes="hint")

    def on_mount(self) -> None:
        self.current = ""
        self.show_providers("")
        self.query_one("#search", Input).focus()

    def show_providers(self, query: str) -> None:
        """Fill the list with the providers that match the search."""
        lst = self.query_one("#providers", OptionList)
        lst.clear_options()
        query = query.strip().lower()
        for key, provider in PROVIDERS.items():
            if query and query not in provider["name"].lower() and query not in provider["blurb"].lower():
                continue
            lst.add_option(Option(f"{provider['name']}  {provider['blurb']}", id=key))
        if lst.option_count:
            lst.highlighted = 0
        hint = self.query_one("#hint", Label)
        if not lst.option_count:
            hint.update("No providers yet." if not PROVIDERS else "Nothing matches that search.")
        else:
            hint.update("")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search":
            self.show_providers(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search":
            self.open_selected()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            self.open_provider(event.option.id)

    def open_selected(self) -> None:
        """Open the key screen for the highlighted provider."""
        lst = self.query_one("#providers", OptionList)
        if not lst.option_count:
            return
        idx = lst.highlighted if lst.highlighted is not None else 0
        option = lst.get_option_at_index(min(idx, lst.option_count - 1))
        if option is not None and option.id:
            self.open_provider(option.id)

    def open_provider(self, name: str) -> None:
        """Ask for the API key of the provider the user picked."""
        provider = PROVIDERS.get(name)
        if provider is None:
            return
        self.current = name
        self.app.push_screen(ApiKeyScreen(provider), self.key_entered)

    def key_entered(self, key: str | None) -> None:
        """Called when the API key screen closes."""
        if key and self.current:
            self.app.connect_provider(self.current, key)
        self.dismiss()


class ApiKeyScreen(PanelScreen):
    """Ask for the API key of the provider the user picked."""

    def __init__(self, provider: dict) -> None:
        super().__init__()
        self.provider = provider

    def compose(self) -> ComposeResult:
        with Vertical():
            with Horizontal(classes="head"):
                yield Label(f"Connect {self.provider['name']}", classes="title")
                yield Button("esc", id="esc")
            yield Rule()
            yield Input(placeholder=self.provider.get("key_hint", "API key"), id="key", password=True)
            yield Label("submit enter", classes="hint")
            yield Label(f"Get a key at {self.provider['key_url']}", classes="hint")

    def on_mount(self) -> None:
        self.query_one("#key", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        key = event.value.strip()
        if not key:
            return
        self.dismiss(key)


class AIChat(App):
    TITLE = "Enzo"
    ENABLE_COMMAND_PALETTE = False

    CSS = """
    Screen { layout: vertical; }
    #chat { height: 1fr; padding: 1 1 0 1; }
    #bottom { dock: bottom; height: auto; }
    #suggestions {
        display: none;
        height: auto;
        max-height: 10;
        border: round $primary;
        background: $surface;
        padding: 0;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.cfg = load_config()
        self.provider = set_provider(self.cfg.get("provider") or DEFAULT_PROVIDER)
        self.history: list[dict] = []
        self.busy = False
        self._bubble: Message | None = None
        self._reply = ""
        self._thinking: Thinking | None = None
        self._timer: Timer | None = None
        self._image_gen: ImageGenerating | None = None
        self._img_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(id="chat")
        with Vertical(id="bottom"):
            yield OptionList(id="suggestions")
            yield PromptInput(placeholder="Message… (/help for commands)", id="prompt")

    def on_mount(self) -> None:
        self.refresh_header()
        self.query_one("#prompt", Input).focus()
        self.add_message(
            "system",
            f"Welcome! Type a message, or **/help** for commands.\n\n"
            f"Provider: `{self.provider['name']}`  \n"
            f"Working directory: `{ROOT}`  \nFile access: {access_label(self.cfg['tools'])}",
        )
        if not self.cfg["api_key"]:
            self.add_message("error", "No API key yet. Add one with:  /key sk-or-v1-...")

    def add_message(self, role: str, content: str = "") -> Message:
        msg = Message(role, content)
        chat = self.query_one("#chat", VerticalScroll)
        chat.mount(msg)
        chat.scroll_end(animate=False)
        return msg

    # ---------- Thinking indicator ----------
    def start_thinking(self) -> None:
        """Show a live 'thinking' indicator above the upcoming answer."""
        self.finish_thinking()
        thinking = Thinking()
        self._thinking = thinking
        self._timer = self.set_interval(0.2, self._tick_thinking)
        chat = self.query_one("#chat", VerticalScroll)
        chat.mount(thinking)
        chat.scroll_end(animate=False)

    def add_thinking_text(self, chunk: str) -> None:
        """Stream a piece of the model's reasoning into the indicator."""
        if self._thinking is not None:
            self._thinking.set_reasoning(chunk)

    def finish_thinking(self) -> None:
        """Stop the thinking indicator and remove it from the chat."""
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        if self._thinking is not None:
            self._thinking.finish()
            self._thinking = None
        # ---------- Image generation indicator ----------
    def start_image_generation(self) -> None:
        self.finish_image_generation()
        img = ImageGenerating()
        self._image_gen = img
        self._img_timer = self.set_interval(0.2, self._tick_image_gen)
        chat = self.query_one("#chat", VerticalScroll)
        chat.mount(img)
        chat.scroll_end(animate=False)

    def finish_image_generation(self) -> None:
        if self._img_timer is not None:
            self._img_timer.stop()
            self._img_timer = None
        img = getattr(self, "_image_gen", None)
        if img is None:
            return
        img.finish()
        self._image_gen = None

    def _tick_image_gen(self) -> None:
        img = getattr(self, "_image_gen", None)
        if img is None:
            return
        img.tick()

    def _tick_thinking(self) -> None:
        """Animate the spinner and pull the chat down while reasoning streams."""
        thinking = self._thinking
        if thinking is None or thinking.finished:
            return
        thinking.tick()
        if thinking.dirty:
            thinking.dirty = False
            self.query_one("#chat", VerticalScroll).scroll_end(animate=False)

    # ---------- Actions ----------
    def interrupt(self) -> None:
        if self.busy:
            self.workers.cancel_group(self, "chat")
            self.add_message("system", "Interrupted.")
        else:
            self.add_message("system", "Nothing to interrupt.")

    def clear_chat(self) -> None:
        self.history.clear()
        self.query_one("#chat", VerticalScroll).remove_children()
        self.add_message("system", "Conversation cleared.")

    def refresh_header(self) -> None:
        """Show the model and the directory the AI is working in."""
        self.sub_title = f"{self.cfg['model']} · {ROOT.name or str(ROOT)}"

    def connect_provider(self, name: str, key: str) -> None:
        """Save the API key for a provider and start using it (/connect)."""
        provider = set_provider(name)
        self.provider = provider
        self.cfg["provider"] = name
        self.cfg["api_key"] = key
        save_config(self.cfg)
        self.refresh_header()
        self.add_message("system", f"Connected to **{provider['name']}**.")

    def change_dir(self, path: str) -> None:
        """Point the AI at another directory (/cd)."""
        if not path:
            self.add_message("system", f"Working directory: `{ROOT}`")
            return
        try:
            raw = Path(path).expanduser()
            target = (raw if raw.is_absolute() else ROOT / raw).resolve()
        except OSError as e:
            self.add_message("error", f"Could not resolve `{path}`: {e}")
            return
        if not target.exists():
            self.add_message("error", f"No such directory: `{path}`")
            return
        if not target.is_dir():
            self.add_message("error", f"Not a directory: `{path}`")
            return
        set_root(target)
        self.refresh_header()
        self.add_message("system", f"Working directory is now `{target}`")

    # ---------- Input handling ----------
    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if isinstance(event.input, PromptInput):
            event.input.hide_suggestions()
        if not text:
            return

        if text.startswith("/"):
            await self.handle_command(text)
            return

        if self.busy:
            self.add_message("system", "Still replying… use /interrupt to stop.")
            return
        if not self.cfg["api_key"]:
            self.add_message("error", "No API key set. Use:  /key sk-or-v1-...")
            return

        self.add_message("user", text)
        self.history.append({"role": "user", "content": text})
        self.ask()

    def on_input_changed(self, event: Input.Changed) -> None:
        if isinstance(event.input, PromptInput):
            event.input.update_suggestions()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            self.query_one("#prompt", PromptInput).accept(event.option.id)

    async def handle_command(self, text: str) -> None:
        cmd, _, arg = text.partition(" ")
        cmd, arg = cmd.lower(), arg.strip()

        if cmd == "/help":
            self.add_message("system", HELP_TEXT)
        elif cmd in ("/exit", "/quit"):
            self.exit()
        elif cmd == "/interrupt":
            self.interrupt()
        elif cmd == "/clear":
            self.clear_chat()
        elif cmd == "/restart":
            self.add_message("system", "Restarting…")
            os.execv(sys.executable, [sys.executable] + sys.argv)
        elif cmd == "/update":
            self.update_package(arg)
        elif cmd == "/connect":
            self.push_screen(ConnectScreen())
        elif cmd == "/autocompact":
            if arg.lower() in ("on", "off"):
                self.cfg["autocompact"] = arg.lower() == "on"
                save_config(self.cfg)
                state = "on" if self.cfg["autocompact"] else "off"
                self.add_message("system", f"Auto-compact turned **{state}**.")
            else:
                state = "on" if self.cfg["autocompact"] else "off"
                self.add_message("system", f"Auto-compact is **{state}**. Usage: `/autocompact on` or `/autocompact off`")
        elif cmd == "/dir":
            self.add_message(
                "system",
                f"Provider: `{self.provider['name']}`  \n"
                f"Working directory: `{ROOT}`  \nFile access: {access_label(self.cfg['tools'])}"
            )
        elif cmd == "/cd":
            self.change_dir(arg)
        elif cmd == "/tools":
            if arg.lower() in ("on", "off"):
                self.cfg["tools"] = arg.lower() == "on"
                save_config(self.cfg)
                self.add_message(
                    "system",
                    f"File access turned **{arg.lower()}**.\n"
                    f"The AI can now read, write and run commands in `{ROOT}`.",
                )
            else:
                self.add_message("system", "Usage: `/tools on` or `/tools off`")
        elif cmd == "/key":
            if not arg:
                k = self.cfg["api_key"]
                shown = f"{k[:8]}…{k[-4:]}" if len(k) > 12 else ("set" if k else "not set")
                self.add_message("system", f"API key: `{shown}`\nUsage: `/key sk-or-v1-...`")
            else:
                self.cfg["api_key"] = arg
                save_config(self.cfg)
                self.add_message("system", f"API key saved to `{CONFIG_PATH}`")
        elif cmd == "/model":
            if not arg:
                self.add_message("system", f"Current model: `{self.cfg['model']}`")
            else:
                self.cfg["model"] = arg
                save_config(self.cfg)
                self.sub_title = arg
                self.add_message("system", f"Model set to `{arg}`")
        elif cmd == "/system":
            if not arg:
                self.add_message("system", f"System prompt:\n\n{self.cfg['system']}")
            else:
                self.cfg["system"] = arg
                save_config(self.cfg)
                self.add_message("system", "System prompt updated.")
        elif cmd == "/models":
            self.search_models(arg)
        else:
            self.add_message("error", f"Unknown command: {cmd}  (try /help)")

    # ---------- Networking ----------
    @work(group="update")
    async def update_package(self, package: str = "") -> None:
        """Install the latest version of this package from npm (/update)."""
        name = package.strip() or installed_package_name()
        if not name:
            self.add_message(
                "error",
                "Could not work out which npm package this is.\n"
                "Use:  /update @scope/name",
            )
            return
        if not shutil.which("npm"):
            self.add_message("error", "npm is not installed, so /update cannot run here.")
            return
        self.add_message("system", f"Updating `{name}` from npm, this can take a minute…")
        cmd = ["npm", "install", "-g", f"{name}@latest"]
        try:
            proc = await asyncio.to_thread(
                subprocess.run, cmd, capture_output=True, text=True, timeout=600
            )
        except subprocess.TimeoutExpired:
            self.add_message("error", "npm install took too long and was stopped.")
            return
        except Exception as e:  # noqa: BLE001
            self.add_message("error", f"Could not run npm: {e}")
            return
        out = ((proc.stdout or "") + (proc.stderr or "")).strip()
        if proc.returncode != 0:
            self.add_message("error", f"npm failed:\n\n```\n{out[-1500:]}\n```")
            return
        tail = "\n".join(out.splitlines()[-6:]) if out else ""
        self.add_message(
            "system",
            f"Updated `{name}`.\n\n"
            + (f"```\n{tail}\n```\n\n" if tail else "")
            + "Run `/restart` to start the new version.",
        )

    def headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.cfg['api_key']}",
            "Content-Type": "application/json",
            "X-Title": "Enzo",
        }

    @work(exclusive=True, group="models")
    async def search_models(self, query: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(MODELS_URL)
                r.raise_for_status()
                models = r.json().get("data", [])
        except Exception as e:  # noqa: BLE001
            self.add_message("error", f"Could not fetch models: {e}")
            return
        q = query.lower()
        found = [m["id"] for m in models if q in m["id"].lower()]
        if not found:
            self.add_message("system", "No models matched.")
            return
        lines = "\n".join(f"- `{m}`" for m in found[:15])
        extra = f"\n\n…and {len(found) - 15} more." if len(found) > 15 else ""
        self.add_message("system", f"**Models**\n{lines}{extra}")

    def build_messages(self) -> list[dict]:
        system = self.cfg["system"] or ""
        if self.cfg["tools"]:
            system += (
                f"\n\nYou have full access to the user's project directory: {ROOT}\n"
                "- list_directory / read_file: explore the project (paths are relative to it)\n"
                "- write_file: create or overwrite a file (parent folders are created; read first to keep existing content)\n"
                "- make_directory / rename_path / delete_path: create, rename/move, or delete files and folders\n"
                "- run_command: run a shell command inside the project directory and get its output\n"
                "Look before you answer instead of guessing. Stay inside that directory. "
                "Only delete or overwrite things the user asked you to; avoid destructive or interactive commands. "
                "Prefer write_file over shell heredocs for editing files."
            )
        messages = [{"role": "system", "content": system.strip()}] if system.strip() else []
        messages.extend(self.compact_history(self.history))
        return messages

    def compact_history(self, history: list[dict]) -> list[dict]:
        """Return history with older turns summarized when it exceeds the threshold."""
        if not self.cfg["autocompact"] or not history:
            return history
        total = sum(len(m.get("content", "")) for m in history)
        if total <= AUTO_COMPACT_THRESHOLD:
            return history
        keep = history[-AUTO_COMPACT_KEEP:]
        omitted = history[:-AUTO_COMPACT_KEEP]
        summary = f"[Context compacted: {len(omitted)} earlier turns omitted to stay within context window. Recent conversation continues below.]"
        # Preserve any file paths mentioned in omitted turns for continuity
        paths: list[str] = []
        import re as _re
        for m in omitted:
            for match in _re.findall(r"`([^`]+)`", m.get("content", "")):
                if "/" in match or match.endswith((".py", ".md", ".txt", ".json", ".ts", ".js", ".html", ".css")):
                    paths.append(match)
        if paths:
            uniq = []
            for p in paths:
                if p not in uniq:
                    uniq.append(p)
            summary += f" Files referenced: {', '.join(uniq[:10])}."
        return [{"role": "system", "content": summary}] + keep

    async def stream_round(self, client: httpx.AsyncClient, messages: list[dict], use_tools: bool):
        """Stream one model response. Returns (text, tool_calls)."""
        payload = {"model": self.cfg["model"], "messages": messages, "stream": True}
        if use_tools:
            payload["tools"] = TOOLS

        chat = self.query_one("#chat", VerticalScroll)
        text = ""
        calls: dict[int, dict] = {}
        self._bubble = None
        stream = TextStream()
        round_base = ""
        self.start_thinking()

        async with client.stream("POST", API_URL, headers=self.headers(), json=payload) as resp:
            if resp.status_code != 200:
                body = (await resp.aread()).decode(errors="replace")
                try:
                    body = json.loads(body)["error"]["message"]
                except Exception:  # noqa: BLE001
                    pass
                hint = ""
                if use_tools and "tool" in body.lower():
                    hint = "\nThis model may not support file access. Try another model, or /tools off."
                raise RuntimeError(f"HTTP {resp.status_code}: {body}{hint}")

            async for line in resp.aiter_lines():
                if not line or line.startswith(":") or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if "error" in obj:
                    err = obj["error"]
                    raise RuntimeError(err.get("message", str(err)) if isinstance(err, dict) else str(err))
                choices = obj.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}

                reasoning = extract_reasoning(delta)
                if reasoning:
                    self.add_thinking_text(reasoning)

                chunk = delta.get("content") or ""
                if chunk:
                    self.finish_thinking()
                    if self._bubble is None:
                        round_base = self._reply
                        if round_base:
                            round_base += "\n\n"
                        self._bubble = self.add_message("assistant", "")
                    text = stream.feed(chunk)
                    self._reply = round_base + text
                    self._bubble.set_text(text)
                    chat.scroll_end(animate=False)

                for tc in delta.get("tool_calls") or []:
                    slot = calls.setdefault(tc.get("index", 0), {"id": "", "name": "", "args": ""})
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["name"] = fn["name"]
                    if fn.get("arguments"):
                        slot["args"] += fn["arguments"]

        self.finish_thinking()
        if self._bubble is not None:
            self._bubble.flush()
        ordered = [calls[i] for i in sorted(calls)]
        for n, c in enumerate(ordered):
            c["id"] = c["id"] or f"call_{n}"
        return text, ordered

    @work(exclusive=True, group="chat")
    async def ask(self) -> None:
        self.busy = True
        prompt = self.query_one("#prompt", Input)
        prompt.placeholder = "Thinking… (/interrupt to stop)"
        chat = self.query_one("#chat", VerticalScroll)
        self._bubble = None
        self._reply = ""
        failed = False

        messages = self.build_messages()
        use_tools = bool(self.cfg["tools"])

        try:
            timeout = httpx.Timeout(60.0, read=120.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                for _ in range(MAX_TOOL_ROUNDS):
                    text, calls = await self.stream_round(client, messages, use_tools)
                    if not calls:
                        break
                    messages.append(
                        {
                            "role": "assistant",
                            "content": text or None,
                            "tool_calls": [
                                {
                                    "id": c["id"],
                                    "type": "function",
                                    "function": {"name": c["name"], "arguments": c["args"] or "{}"},
                                }
                                for c in calls
                            ],
                        }
                    )
                    for c in calls:
                        if c["name"] != "run_command":  # shown as '<dir>$ cmd' in the result
                            self.add_message("tool", "→ " + describe_call(c["name"], c["args"]))
                        chat.scroll_end(animate=False)
                        if c["name"] == "generate_image":
                            self.start_image_generation()
                        result = await asyncio.to_thread(run_tool, c["name"], c["args"])
                        if c["name"] == "generate_image":
                            self.finish_image_generation()
                        if c["name"] in SHOW_RESULT_TOOLS:
                            # show what ran / changed below the AI's message
                            self.add_message(
                                "tool", format_tool_result(c["name"], c["args"], result)
                            )
                            chat.scroll_end(animate=False)
                        messages.append({"role": "tool", "tool_call_id": c["id"], "content": result})
                else:
                    self.add_message("system", "Stopped: too many tool steps for one question.")
        except asyncio.CancelledError:
            if self._bubble is not None:
                self._bubble.append("\n\n*(stopped)*")
        except Exception as e:  # noqa: BLE001
            failed = True
            self.add_message("error", f"Error: {e}")
        finally:
            self.finish_thinking()
            if failed or not self._reply:
                # drop the unanswered user turn so the history stays valid
                if self.history and self.history[-1]["role"] == "user":
                    self.history.pop()
            else:
                self.history.append({"role": "assistant", "content": self._reply})
            self.busy = False
            prompt.placeholder = "Message… (/help for commands)"
            prompt.focus()


if __name__ == "__main__":
    AIChat().run()
