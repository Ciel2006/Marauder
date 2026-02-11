"""File system tools the AI agent can use."""
import os
import json

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
            "description": "Run a shell command in the working directory and return stdout/stderr.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute."}
                },
                "required": ["command"],
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
    import subprocess
    try:
        result = subprocess.run(
            command, shell=True, cwd=work_dir,
            capture_output=True, text=True, timeout=30,
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += ("\n" if output else "") + result.stderr
        if result.returncode != 0:
            output += f"\n(exit code: {result.returncode})"
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: command timed out (30s limit)"
    except Exception as e:
        return f"Error: {e}"


TOOL_MAP = {
    "read_file": lambda wd, args: read_file(wd, args["path"]),
    "write_file": lambda wd, args: write_file(wd, args["path"], args["content"]),
    "edit_file": lambda wd, args: edit_file(wd, args["path"], args["old_str"], args["new_str"]),
    "list_files": lambda wd, args: list_files(wd, args.get("path", "."), args.get("depth", 2)),
    "run_command": lambda wd, args: run_command(wd, args["command"]),
}


def execute_tool(work_dir: str, name: str, arguments: str) -> str:
    """Execute a tool call and return the result string."""
    args = json.loads(arguments)
    handler = TOOL_MAP.get(name)
    if not handler:
        return f"Error: unknown tool '{name}'"
    return handler(work_dir, args)
