"""API connection configuration."""
import json
import os

DEFAULT_CONFIG_PATH = os.path.expanduser("~/.marauder_config.json")
POINTER_PATH = os.path.expanduser("~/.marauder_config_path")


def _get_config_path() -> str:
    """Get the config file path. Checks pointer file first, falls back to default."""
    if os.path.exists(POINTER_PATH):
        with open(POINTER_PATH, "r") as f:
            path = f.read().strip()
            if path and os.path.isdir(os.path.dirname(path)):
                return path
    return DEFAULT_CONFIG_PATH


def _set_config_path(path: str):
    """Save the chosen config path to the pointer file."""
    with open(POINTER_PATH, "w") as f:
        f.write(path)


def load_config() -> dict | None:
    """Load saved config if it exists."""
    path = _get_config_path()
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return None


def save_config(base_url: str, api_key: str, model: str, context_limit: int = 128000):
    """Save config to disk."""
    path = _get_config_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump({
            "base_url": base_url, "api_key": api_key,
            "model": model, "context_limit": context_limit,
        }, f, indent=2)


def prompt_config() -> dict:
    """Ask user for API config interactively."""
    from prompt_toolkit import prompt as pt_prompt

    print("\n⚙️  Marauder Code — Setup\n")

    saved = load_config()
    if saved:
        config_path = _get_config_path()
        print(f"  Found saved config: {saved['base_url']} / model: {saved['model']}")
        print(f"  Config location: {config_path}")
        reuse = pt_prompt("  Use saved config? [Y/n]: ").strip().lower()
        if reuse in ("", "y", "yes"):
            return saved

    base_url = pt_prompt("  API Base URL (e.g. https://api.openai.com/v1): ").strip()
    api_key = pt_prompt("  API Key: ", is_password=True).strip()
    model = pt_prompt("  Model ID (e.g. gpt-4o, claude-3-opus): ").strip()
    ctx_input = pt_prompt("  Context window size in tokens [128000]: ").strip()
    context_limit = int(ctx_input) if ctx_input.isdigit() else 128000

    # Ask where to save
    default = _get_config_path()
    print(f"\n  Config save location (default: {default})")
    custom_path = pt_prompt(f"  Path [{default}]: ").strip()
    if custom_path:
        custom_path = os.path.abspath(os.path.expanduser(custom_path))
        # If they gave a directory, append the filename
        if os.path.isdir(custom_path):
            custom_path = os.path.join(custom_path, "marauder_config.json")
        _set_config_path(custom_path)

    cfg = {"base_url": base_url, "api_key": api_key, "model": model, "context_limit": context_limit}
    save_config(**cfg)
    print(f"  [saved to {_get_config_path()}]")
    return cfg
