---
title: "One-line install + --help everywhere"
date: 2026-04-28
---

Two small DX improvements that make Nova nicer to start and nicer to live with.

**`scripts/bootstrap.sh` + curl-pipe-bash one-liner.** New users can now install Nova with a single command:

```bash
curl -fsSL https://raw.githubusercontent.com/arialabs/nova/main/scripts/bootstrap.sh | bash
```

The bootstrap script checks for `git` and `docker`, clones the repo (defaults to `./nova`, override with `NOVA_DIR=<path>`), and re-attaches the install wizard to the controlling terminal so you land directly in the mode-selection prompt. Pass `--no-install` to clone without launching the wizard, or just keep using the `git clone && cd nova && ./install` flow if you'd rather audit the source first — both routes hit the same wizard.

**`--help` on every script.** Every user-facing script (`./install`, `./uninstall`, `scripts/install.sh`, `scripts/backup.sh`, `scripts/restore.sh`, `scripts/setup-remote-ollama.sh`, `scripts/detect_hardware.sh`, `scripts/bootstrap.sh`) now responds to `--help` / `-h` with a clear usage block — what the script does, how to invoke it, what flags and environment variables it accepts. No more "what does this script even do" — just append `--help`.
