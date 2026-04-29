---
title: "./uninstall — clean removal in one command"
date: 2026-04-28
---

Nova now ships with a top-level `./uninstall` script that removes everything Nova installed on the machine: containers, networks, named volumes, locally-built Docker images, the bind-mounted `data/` directory, `backups/`, `.env` and its backups, build artifacts (`dist/`, `node_modules/`, `__pycache__`, `.pytest_cache`), and the agent workspace at `~/.nova/workspace/`.

The flow is preview-first: `./uninstall` always shows you exactly what will be deleted, broken down by category with disk-size totals, before asking for an explicit `uninstall` confirmation. Pass `--dry-run` to see the preview without any destruction, or `--yes` to skip the confirmation in scripted contexts.

The cloned repo source itself is left intact (delete it manually with `cd .. && rm -rf nova` if you want), and shared upstream Docker images (`ollama/ollama`, `pgvector/pgvector`, `redis`, etc.) are NOT touched — they may be in use by other Docker projects on the same machine. Use `docker image prune -a` separately if you want a deeper sweep.

For routine "reset Nova to a clean slate while keeping it installed," use the in-app factory reset under Settings → System. `./uninstall` is for "Nova is leaving this machine."

**Also in this release:** the top-level `setup` script and `scripts/setup.sh` have been renamed to `install` and `scripts/install.sh` to match the conventional install/uninstall pairing. The `make setup` target is now `make install`.
