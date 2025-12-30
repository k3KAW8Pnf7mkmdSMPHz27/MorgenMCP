#!/usr/bin/env python3
"""
MorgenMCP Development Environment Setup

This script configures direnv for automatic API key management.
Run this once after cloning the repository.

Usage:
    uv run setup-dev
"""

import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    """Configure direnv for automatic API key management."""
    print("🔧 MorgenMCP Development Environment Setup")
    print("===========================================")
    print()

    # Find project root (where pyproject.toml is)
    # Script is now in morgenmcp/, so project root is parent
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    envrc_file = project_root / ".envrc"
    
    # Verify we found the right directory
    if not (project_root / "pyproject.toml").exists():
        # Fallback to current working directory
        project_root = Path.cwd()
        envrc_file = project_root / ".envrc"

    # Check if direnv is installed
    if not shutil.which("direnv"):
        print("❌ direnv is not installed.")
        print()
        print("Please install direnv first:")
        print("  macOS:  brew install direnv")
        print("  Ubuntu: sudo apt install direnv")
        print()
        print("Then add the hook to your shell (~/.zshrc or ~/.bashrc):")
        print('  eval "$(direnv hook zsh)"   # for zsh')
        print('  eval "$(direnv hook bash)"  # for bash')
        print()
        print("After installing, run this script again.")
        return 1

    print("✓ direnv is installed")

    # Check if .envrc already exists
    if envrc_file.exists():
        print()
        print(f"⚠️  .envrc file already exists at: {envrc_file}")
        print()
        response = input("Do you want to overwrite it? [y/N] ").strip().lower()
        if response not in ("y", "yes"):
            print("Setup cancelled. Existing .envrc preserved.")
            return 0

    # Prompt for API key
    print()
    print("Get your Morgen API key from:")
    print("  https://platform.morgen.so/developers-api")
    print()
    api_key = input("Enter your Morgen API key: ").strip()

    if not api_key:
        print()
        print("❌ No API key provided. Setup cancelled.")
        return 1

    # Create .envrc file
    envrc_content = f"""\
# MorgenMCP Development Environment
# This file is automatically loaded by direnv when you enter this directory.
# Do not commit this file to version control!

export MORGEN_API_KEY="{api_key}"
"""
    envrc_file.write_text(envrc_content)
    print()
    print("✓ Created .envrc file")

    # Allow direnv for this directory
    try:
        subprocess.run(
            ["direnv", "allow"],
            cwd=project_root,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Failed to run 'direnv allow': {e}")
        print("You may need to run 'direnv allow' manually.")

    print()
    print("✅ Setup complete!")
    print()
    print("Your API key will now be automatically loaded when you enter this directory.")
    print()
    print("Try running:")
    print("  uv run morgenmcp")
    print("  uv run pytest")

    return 0


if __name__ == "__main__":
    sys.exit(main())
