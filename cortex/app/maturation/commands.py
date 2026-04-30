"""Run verification commands. Captures stdout/stderr tails + exit codes."""
from __future__ import annotations

import asyncio
import logging

log = logging.getLogger(__name__)

_TAIL_LIMIT = 4000  # bytes per stream

# LLM-generated verification commands must START with one of these tokens.
# This is a defense-in-depth check — cortex runs in its own container, but a
# malicious or compromised LLM could otherwise execute arbitrary shell.
ALLOWED_PREFIXES = (
    "pytest", "python -m pytest", "python3 -m pytest",
    "npm test", "npm run", "pnpm test", "pnpm run", "yarn test",
    "make", "cargo test", "go test",
    "ruff", "mypy", "pyright", "tsc", "npx tsc",
    "docker compose ps",
    "curl -sf",
    "true", "false",  # for testing the verifier itself
)


def _is_allowed(cmd: str) -> bool:
    """True if cmd's first token (or two-word prefix for `python -m pytest`-style)
    matches the allowlist. Whitespace-tolerant; case-sensitive."""
    stripped = cmd.strip()
    return any(stripped == p or stripped.startswith(p + " ") for p in ALLOWED_PREFIXES)


async def run_commands(cmd_specs: list[dict]) -> list[dict]:
    """Execute each cmd spec and return per-command result dicts.

    Each spec: {"cmd": str, "cwd": str|None, "timeout_s": int|None}
    Each result: {"cmd": str, "exit_code": int, "stdout_tail": str, "stderr_tail": str, "duration_ms": int}
    """
    results = []
    for spec in cmd_specs or []:
        cmd = spec.get("cmd") or ""
        cwd = spec.get("cwd") or None
        timeout = float(spec.get("timeout_s") or 60)
        if not cmd:
            results.append({"cmd": "", "exit_code": -1,
                            "stdout_tail": "", "stderr_tail": "empty cmd", "duration_ms": 0})
            continue

        if not _is_allowed(cmd):
            results.append({
                "cmd": cmd,
                "exit_code": -4,
                "stdout_tail": "",
                "stderr_tail": f"command rejected: not in allowlist ({len(ALLOWED_PREFIXES)} prefixes)",
                "duration_ms": 0,
            })
            log.warning("Rejected non-allowlisted command: %s", cmd[:120])
            continue

        start = asyncio.get_event_loop().time()
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd, cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                exit_code = proc.returncode
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                stdout, stderr = b"", b"timed out"
                exit_code = -2
        except Exception as e:
            log.warning("Command '%s' failed to launch: %s", cmd, e)
            stdout, stderr = b"", str(e).encode()
            exit_code = -3

        duration_ms = int((asyncio.get_event_loop().time() - start) * 1000)
        results.append({
            "cmd": cmd,
            "exit_code": exit_code,
            "stdout_tail": stdout[-_TAIL_LIMIT:].decode("utf-8", errors="replace"),
            "stderr_tail": stderr[-_TAIL_LIMIT:].decode("utf-8", errors="replace"),
            "duration_ms": duration_ms,
        })
    return results
