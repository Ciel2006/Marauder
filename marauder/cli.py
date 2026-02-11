"""Marauder Code — CLI entry point."""
import os
import sys

from rich.console import Console
from rich.panel import Panel
from prompt_toolkit import prompt as pt_prompt
from prompt_toolkit.history import InMemoryHistory

from marauder import __version__
from marauder.config import prompt_config
from marauder.ai import create_client, test_connection
from marauder.agent import run_agent, set_view_mode, view_mode

console = Console()

BANNER = f"""\
[bold red]
    ▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄
    ██                                                                   ██
    ██  ███▄ ▄███  ▄████▄  ██████▄  ▄████▄  ██   ██ ██████▄ ██████ ██████▄
    ██  ████▄████ ██▀  ▀██ ██   ▀██▐█▀  ▀██ ██   ██ ██   ██ ██     ██   ██
    ██  ██ ███ ██ ████████ ██████▀ ████████ ██   ██ ██   ██ █████  ██████▀
    ██  ██  █  ██ ██    ██ ██  ▀█▄ ██    ██ ██▄ ▄██ ██  ▄██ ██     ██  ▀█▄
    ██  ██     ██ ██    ██ ██   ██ ██    ██  ▀████▀  █████▀  ██████ ██   ██
    ██                                                                   ██
    ██▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄[/bold red]
[bold yellow]              ░█▀▀ ░█▀█ ░█▀▄ ░█▀▀  v{__version__}[/bold yellow][dim]  ─────━━  ░░░[/dim]
[dim italic]
          "My name is Mar. My world is Codbase and fucking arround"
[/dim italic]"""


def main():
    console.print(BANNER)
    console.print()

    # Step 1: API config
    cfg = prompt_config()
    base_url = cfg["base_url"]
    api_key = cfg["api_key"]
    model = cfg["model"]

    # Step 2: Test connection
    console.print(f"\n  🔌 Testing connection to [cyan]{base_url}[/cyan] with model [cyan]{model}[/cyan]...")
    client = create_client(base_url, api_key)
    if not test_connection(client, model):
        console.print("  [red]Could not connect. Check your URL, key, and model.[/red]")
        sys.exit(1)
    console.print("  [green]✓ Connection successful![/green]\n")

    # Step 3: Pick working directory
    default_dir = os.getcwd()
    console.print(f"  📁 Current directory: [cyan]{default_dir}[/cyan]")
    use_current = pt_prompt("  Use current directory as workspace? [Y/n]: ").strip().lower()

    if use_current in ("", "y", "yes"):
        work_dir = default_dir
    else:
        while True:
            work_dir = pt_prompt("  Enter workspace path: ").strip()
            work_dir = os.path.abspath(os.path.expanduser(work_dir))
            if os.path.isdir(work_dir):
                break
            console.print(f"  [red]Directory not found: {work_dir}. Try again.[/red]")

    console.print(f"  [green]✓ Working in: {work_dir}[/green]\n")

    # Step 4: Pick view mode
    console.print("  📺 View mode:")
    console.print("     [cyan]1[/cyan] — normal: clean timer + summary (recommended)")
    console.print("     [cyan]2[/cyan] — advanced: see every file read/write/edit live\n")
    mode_choice = pt_prompt("  Pick mode [1]: ").strip()
    if mode_choice == "2":
        set_view_mode("advanced")
        console.print("  [dim]→ Advanced mode.[/dim]\n")
    else:
        set_view_mode("normal")
        console.print("  [dim]→ Normal mode.[/dim]\n")

    console.print("  Commands: [cyan]/quit[/cyan]  [cyan]/clear[/cyan]  [cyan]/mode[/cyan] (switch view)\n")

    # Step 4: Chat loop
    history = []
    input_history = InMemoryHistory()

    while True:
        try:
            user_input = pt_prompt("you > ", history=input_history).strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n  👋 Later!", style="dim")
            break

        if not user_input:
            continue
        if user_input.lower() in ("/quit", "/exit", "/q"):
            console.print("  👋 Later!", style="dim")
            break
        if user_input.lower() == "/clear":
            history = []
            console.print("  [dim]Context cleared.[/dim]")
            continue
        if user_input.lower() == "/mode":
            from marauder.agent import view_mode as current_mode
            new_mode = "advanced" if current_mode == "normal" else "normal"
            set_view_mode(new_mode)
            console.print(f"  [dim]Switched to {new_mode} mode.[/dim]")
            continue

        history = run_agent(client, model, work_dir, user_input, history)
        print()  # spacing


if __name__ == "__main__":
    main()
