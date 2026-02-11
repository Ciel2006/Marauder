"""Agent loop — sends messages, handles tool calls, streams responses."""
import json
import os
import time
import threading
from openai import OpenAI
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from marauder.tools import TOOL_DEFINITIONS, execute_tool

console = Console()

EXT_TO_LANG = {
    ".py": "python", ".js": "javascript", ".ts": "typescript", ".tsx": "tsx",
    ".jsx": "jsx", ".html": "html", ".css": "css", ".json": "json",
    ".yaml": "yaml", ".yml": "yaml", ".md": "markdown", ".sh": "bash",
    ".bash": "bash", ".sql": "sql", ".xml": "xml", ".toml": "toml",
    ".rs": "rust", ".go": "go", ".java": "java", ".c": "c", ".cpp": "cpp",
    ".h": "c", ".rb": "ruby", ".php": "php", ".swift": "swift",
    ".kt": "kotlin", ".lua": "lua", ".r": "r", ".txt": "text",
}

MAX_DISPLAY_LINES = 30
MAX_HISTORY_MESSAGES = 40
MAX_TOOL_RESULT_CHARS = 2000

SYSTEM_PROMPT = """You are Marauder Code, an AI coding assistant running in a CLI.
You have access to the user's project directory and can read, write, edit files, list directory contents, and run shell commands.

Rules:
- Always use the tools to interact with files. Never guess file contents.
- When editing, use edit_file with exact matching strings.
- Use list_files first to understand the project structure before making changes.
- Be concise in your explanations. Focus on doing the work.
- If a task is ambiguous, ask the user to clarify.
- When creating files, write complete, working code.
- Keep your text responses short. The user wants results, not essays.
"""

view_mode = "normal"


def set_view_mode(mode: str):
    global view_mode
    view_mode = mode


def _trim_history(history: list) -> list:
    if len(history) <= MAX_HISTORY_MESSAGES:
        return history
    keep_start = history[:2]
    keep_end = history[-(MAX_HISTORY_MESSAGES - 2):]
    return keep_start + [{"role": "system", "content": "[Earlier conversation trimmed]"}] + keep_end


def _truncate_tool_results(history: list) -> list:
    result = []
    total = len(history)
    for i, msg in enumerate(history):
        if msg.get("role") == "tool" and i < total - 10:
            content = msg["content"]
            if len(content) > MAX_TOOL_RESULT_CHARS:
                msg = dict(msg)
                msg["content"] = content[:MAX_TOOL_RESULT_CHARS] + "\n... (truncated)"
        result.append(msg)
    return result


def run_agent(client: OpenAI, model: str, work_dir: str, user_message: str, history: list) -> list:
    """Run one turn of the agent loop. Returns updated history."""
    history.append({"role": "user", "content": user_message})
    history = _trim_history(history)

    start_time = time.time()
    tool_count = 0
    files_changed = []
    current_phase = "thinking"
    final_content = None

    use_normal = view_mode == "normal"
    status_ctx = None
    ticker_stop = threading.Event()

    def _build_status() -> str:
        elapsed = time.time() - start_time
        txt = f"  ⚡ Marauder is working  ({elapsed:.0f}s • {tool_count} actions • {current_phase})"
        return txt

    # Background thread to tick the timer every second
    def _ticker():
        while not ticker_stop.is_set():
            if status_ctx:
                try:
                    status_ctx.update(_build_status())
                except Exception:
                    pass
            ticker_stop.wait(1.0)

    if use_normal:
        status_ctx = console.status(_build_status(), spinner="dots", spinner_style="cyan")
        status_ctx.start()
        ticker_thread = threading.Thread(target=_ticker, daemon=True)
        ticker_thread.start()

    try:
        while True:
            messages = [{"role": "system", "content": SYSTEM_PROMPT}] + _truncate_tool_results(history)

            current_phase = "waiting for API..."

            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=TOOL_DEFINITIONS,
                    temperature=0,
                )
            except Exception as e:
                console.print(f"[red]  API error: {e}[/red]")
                break

            choice = resp.choices[0]
            msg = choice.message

            current_phase = "processing response"

            assistant_msg = {"role": "assistant", "content": msg.content}
            if msg.tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in msg.tool_calls
                ]
            history.append(assistant_msg)

            if not msg.tool_calls:
                final_content = msg.content
                break

            for tc in msg.tool_calls:
                fn_name = tc.function.name
                fn_args = tc.function.arguments
                tool_count += 1

                try:
                    parsed = json.loads(fn_args)
                    short = _summarize_tool_call(fn_name, parsed)
                except Exception:
                    short = fn_args
                    parsed = {}

                if fn_name in ("write_file", "edit_file") and "path" in parsed:
                    files_changed.append(parsed["path"])

                current_phase = _short_action(fn_name, parsed)

                if view_mode == "advanced":
                    console.print(f"  [dim]⚡ {fn_name}({short})[/dim]")

                result = execute_tool(work_dir, fn_name, fn_args)

                if view_mode == "advanced":
                    _display_tool_result(fn_name, parsed, result)

                history.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

            if msg.content and view_mode == "advanced":
                console.print(Panel(msg.content, title="Marauder", border_style="cyan"))

    finally:
        ticker_stop.set()
        if status_ctx:
            status_ctx.stop()

    # Final summary
    elapsed = time.time() - start_time
    if use_normal:
        console.print(f"  [green]✓ Done in {elapsed:.1f}s — {tool_count} actions[/green]")
        if files_changed:
            unique = list(dict.fromkeys(files_changed))
            console.print(f"  [dim]Files touched: {', '.join(unique)}[/dim]")
        console.print()

    if final_content:
        console.print(Panel(final_content, title="Marauder", border_style="cyan"))

    return history


def _short_action(fn_name: str, args: dict) -> str:
    path = args.get("path", "")
    if fn_name == "read_file":
        return f"reading {path}"
    if fn_name == "write_file":
        return f"writing {path}"
    if fn_name == "edit_file":
        return f"editing {path}"
    if fn_name == "list_files":
        return "listing files"
    if fn_name == "run_command":
        return f"running {args.get('command', '')[:30]}"
    return fn_name


def _detect_lang(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return EXT_TO_LANG.get(ext, "text")


def _display_tool_result(fn_name: str, args: dict, result: str):
    if result.startswith("Error:"):
        console.print(f"  [red]→ {result}[/red]")
        return

    path = args.get("path", "")
    lang = _detect_lang(path) if path else "text"

    if fn_name == "read_file":
        lines = result.split("\n")
        total = len(lines)
        display_text = "\n".join(lines[:MAX_DISPLAY_LINES])
        if total > MAX_DISPLAY_LINES:
            display_text += f"\n... ({total - MAX_DISPLAY_LINES} more lines)"
        syntax = Syntax(display_text, lang, theme="monokai", line_numbers=True, word_wrap=True)
        console.print(Panel(syntax, title=f"📄 {path} ({total} lines)", border_style="dim cyan", expand=False))

    elif fn_name == "write_file":
        content = args.get("content", "")
        lines = content.split("\n")
        total = len(lines)
        display_text = "\n".join(lines[:MAX_DISPLAY_LINES])
        if total > MAX_DISPLAY_LINES:
            display_text += f"\n... ({total - MAX_DISPLAY_LINES} more lines)"
        syntax = Syntax(display_text, lang, theme="monokai", line_numbers=True, word_wrap=True)
        console.print(Panel(syntax, title=f"✏️  wrote {path} ({total} lines)", border_style="dim green", expand=False))

    elif fn_name == "edit_file":
        console.print(f"  [green]→ {result}[/green]")

    elif fn_name == "list_files":
        lines = result.split("\n")
        total = len(lines)
        display_text = "\n".join(lines[:40])
        if total > 40:
            display_text += f"\n... ({total - 40} more entries)"
        console.print(Panel(display_text, title=f"📁 {path or '.'}", border_style="dim yellow", expand=False))

    elif fn_name == "run_command":
        lines = result.split("\n")
        total = len(lines)
        display_text = "\n".join(lines[:MAX_DISPLAY_LINES])
        if total > MAX_DISPLAY_LINES:
            display_text += f"\n... ({total - MAX_DISPLAY_LINES} more lines)"
        console.print(Panel(display_text, title=f"$ {args.get('command', '')}", border_style="dim white", expand=False))

    else:
        display = result if len(result) < 300 else result[:300] + "..."
        console.print(f"  [dim]→ {display}[/dim]")


def _summarize_tool_call(name: str, args: dict) -> str:
    if name == "read_file":
        return args.get("path", "")
    if name == "write_file":
        return f"{args.get('path', '')} ({len(args.get('content', ''))} chars)"
    if name == "edit_file":
        return args.get("path", "")
    if name == "list_files":
        return args.get("path", ".")
    if name == "run_command":
        cmd = args.get("command", "")
        return cmd if len(cmd) < 60 else cmd[:60] + "..."
    return str(args)[:80]
