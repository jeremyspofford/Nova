"""Run verification commands. Captures stdout/stderr tails + exit codes."""
from __future__ import annotations

import asyncio
import logging

log = logging.getLogger(__name__)

_TAIL_LIMIT = 4000  # bytes per stream


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
