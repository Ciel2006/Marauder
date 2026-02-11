"""File system tools the AI agent can use."""
import os
import json
import subprocess
import threading
import time
import signal

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file at the given path (relative to working directory).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative file path to read."}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a file with the given content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative file path to write."},
                    "content": {"type": "string", "description": "Full file content to write."},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace an exact string in a file with new content. The old_str must match exactly.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative file path to edit."},
                    "old_str": {"type": "string", "description": "Exact string to find and replace."},
                    "new_str": {"type": "string", "description": "Replacement string."},
                },
                "required": ["path", "old_str", "new_str"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files and directories at the given path. Returns a tree-like listing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative directory path. Use '.' for current dir.", "default": "."},
                    "depth": {"type": "integer", "description": "Max depth to recurse. Default 2.", "default": 2},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a short-lived shell command (installs, builds, linting, tests, etc.) and return stdout/stderr. Has a 60s timeout. Do NOT use this for long-running processes like dev servers — use run_background instead.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute."}
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_background",
            "description": "Launch a long-running process (dev servers, watchers, etc.) in the background. Waits a few seconds then returns the initial output so you can check if it started successfully or crashed. Use this for commands like 'npm run dev', 'python app.py', 'flask run', etc. Returns a process ID you can use with check_background or stop_background.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run in background."},
                    "wait_seconds": {"type": "integer", "description": "Seconds to wait before capturing output. Default 5. Use longer (10-15) for slow-starting servers.", "default": 5},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_background",
            "description": "Check the status and recent output of a background process. Use this to see if a running server has new logs, errors, or has crashed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pid": {"type": "integer", "description": "Process ID returned by run_background."},
                },
                "required": ["pid"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stop_background",
            "description": "Stop a background process by its process ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pid": {"type": "integer", "description": "Process ID to stop."},
                },
                "required": ["pid"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_background",
            "description": "List all currently tracked background processes with their status and recent output.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
]


def _resolve(work_dir: str, path: str) -> str:
    """Resolve a relative path against the working directory safely."""
    full = os.path.normpath(os.path.join(work_dir, path))
    if not full.startswith(os.path.normpath(work_dir)):
        raise ValueError(f"Path escapes working directory: {path}")
    return full


def read_file(work_dir: str, path: str) -> str:
    full = _resolve(work_dir, path)
    if not os.path.isfile(full):
        return f"Error: file not found: {path}"
    with open(full, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def write_file(work_dir: str, path: str, content: str) -> str:
    full = _resolve(work_dir, path)
    os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Wrote {len(content)} chars to {path}"


def edit_file(work_dir: str, path: str, old_str: str, new_str: str) -> str:
    full = _resolve(work_dir, path)
    if not os.path.isfile(full):
        return f"Error: file not found: {path}"
    with open(full, "r", encoding="utf-8") as f:
        text = f.read()
    if old_str not in text:
        return f"Error: old_str not found in {path}"
    count = text.count(old_str)
    if count > 1:
        return f"Error: old_str found {count} times in {path}, must be unique"
    text = text.replace(old_str, new_str, 1)
    with open(full, "w", encoding="utf-8") as f:
        f.write(text)
    return f"Edited {path}"


def list_files(work_dir: str, path: str = ".", depth: int = 2) -> str:
    full = _resolve(work_dir, path)
    if not os.path.isdir(full):
        return f"Error: not a directory: {path}"
    lines = []
    _walk(full, "", depth, lines)
    return "\n".join(lines) if lines else "(empty directory)"


def _walk(dir_path: str, prefix: str, depth: int, lines: list):
    if depth < 0:
        return
    try:
        entries = sorted(os.listdir(dir_path))
    except PermissionError:
        lines.append(f"{prefix}(permission denied)")
        return
    # Skip common noise
    skip = {".git", "node_modules", "__pycache__", ".venv", "venv", ".env"}
    entries = [e for e in entries if e not in skip]
    for entry in entries:
        fp = os.path.join(dir_path, entry)
        if os.path.isdir(fp):
            lines.append(f"{prefix}{entry}/")
            _walk(fp, prefix + "  ", depth - 1, lines)
        else:
            lines.append(f"{prefix}{entry}")


def run_command(work_dir: str, command: str) -> str:
    try:
        result = subprocess.run(
            command, shell=True, cwd=work_dir,
            capture_output=True, text=True, timeout=60,
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += ("\n" if output else "") + result.stderr
        if result.returncode != 0:
            output += f"\n(exit code: {result.returncode})"
        output = output or "(no output)"
        # Cap output to prevent context bloat (pip install, npm install, etc.)
        if len(output) > 4000:
            lines = output.split("\n")
            if len(lines) > 40:
                output = "\n".join(lines[:15]) + f"\n... ({len(lines) - 30} lines omitted) ...\n" + "\n".join(lines[-15:])
            else:
                output = output[:4000] + "\n...(output truncated)"
        return output
    except subprocess.TimeoutExpired:
        return "Error: command timed out (60s limit). If this is a long-running process (dev server, watcher), use run_background instead."
    except Exception as e:
        return f"Error: {e}"


# ── Background process management ──────────────────────────────────────

_background_processes: dict[int, dict] = {}
_bg_lock = threading.Lock()


def _read_output(proc, output_buf: list, lock: threading.Lock):
    """Background thread to continuously read process output."""
    try:
        for line in iter(proc.stdout.readline, ""):
            with lock:
                output_buf.append(line)
            # Keep buffer from growing unbounded
            with lock:
                if len(output_buf) > 500:
                    output_buf[:] = output_buf[-300:]
    except (ValueError, OSError):
        pass


def _read_stderr(proc, output_buf: list, lock: threading.Lock):
    """Background thread to continuously read process stderr."""
    try:
        for line in iter(proc.stderr.readline, ""):
            with lock:
                output_buf.append(f"[stderr] {line}")
            with lock:
                if len(output_buf) > 500:
                    output_buf[:] = output_buf[-300:]
    except (ValueError, OSError):
        pass


def run_background(work_dir: str, command: str, wait_seconds: int = 5) -> str:
    """Launch a process in the background and return initial output after waiting."""
    try:
        proc = subprocess.Popen(
            command, shell=True, cwd=work_dir,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
    except Exception as e:
        return f"Error starting process: {e}"

    output_buf = []
    buf_lock = threading.Lock()

    # Start reader threads
    stdout_thread = threading.Thread(target=_read_output, args=(proc, output_buf, buf_lock), daemon=True)
    stderr_thread = threading.Thread(target=_read_stderr, args=(proc, output_buf, buf_lock), daemon=True)
    stdout_thread.start()
    stderr_thread.start()

    # Wait for initial output
    time.sleep(min(wait_seconds, 30))

    pid = proc.pid
    alive = proc.poll() is None

    with _bg_lock:
        _background_processes[pid] = {
            "command": command,
            "proc": proc,
            "output_buf": output_buf,
            "buf_lock": buf_lock,
            "started_at": time.time(),
        }

    with buf_lock:
        initial_output = "".join(output_buf)

    status = "RUNNING" if alive else f"EXITED (code: {proc.returncode})"

    result = f"Process started (PID: {pid})\nStatus: {status}\n"
    if initial_output.strip():
        result += f"\n--- Initial output ---\n{initial_output}"
    else:
        result += "\n(no output yet)"

    if not alive and proc.returncode != 0:
        result += "\n\n⚠ Process crashed on startup. Check the output above for errors."

    return result


def check_background(pid: int) -> str:
    """Check status and recent output of a background process."""
    with _bg_lock:
        entry = _background_processes.get(pid)
    if not entry:
        return f"Error: no tracked process with PID {pid}. Use list_background to see active processes."

    proc = entry["proc"]
    alive = proc.poll() is None
    elapsed = time.time() - entry["started_at"]

    with entry["buf_lock"]:
        # Get last 50 lines
        recent = entry["output_buf"][-50:]
        output = "".join(recent)

    status = "RUNNING" if alive else f"EXITED (code: {proc.returncode})"
    result = f"PID: {pid} | Command: {entry['command']}\nStatus: {status} | Uptime: {elapsed:.0f}s\n"
    if output.strip():
        result += f"\n--- Recent output ---\n{output}"
    else:
        result += "\n(no recent output)"

    return result


def stop_background(pid: int) -> str:
    """Stop a background process."""
    with _bg_lock:
        entry = _background_processes.get(pid)
    if not entry:
        return f"Error: no tracked process with PID {pid}."

    proc = entry["proc"]
    if proc.poll() is not None:
        with _bg_lock:
            del _background_processes[pid]
        return f"Process {pid} already exited (code: {proc.returncode})."

    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
    except Exception as e:
        return f"Error stopping process: {e}"

    with _bg_lock:
        del _background_processes[pid]

    return f"Process {pid} stopped."


def list_background() -> str:
    """List all tracked background processes."""
    with _bg_lock:
        if not _background_processes:
            return "No background processes running."

        lines = []
        for pid, entry in _background_processes.items():
            proc = entry["proc"]
            alive = proc.poll() is None
            status = "RUNNING" if alive else f"EXITED ({proc.returncode})"
            elapsed = time.time() - entry["started_at"]
            lines.append(f"  PID {pid} | {status} | {elapsed:.0f}s | {entry['command']}")

        return "Background processes:\n" + "\n".join(lines)


TOOL_MAP = {
    "read_file": lambda wd, args: read_file(wd, args["path"]),
    "write_file": lambda wd, args: write_file(wd, args["path"], args["content"]),
    "edit_file": lambda wd, args: edit_file(wd, args["path"], args["old_str"], args["new_str"]),
    "list_files": lambda wd, args: list_files(wd, args.get("path", "."), args.get("depth", 2)),
    "run_command": lambda wd, args: run_command(wd, args["command"]),
    "run_background": lambda wd, args: run_background(wd, args["command"], args.get("wait_seconds", 5)),
    "check_background": lambda wd, args: check_background(args["pid"]),
    "stop_background": lambda wd, args: stop_background(args["pid"]),
    "list_background": lambda wd, args: list_background(),
}


def execute_tool(work_dir: str, name: str, arguments: str) -> str:
    """Execute a tool call and return the result string."""
    args = json.loads(arguments)
    handler = TOOL_MAP.get(name)
    if not handler:
        return f"Error: unknown tool '{name}'"
    return handler(work_dir, args)
