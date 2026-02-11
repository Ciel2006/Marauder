"""Marauder Code — Installer. Installs deps + registers 'marauder' as a global command."""
import subprocess
import sys
import os
import shutil

DEPS = ["openai", "rich", "prompt_toolkit"]

BANNER = """
    ▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄
    ██                                                                   ██
    ██  ███▄ ▄███  ▄████▄  ██████▄  ▄████▄  ██   ██ ██████▄ ██████ ██████▄
    ██  ████▄████ ██▀  ▀██ ██   ▀██▐█▀  ▀██ ██   ██ ██   ██ ██     ██   ██
    ██  ██ ███ ██ ████████ ██████▀ ████████ ██   ██ ██   ██ █████  ██████▀
    ██  ██  █  ██ ██    ██ ██  ▀█▄ ██    ██ ██▄ ▄██ ██  ▄██ ██     ██  ▀█▄
    ██  ██     ██ ██    ██ ██   ██ ██    ██  ▀████▀  █████▀  ██████ ██   ██
    ██                                                                   ██
    ██▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄
                    I N S T A L L E R  ─────━━  ░░░
"""


def install_deps():
    """Install missing Python dependencies."""
    missing = []
    for pkg in DEPS:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)

    if missing:
        print(f"  📦 Installing missing packages: {', '.join(missing)}")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", *missing, "--quiet"]
        )
        print("  ✓ Packages installed.\n")
    else:
        print("  ✓ All dependencies already installed.\n")


def install_package():
    """Install marauder as a package with the 'marauder' console entry point."""
    print("  📦 Installing Marauder Code as a global command...")
    project_dir = os.path.dirname(os.path.abspath(__file__))
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-e", project_dir, "--quiet"]
    )
    print("  ✓ Package installed.\n")


def verify_command():
    """Check that 'marauder' is reachable from PATH."""
    location = shutil.which("marauder")
    if location:
        print(f"  ✅ 'marauder' command is ready at: {location}")
        print("     Open any terminal and type: marauder")
        return True
    else:
        # Figure out where pip puts scripts on this platform
        if os.name == "nt":
            scripts_dir = os.path.join(os.path.dirname(sys.executable), "Scripts")
            shell_hint = "     Add it to PATH via System Environment Variables, then restart your terminal."
        else:
            # Linux/macOS: pip --user installs to ~/.local/bin
            user_bin = os.path.expanduser("~/.local/bin")
            venv_bin = os.path.join(os.path.dirname(sys.executable))
            # Check which one has the script
            if os.path.isfile(os.path.join(user_bin, "marauder")):
                scripts_dir = user_bin
            elif os.path.isfile(os.path.join(venv_bin, "marauder")):
                scripts_dir = venv_bin
            else:
                scripts_dir = user_bin  # most common case
            shell_hint = f'     Add this to your shell config (~/.bashrc or ~/.zshrc):\n       export PATH="$PATH:{scripts_dir}"\n     Then run: source ~/.bashrc  (or restart your terminal)'

        print("  ⚠️  'marauder' installed but not found in PATH.")
        print(f"     Scripts directory: {scripts_dir}")
        print(shell_hint)
        return False


def main():
    print(BANNER)
    print("  Setting up Marauder Code on your system...\n")

    install_deps()
    install_package()
    verify_command()

    print("\n  🎉 Installation complete!\n")


if __name__ == "__main__":
    main()
