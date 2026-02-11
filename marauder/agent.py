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
MAX_TOOL_RESULT_CHARS = 1500
MAX_OLD_ASSISTANT_CHARS = 500

SYSTEM_PROMPT = """You are Marauder Code, an AI coding assistant in a CLI.
You can read, write, edit files, list dirs, and run commands in the user's project.

Rules:
- Use tools to interact with files. Never guess contents.
- edit_file needs exact matching strings.
- list_files first to understand structure.
- Be concise. Do the work, skip the essays.
- Write complete, working code.
"""

view_mode = "normal"


def set_view_mode(mode: str):
    global view_mode
    view_mode = mode


def _trim_history(history: list) -> list:
    """Smart history trimming to keep context lean."""
    if len(history) <= MAX_HISTORY_MESSAGES:
        return history
    # Keep first 2 messages (initial context) + most recent
    keep_start = history[:2]
    keep_end = history[-(MAX_HISTORY_MESSAGES - 2):]
    return keep_start + [{"role": "system", "content": "[Earlier conversation trimmed]"}] + keep_end


def _fmt_tokens(n: int) -> str:
    if n < 1000:
        return str(n)
    return f"{n / 1000:.1f}k"


def _truncate_tool_results(history: list) -> list:
    """Aggressively compress old messages to save context.
    
    - Old tool results (beyond last 6): truncated hard
    - Old assistant messages: trimmed to summary length
    - Recent messages (last 6): kept intact
    """
    result = []
    total = len(history)
    recent_cutoff = total - 6  # keep last 6 messages fully intact

    for i, msg in enumerate(history):
        if i >= recent_cutoff:
            result.append(msg)
            continue

        role = msg.get("role", "")

        if role == "tool":
            content = msg["content"]
            if len(content) > MAX_TOOL_RESULT_CHARS:
                msg = dict(msg)
                # For file reads, just keep first/last few lines
                lines = content.split("\n")
                if len(lines) > 20:
                    kept = lines[:10] + [f"... ({len(lines) - 20} lines omitted) ..."] + lines[-10:]
                    msg["content"] = "\n".join(kept)
                else:
                    msg["content"] = content[:MAX_TOOL_RESULT_CHARS] + "\n... (truncated)"

        elif role == "assistant":
            content = msg.get("content", "") or ""
            if len(content) > MAX_OLD_ASSISTANT_CHARS:
                msg = dict(msg)
                msg["content"] = content[:MAX_OLD_ASSISTANT_CHARS] + "..."

        result.append(msg)
    return result


def _extract_content(msg) -> tuple[str, str]:
    """Extract text content and thinking content from a message.
    
    Handles:
    - Standard string content (most models)
    - Content blocks with type "thinking"/"text" (Claude extended thinking)
    - Reasoning_content field (DeepSeek R1, Kimi K2.5)
    
    Returns (text_content, thinking_content).
    """
    text = ""
    thinking = ""

    # Check for reasoning_content (DeepSeek, Kimi style)
    reasoning = getattr(msg, "reasoning_content", None)
    if reasoning:
        thinking = reasoning

    # Main content — could be string or list of content blocks
    content = msg.content
    if isinstance(content, str):
        text = content or ""
    elif isinstance(content, list):
        # Content blocks (Claude style): [{"type": "thinking", "thinking": "..."}, {"type": "text", "text": "..."}]
        for block in content:
            if isinstance(block, dict):
                block_type = block.get("type", "")
                if block_type == "thinking":
                    thinking += block.get("thinking", "")
                elif block_type == "text":
                    text += block.get("text", "")
                else:
                    text += block.get("text", str(block))
            elif hasattr(block, "type"):
                # Object-style blocks from the SDK
                if block.type == "thinking":
                    thinking += getattr(block, "thinking", "")
                elif block.type == "text":
                    text += getattr(block, "text", "")
                else:
                    text += getattr(block, "text", str(block))
            else:
                text += str(block)

    return text.strip(), thinking.strip()


def run_agent(client: OpenAI, model: str, work_dir: str, user_message: str, history: list) -> list:
    """Run one turn of the agent loop. Returns updated history."""
    history.append({"role": "user", "content": user_message})
    history = _trim_history(history)

    start_time = time.time()
    tool_count = 0
    files_changed = []
    current_phase = "thinking"
    final_content = None
    total_prompt_tokens = 0
    total_completion_tokens = 0
    api_calls = 0

    use_normal = view_mode == "normal"
    status_ctx = None
    ticker_stop = threading.Event()

    def _build_status() -> str:
        elapsed = time.time() - start_time
        txt = f"  ⚡ Marauder is working  ({elapsed:.0f}s • {tool_count} actions • {_fmt_tokens(total_prompt_tokens + total_completion_tokens)} tokens • {current_phase})"
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

            # Track token usage
            if resp.usage:
                total_prompt_tokens += resp.usage.prompt_tokens or 0
                total_completion_tokens += resp.usage.completion_tokens or 0
            api_calls += 1

            current_phase = "processing response"

            # Extract text and thinking content
            text_content, thinking_content = _extract_content(msg)

            # Show thinking in advanced mode
            if thinking_content and view_mode == "advanced":
                console.print(Panel(
                    thinking_content[:500] + ("..." if len(thinking_content) > 500 else ""),
                    title="💭 Thinking", border_style="dim magenta", expand=False,
                ))
            elif thinking_content and use_normal:
                current_phase = "thinking deeply..."

            # Build history message — only store text, not thinking (saves tokens)
            assistant_msg = {"role": "assistant", "content": text_content}
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
                final_content = text_content
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

            if text_content and view_mode == "advanced":
                console.print(Panel(text_content, title="Marauder", border_style="cyan"))

    finally:
        ticker_stop.set()
        if status_ctx:
            status_ctx.stop()

    # Final summary
    elapsed = time.time() - start_time
    total_tokens = total_prompt_tokens + total_completion_tokens
    if use_normal:
        console.print(f"  [green]✓ Done in {elapsed:.1f}s — {tool_count} actions[/green]")
        if files_changed:
            unique = list(dict.fromkeys(files_changed))
            console.print(f"  [dim]Files touched: {', '.join(unique)}[/dim]")
        if total_tokens > 0:
            console.print(f"  [dim]Tokens: {_fmt_tokens(total_prompt_tokens)} in / {_fmt_tokens(total_completion_tokens)} out / {_fmt_tokens(total_tokens)} total ({api_calls} API calls)[/dim]")
        console.print()

    if final_content:
        console.print(Panel(final_content, title="Marauder", border_style="cyan"))

    return history, total_prompt_tokens


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


SUMMARIZE_PROMPT = """Summarize this conversation for context continuity. Include:
1. What the project is (language, framework, purpose) in 1-2 sentences.
2. What was accomplished in this session (files created/edited, features built).
3. What the user was last working on or asked for.
4. Any important decisions or patterns established.

Be concise. Max 300 words. This summary will be used to continue the conversation in a fresh context."""


def summarize_context(client: OpenAI, model: str, history: list) -> str:
    """Ask the model to summarize the current conversation for compaction."""
    # Build a condensed version of history for the summary request
    condensed = []
    for msg in history:
        role = msg.get("role", "")
        content = msg.get("content", "") or ""
        if role == "user":
            condensed.append({"role": "user", "content": content[:500]})
        elif role == "assistant":
            condensed.append({"role": "assistant", "content": content[:300]})
        elif role == "tool":
            # Just mention what tool was called, not the full result
            condensed.append({"role": "assistant", "content": f"[tool result: {content[:100]}]"})

    messages = [{"role": "system", "content": SUMMARIZE_PROMPT}] + condensed[-30:]

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=500,
            temperature=0,
        )
        text, _ = _extract_content(resp.choices[0].message)
        return text
    except Exception as e:
        return f"(Summary failed: {e})"
