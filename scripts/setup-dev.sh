#!/bin/bash
#
# MorgenMCP Development Environment Setup
#
# This script configures direnv for automatic API key management.
# Run this once after cloning the repository.
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENVRC_FILE="$PROJECT_ROOT/.envrc"

echo "🔧 MorgenMCP Development Environment Setup"
echo "==========================================="
echo ""

# Check if direnv is installed
if ! command -v direnv &> /dev/null; then
    echo "❌ direnv is not installed."
    echo ""
    echo "Please install direnv first:"
    echo "  macOS:  brew install direnv"
    echo "  Ubuntu: sudo apt install direnv"
    echo ""
    echo "Then add the hook to your shell (~/.zshrc or ~/.bashrc):"
    echo '  eval "$(direnv hook zsh)"   # for zsh'
    echo '  eval "$(direnv hook bash)"  # for bash'
    echo ""
    echo "After installing, run this script again."
    exit 1
fi

echo "✓ direnv is installed"

# Check if .envrc already exists
if [ -f "$ENVRC_FILE" ]; then
    echo ""
    echo "⚠️  .envrc file already exists at: $ENVRC_FILE"
    echo ""
    read -p "Do you want to overwrite it? [y/N] " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Setup cancelled. Existing .envrc preserved."
        exit 0
    fi
fi

# Prompt for API key
echo ""
echo "Get your Morgen API key from:"
echo "  https://platform.morgen.so/developers-api"
echo ""
read -p "Enter your Morgen API key: " -r API_KEY

if [ -z "$API_KEY" ]; then
    echo ""
    echo "❌ No API key provided. Setup cancelled."
    exit 1
fi

# Create .envrc file
cat > "$ENVRC_FILE" << EOF
# MorgenMCP Development Environment
# This file is automatically loaded by direnv when you enter this directory.
# Do not commit this file to version control!

export MORGEN_API_KEY="$API_KEY"
EOF

echo ""
echo "✓ Created .envrc file"

# Allow direnv for this directory
cd "$PROJECT_ROOT"
direnv allow

echo ""
echo "✅ Setup complete!"
echo ""
echo "Your API key will now be automatically loaded when you enter this directory."
echo ""
echo "Try running:"
echo "  uv run morgenmcp"
echo "  uv run pytest"
