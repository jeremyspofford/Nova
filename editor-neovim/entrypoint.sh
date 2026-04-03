#!/bin/sh
set -e

NVIM_CONFIG_DIR="${NVIM_CONFIG_DIR:-/root/.config/nvim}"

# Clone or pull dotfiles repo if configured
if [ -n "$EDITOR_DOTFILES_REPO" ]; then
  if [ ! -d "$NVIM_CONFIG_DIR/.git" ]; then
    echo "[editor-neovim] Cloning dotfiles from $EDITOR_DOTFILES_REPO"
    git clone "$EDITOR_DOTFILES_REPO" "$NVIM_CONFIG_DIR"
  else
    echo "[editor-neovim] Pulling latest dotfiles"
    cd "$NVIM_CONFIG_DIR" && git pull --ff-only || true
  fi
fi

echo "[editor-neovim] Starting ttyd + neovim"
exec ttyd --writable --base-path /editor-neovim --port 7681 nvim /workspace
