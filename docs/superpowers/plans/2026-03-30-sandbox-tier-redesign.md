# Sandbox Tier Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename sandbox tiers to Workspace/Home/Root/Isolated, add Docker volume mounts so Home and Root actually access the host filesystem, make tool descriptions tier-aware so agents know their access scope.

**Architecture:** The sandbox tier enum is renamed (with backward-compat aliases). Two Docker volumes are added to expose the host's home dir and root filesystem. `_resolve_path()` gains per-tier logic with transparent `/host-root` path translation for Root tier. Tool descriptions become dynamic via a factory function called at resolution time — the static registry stays untouched.

**Tech Stack:** Python (FastAPI, asyncpg), Docker Compose, React/TypeScript (dashboard), SQL migrations

**Spec:** `docs/superpowers/specs/2026-03-30-sandbox-tier-redesign-design.md`

---

### Task 1: Rename SandboxTier Enum + Backward Compat

**Files:**
- Modify: `orchestrator/app/tools/sandbox.py`
- Modify: `orchestrator/app/config.py:46-50`

- [ ] **Step 1: Update the SandboxTier enum in `sandbox.py`**

Replace the enum and add `_missing_` for backward compat:

```python
class SandboxTier(str, enum.Enum):
    isolated  = "isolated"
    workspace = "workspace"
    home      = "home"
    root      = "root"

    @classmethod
    def _missing_(cls, value):
        """Backward compat: accept old tier names during transition."""
        _ALIASES = {"nova": cls.home, "host": cls.root}
        return _ALIASES.get(value)
```

- [ ] **Step 2: Update `sandbox.py` module docstring**

Replace the module docstring (lines 1-16):

```python
"""
Sandbox tier system — controls filesystem and shell access scope per agent execution.

Tiers:
  workspace — paths scoped to /workspace (default)
  home      — paths scoped to user's home directory on the host
  root      — full host filesystem via /host-root mount
  isolated  — no filesystem or shell access

Usage:
  token = set_sandbox(SandboxTier.home)
  try:
      # ... agent execution ...
  finally:
      reset_sandbox(token)
"""
```

- [ ] **Step 3: Update `get_root()` in `sandbox.py`**

```python
def get_root() -> Path:
    from app.config import settings

    tier = get_sandbox()
    if tier == SandboxTier.workspace:
        return Path(settings.workspace_root).resolve()
    elif tier == SandboxTier.home:
        return Path(settings.home_root).resolve()
    elif tier == SandboxTier.root:
        return Path("/host-root")
    elif tier == SandboxTier.isolated:
        raise PermissionError("Filesystem access disabled in isolated sandbox tier")
    return Path(settings.workspace_root).resolve()
```

- [ ] **Step 4: Add `home_root` to `config.py`**

After the existing `nova_root` line (line 50), add:

```python
# HOME on the host — set via HOST_HOME env in docker-compose.yml.
# Default "/root" is the container's root home; only correct if HOST_HOME is set.
home_root: str = Field(default="/root", validation_alias=AliasChoices("HOST_HOME", "home_root"))
```

Update the comment on line 48:

```python
# Sandbox tier: workspace | home | root | isolated
shell_sandbox: str = "workspace"
```

- [ ] **Step 5: Verify enum backward compat works**

```bash
cd /home/jeremy/workspace/arialabs/nova && docker compose exec orchestrator python3 -c "
from app.tools.sandbox import SandboxTier
# New values
assert SandboxTier('workspace') == SandboxTier.workspace
assert SandboxTier('home') == SandboxTier.home
assert SandboxTier('root') == SandboxTier.root
# Old values via _missing_
assert SandboxTier('nova') == SandboxTier.home
assert SandboxTier('host') == SandboxTier.root
print('All assertions passed')
"
```

- [ ] **Step 6: Commit**

```bash
git add orchestrator/app/tools/sandbox.py orchestrator/app/config.py
git commit -m "refactor(sandbox): rename tiers — workspace/home/root/isolated with backward compat"
```

---

### Task 2: Update Path Resolution + Display Helper

**Files:**
- Modify: `orchestrator/app/tools/code_tools.py:1-171` (path helpers section)

- [ ] **Step 1: Add `HOST_ROOT_PREFIX` constant and `display_path()` helper**

Add after the imports (around line 24):

```python
HOST_ROOT_PREFIX = "/host-root"


def display_path(path: Path | str) -> str:
    """Convert internal container path to user-facing path.

    Root tier paths are prefixed with /host-root inside the container.
    Strip this prefix so agents and users see real host paths.
    """
    s = str(path)
    if s.startswith(HOST_ROOT_PREFIX):
        return s[len(HOST_ROOT_PREFIX):] or "/"
    return s
```

- [ ] **Step 2: Rewrite `_resolve_path()` with per-tier logic**

Replace the existing `_resolve_path` function (lines 150-171):

```python
def _resolve_path(relative: str) -> Path:
    """Resolve a path within the current sandbox tier's root.

    - workspace: relative paths only, scoped to /workspace
    - home: absolute or relative, scoped to $HOME
    - root: absolute or relative, transparently mapped to /host-root
    - isolated: raises PermissionError
    """
    from app.tools.sandbox import get_root, get_sandbox, SandboxTier

    tier = get_sandbox()

    if tier == SandboxTier.isolated:
        get_root()  # raises PermissionError

    root = get_root()

    if tier == SandboxTier.root:
        if relative.startswith("/"):
            candidate = (Path(HOST_ROOT_PREFIX) / relative.lstrip("/")).resolve()
        else:
            candidate = (Path(HOST_ROOT_PREFIX) / relative).resolve()
        if not str(candidate).startswith(HOST_ROOT_PREFIX):
            raise ValueError(
                f"Path '{relative}' resolves outside host filesystem mount. "
                "Directory traversal is not permitted."
            )
        return candidate

    if tier == SandboxTier.home:
        if relative.startswith("/"):
            candidate = Path(relative).resolve()
        else:
            candidate = (root / relative).resolve()
        if not str(candidate).startswith(str(root)):
            raise ValueError(
                f"Path '{relative}' resolves outside home directory '{root}'. "
                "Access denied in home sandbox tier."
            )
        return candidate

    # Workspace tier (default)
    candidate = (root / relative).resolve()
    if not str(candidate).startswith(str(root)):
        raise ValueError(
            f"Path '{relative}' resolves outside sandbox root '{root}'. "
            "Directory traversal is not permitted."
        )
    return candidate
```

- [ ] **Step 3: Commit**

```bash
git add orchestrator/app/tools/code_tools.py
git commit -m "feat(sandbox): per-tier path resolution with /host-root translation"
```

---

### Task 3: Integrate `display_path()` Into Tool Results

**Files:**
- Modify: `orchestrator/app/tools/code_tools.py:209-437` (tool execution functions)

- [ ] **Step 1: Update `_execute_list_dir` (lines 209-230)**

Replace the function:

```python
def _execute_list_dir(path: str, recursive: bool) -> str:
    target = _resolve_path(path)
    if not target.exists():
        return f"Path '{path}' does not exist."
    if not target.is_dir():
        return f"'{path}' is a file, not a directory."

    if recursive:
        entries = sorted(target.rglob("*"))
    else:
        entries = sorted(target.iterdir())

    if not entries:
        return f"Directory '{path}' is empty."

    lines = [f"Contents of {path}:"]
    for e in entries:
        try:
            rel = e.relative_to(target)
        except ValueError:
            rel = display_path(e)
        kind = "/" if e.is_dir() else ""
        lines.append(f"  {rel}{kind}")
    return "\n".join(lines)
```

- [ ] **Step 2: Update `_execute_read_file` (lines 233-245)**

Replace the function:

```python
def _execute_read_file(path: str) -> str:
    target = _resolve_path(path)
    if not target.exists():
        return f"File '{path}' does not exist."
    if not target.is_file():
        return f"'{path}' is a directory, not a file."

    MAX_CHARS = 8000
    text = target.read_text(encoding="utf-8", errors="replace")
    if len(text) > MAX_CHARS:
        truncated = len(text) - MAX_CHARS
        text = text[:MAX_CHARS] + f"\n\n[... {truncated} characters truncated ...]"
    return f"File: {display_path(target)}\n```\n{text}\n```"
```

- [ ] **Step 3: Update `_execute_write_file` (lines 248-255)**

Replace the function:

```python
def _execute_write_file(path: str, content: str) -> str:
    target = _resolve_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    existed = target.exists()
    target.write_text(content, encoding="utf-8")
    action = "Updated" if existed else "Created"
    byte_count = len(content.encode())
    return f"{action} '{display_path(target)}' ({byte_count} bytes, {content.count(chr(10)) + 1} lines)."
```

- [ ] **Step 4: Update `_execute_search_codebase` (lines 400-437)**

After the ripgrep subprocess completes, strip `/host-root` from output. Replace the output handling section (after `proc.communicate()`):

```python
    out = stdout.decode(errors="replace").strip()
    err = stderr.decode(errors="replace").strip()

    # Strip /host-root prefix from ripgrep output paths
    if HOST_ROOT_PREFIX + "/" in (out or ""):
        out = out.replace(HOST_ROOT_PREFIX + "/", "/")

    if proc.returncode == 1 and not out:
        return f"No matches found for '{pattern}' in '{path}'."
    if err:
        log.warning("rg stderr: %s", err)
    return out or f"No matches found for '{pattern}' in '{path}'."
```

- [ ] **Step 5: Commit**

```bash
git add orchestrator/app/tools/code_tools.py
git commit -m "feat(sandbox): display_path strips /host-root prefix from all tool results"
```

---

### Task 4: Fix Shell cwd/HOME + Update Command Blocking

**Files:**
- Modify: `orchestrator/app/tools/code_tools.py:258-367` (shell execution + command blocking)

- [ ] **Step 1: Fix `_execute_run_shell` HOME env and cwd defaults**

Replace the function (lines 258-314):

```python
async def _execute_run_shell(command: str, working_dir: str | None) -> str:
    from app.config import settings
    from app.tools.sandbox import get_sandbox, SandboxTier

    tier = get_sandbox()

    # Isolated tier blocks shell entirely
    if tier == SandboxTier.isolated:
        return "Command blocked: shell access is disabled in isolated sandbox tier."

    # Resolve working directory
    try:
        cwd = _resolve_path(working_dir) if working_dir else _resolve_path(".")
    except PermissionError as e:
        return f"Command blocked: {e}"
    if not cwd.exists():
        return f"Working directory '{working_dir}' does not exist."

    # Security check — tier-aware
    blocked, reason = _is_command_blocked(command, tier)
    if blocked:
        return f"Command blocked: {reason}"

    # Warning check — non-blocking, prepended to result
    warned, warning_msg = _is_command_warned(command)

    # Set HOME correctly per tier
    if tier == SandboxTier.root:
        shell_home = f"{HOST_ROOT_PREFIX}{settings.home_root}"
    elif tier == SandboxTier.home:
        shell_home = settings.home_root
    else:
        shell_home = str(cwd)

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "HOME": shell_home, "TERM": "dumb"},
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=settings.shell_timeout_seconds,
        )
    except asyncio.TimeoutError:
        proc.kill()
        return (
            f"Command timed out after {settings.shell_timeout_seconds}s.\n"
            f"Command: {command}"
        )

    out = stdout.decode(errors="replace").strip()
    err = stderr.decode(errors="replace").strip()

    parts = []
    if warned:
        parts.append(f"WARNING: {warning_msg}. The command ran — verify the result.")
    parts.extend([f"$ {command}", f"exit code: {proc.returncode}"])
    if out:
        parts.append(f"stdout:\n{out}")
    if err:
        parts.append(f"stderr:\n{err}")
    return "\n".join(parts)
```

- [ ] **Step 2: Update `_is_command_blocked` tier reference (line 350)**

Change:

```python
    if tier in (SandboxTier.workspace, SandboxTier.nova):
```

To:

```python
    if tier in (SandboxTier.workspace, SandboxTier.home):
```

- [ ] **Step 3: Commit**

```bash
git add orchestrator/app/tools/code_tools.py
git commit -m "fix(sandbox): correct shell HOME env per tier, update command blocking for home tier"
```

---

### Task 5: Dynamic Tool Descriptions

**Files:**
- Modify: `orchestrator/app/tools/code_tools.py:26-145` (tool definitions section)
- Modify: `orchestrator/app/tools/git_tools.py:24-114` (tool definitions section)

- [ ] **Step 1: Add `get_code_tools()` factory in `code_tools.py`**

Keep the existing `CODE_TOOLS` list as-is (it serves as the workspace default and is used for dispatch). Add the factory function after it:

```python
# Name-based lookup for stable parameter reuse across tiers
_CODE_PARAMS = {t.name: t.parameters for t in CODE_TOOLS}


def get_code_tools(tier: "SandboxTier") -> list[ToolDefinition]:
    """Generate tool definitions with tier-appropriate descriptions."""
    from app.tools.sandbox import SandboxTier

    if tier == SandboxTier.home:
        return [
            ToolDefinition(
                name="list_dir",
                description=(
                    "List files and directories at a path in your home directory. "
                    "Use absolute paths (e.g., '/home/user/project/src') or relative paths from home."
                ),
                parameters=_CODE_PARAMS["list_dir"],
            ),
            ToolDefinition(
                name="read_file",
                description=(
                    "Read the contents of a file in your home directory. "
                    "Use absolute paths (e.g., '/home/user/project/main.py') or relative. "
                    "Large files are truncated at 8000 characters."
                ),
                parameters=_CODE_PARAMS["read_file"],
            ),
            ToolDefinition(
                name="write_file",
                description=(
                    "Write or overwrite a file in your home directory. "
                    "Use absolute paths or relative. Creates parent directories automatically."
                ),
                parameters=_CODE_PARAMS["write_file"],
            ),
            ToolDefinition(
                name="run_shell",
                description=(
                    "Run a shell command with cwd in your home directory. "
                    "Commands run in a subprocess with a hard timeout. "
                    "Blocks sudo, curl|sh, and privilege escalation."
                ),
                parameters=_CODE_PARAMS["run_shell"],
            ),
            ToolDefinition(
                name="search_codebase",
                description=(
                    "Search for a pattern across files in your home directory using ripgrep. "
                    "Returns matching lines with file paths and line numbers."
                ),
                parameters=_CODE_PARAMS["search_codebase"],
            ),
        ]

    if tier == SandboxTier.root:
        return [
            ToolDefinition(
                name="list_dir",
                description=(
                    "List files and directories at any path on the host filesystem. "
                    "Use absolute paths (e.g., '/etc/nginx', '/var/log')."
                ),
                parameters=_CODE_PARAMS["list_dir"],
            ),
            ToolDefinition(
                name="read_file",
                description=(
                    "Read the contents of any file on the host filesystem. "
                    "Use absolute paths (e.g., '/etc/nginx/nginx.conf'). "
                    "Large files are truncated at 8000 characters."
                ),
                parameters=_CODE_PARAMS["read_file"],
            ),
            ToolDefinition(
                name="write_file",
                description=(
                    "Write or overwrite any file on the host filesystem. "
                    "Use absolute paths. Creates parent directories automatically."
                ),
                parameters=_CODE_PARAMS["write_file"],
            ),
            ToolDefinition(
                name="run_shell",
                description=(
                    "Run a shell command on the host. "
                    "Working directory defaults to home. "
                    "Use file tools (read_file, write_file) for accessing arbitrary host paths."
                ),
                parameters=_CODE_PARAMS["run_shell"],
            ),
            ToolDefinition(
                name="search_codebase",
                description=(
                    "Search for a pattern across files on the host filesystem using ripgrep. "
                    "Use absolute paths to scope the search (e.g., '/etc', '/home/user/project')."
                ),
                parameters=_CODE_PARAMS["search_codebase"],
            ),
        ]

    # workspace / isolated — return defaults
    return list(CODE_TOOLS)
```

- [ ] **Step 2: Add `get_git_tools()` factory in `git_tools.py`**

Add after the existing `GIT_TOOLS` list:

```python
# Name-based lookup for stable parameter reuse across tiers
_GIT_PARAMS = {t.name: t.parameters for t in GIT_TOOLS}


def get_git_tools(tier: "SandboxTier") -> list[ToolDefinition]:
    """Generate git tool definitions with tier-appropriate descriptions."""
    from app.tools.sandbox import SandboxTier

    if tier in (SandboxTier.home, SandboxTier.root):
        scope = "home directory" if tier == SandboxTier.home else "host filesystem"
        return [
            ToolDefinition(
                name="git_status",
                description=(
                    f"Show the working tree status of any git repository on the {scope}. "
                    "Returns staged, unstaged, and untracked file lists."
                ),
                parameters=_GIT_PARAMS["git_status"],
            ),
            ToolDefinition(
                name="git_diff",
                description=(
                    f"Show unstaged or staged changes in any git repository on the {scope}."
                ),
                parameters=_GIT_PARAMS["git_diff"],
            ),
            ToolDefinition(
                name="git_log",
                description=f"Show recent git commit history for any repo on the {scope}.",
                parameters=_GIT_PARAMS["git_log"],
            ),
            ToolDefinition(
                name="git_commit",
                description=(
                    f"Stage files and commit in any git repository on the {scope}."
                ),
                parameters=_GIT_PARAMS["git_commit"],
            ),
        ]

    return list(GIT_TOOLS)
```

- [ ] **Step 3: Commit**

```bash
git add orchestrator/app/tools/code_tools.py orchestrator/app/tools/git_tools.py
git commit -m "feat(sandbox): tier-aware tool description factories"
```

---

### Task 6: Wire Dynamic Descriptions Into Tool Resolution

**Files:**
- Modify: `orchestrator/app/tool_permissions.py:53-74`
- Modify: `orchestrator/app/pipeline/executor.py:765-777`
- Modify: `orchestrator/app/router.py:123-136`

- [ ] **Step 1: Update `resolve_effective_tools()` in `tool_permissions.py`**

Replace the function (lines 53-74):

```python
async def resolve_effective_tools(
    allowed_tools: list[str] | None = None,
    sandbox_tier: "SandboxTier | None" = None,
) -> tuple[list[ToolDefinition], set[str]]:
    """Centralized permission resolution — single entry point for all callers.

    Returns (effective_tools, disabled_groups) so callers can pass disabled_groups
    to the system prompt builder without a second DB query.

    Layers:
      1. Global permissions (disabled_groups from platform_config)
      2. Tier-aware descriptions (swap code/git tool descriptions for home/root)
      3. Pod allowlist (optional — filters within permitted tools)
    """
    from app.tools import get_permitted_tools
    from app.tools.sandbox import SandboxTier, get_sandbox

    disabled = await get_disabled_tool_groups()
    tools = get_permitted_tools(disabled)

    # Resolve tier: explicit param > contextvar > default (workspace)
    tier = sandbox_tier or get_sandbox()

    # Swap in tier-aware descriptions for Code and Git tools
    if tier not in (SandboxTier.workspace, SandboxTier.isolated):
        from app.tools.code_tools import get_code_tools
        from app.tools.git_tools import get_git_tools
        tier_tools = get_code_tools(tier) + get_git_tools(tier)
        tier_by_name = {t.name: t for t in tier_tools}
        tools = [tier_by_name.get(t.name, t) for t in tools]

    if allowed_tools is not None:
        allowed_set = set(allowed_tools)
        tools = [t for t in tools if t.name in allowed_set]

    return tools, disabled
```

- [ ] **Step 2: Fix `__members__` check in `executor.py` (lines 765-777)**

Replace the sandbox tier resolution block:

```python
    # Set sandbox tier — try pod config first, fall back to global platform_config
    tier = SandboxTier.workspace
    if pod.sandbox and pod.sandbox != "workspace":
        try:
            tier = SandboxTier(pod.sandbox)
        except ValueError:
            pass  # Unknown tier value — use default
    else:
        # Pod has default tier — check if the global platform config overrides it
        try:
            pool = get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT value #>> '{}' AS val FROM platform_config WHERE key = 'shell.sandbox'"
                )
            if row:
                try:
                    tier = SandboxTier(row["val"])
                except ValueError:
                    pass
        except Exception:
            pass  # DB unavailable — safe default
    sandbox_token = set_sandbox(tier)
```

- [ ] **Step 3: Fix `__members__` check in `router.py` (lines 123-136)**

Replace the function:

```python
async def _get_sandbox_tier() -> SandboxTier:
    """Read the sandbox tier from platform_config (DB), falling back to env var."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT value #>> '{}' AS val FROM platform_config WHERE key = 'shell.sandbox'"
            )
        if row:
            try:
                return SandboxTier(row["val"])
            except ValueError:
                pass
    except Exception:
        pass
    from app.config import settings as _s
    try:
        return SandboxTier(_s.shell_sandbox)
    except ValueError:
        return SandboxTier.workspace
```

- [ ] **Step 4: Commit**

```bash
git add orchestrator/app/tool_permissions.py orchestrator/app/pipeline/executor.py orchestrator/app/router.py
git commit -m "feat(sandbox): wire tier-aware descriptions into tool resolution, fix __members__ checks"
```

---

### Task 7: Docker Compose + Config Changes

**Files:**
- Modify: `docker-compose.yml:339-355`
- Modify: `.env.example`

- [ ] **Step 1: Add volume mounts and HOST_HOME env to `docker-compose.yml`**

In the orchestrator service `environment:` section, add:

```yaml
      HOST_HOME: ${HOME}
```

In the orchestrator service `volumes:` section, after the existing two mounts, add:

```yaml
      - ${HOME}:${HOME}:rw
      - /:/host-root:rw
```

- [ ] **Step 2: Update `.env.example`**

Add after the `NOVA_WORKSPACE` comment:

```bash
# Home/Root sandbox tiers mount ${HOME} and / respectively into the container.
# HOME is detected automatically. No configuration needed for these tiers.
```

- [ ] **Step 3: Verify mounts work**

```bash
cd /home/jeremy/workspace/arialabs/nova && docker compose up -d --build orchestrator && sleep 5 && docker compose exec orchestrator ls -la /host-root/etc/ | head -5 && docker compose exec orchestrator ls -la ${HOME}/ | head -5
```

Expected: both commands list real host files.

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml .env.example
git commit -m "feat(sandbox): add Home and Root tier volume mounts to orchestrator"
```

---

### Task 8: DB Migration

**Files:**
- Create: `orchestrator/app/migrations/050_sandbox_tier_rename.sql`

- [ ] **Step 1: Create migration file**

```sql
-- Rename sandbox tier values: nova → home, host → root
-- The SandboxTier enum's _missing_() method handles backward compat in code,
-- but we also update stored values so the DB reflects current names.

-- Global sandbox tier setting (key: shell.sandbox, value: bare JSON string)
UPDATE platform_config
SET value = '"home"'::jsonb, updated_at = NOW()
WHERE key = 'shell.sandbox' AND value #>> '{}' = 'nova';

UPDATE platform_config
SET value = '"root"'::jsonb, updated_at = NOW()
WHERE key = 'shell.sandbox' AND value #>> '{}' = 'host';

-- Update migration 037 description to reflect new tier names
UPDATE platform_config
SET description = 'Agent filesystem access tier: workspace (user projects), home (home directory), root (full host), isolated (no access)'
WHERE key = 'shell.sandbox';

-- Pod-level sandbox configs (stored in pods.config JSONB)
UPDATE pods
SET config = jsonb_set(config, '{sandbox}', '"home"')
WHERE config->>'sandbox' = 'nova';

UPDATE pods
SET config = jsonb_set(config, '{sandbox}', '"root"')
WHERE config->>'sandbox' = 'host';
```

- [ ] **Step 2: Verify migration runs on restart**

```bash
cd /home/jeremy/workspace/arialabs/nova && docker compose restart orchestrator && sleep 5 && docker compose exec orchestrator python3 -c "
import asyncio, asyncpg
async def check():
    conn = await asyncpg.connect('postgresql://nova:nova_dev_password@postgres:5432/nova')
    row = await conn.fetchrow(\"SELECT value #>> '{}' AS val FROM platform_config WHERE key = 'shell.sandbox'\")
    print(f'Current sandbox tier: {row[\"val\"]}')
    await conn.close()
asyncio.run(check())
"
```

- [ ] **Step 3: Commit**

```bash
git add orchestrator/app/migrations/050_sandbox_tier_rename.sql
git commit -m "migrate: rename sandbox tier values nova→home, host→root"
```

---

### Task 9: Dashboard UI — SandboxSection

**Files:**
- Modify: `dashboard/src/pages/settings/SandboxSection.tsx`

- [ ] **Step 1: Update `TierValue` type (line 9)**

```typescript
type TierValue = 'workspace' | 'home' | 'root' | 'isolated'
```

- [ ] **Step 2: Replace `TIERS` array (lines 11-71)**

```typescript
const TIERS: {
  value: TierValue
  label: string
  tagline: string
  bullets: string[]
  ring: string
  dot: string
}[] = [
  {
    value: 'workspace',
    label: 'Workspace',
    tagline: 'Project-scoped access',
    bullets: [
      'Read & write files in configured workspace',
      'Shell commands scoped to workspace',
      'Git operations scoped to workspace',
      'Blocks sudo, curl|sh, privilege escalation',
    ],
    ring: 'ring-emerald-500/60',
    dot: 'bg-emerald-500',
  },
  {
    value: 'home',
    label: 'Home',
    tagline: 'Home directory access',
    bullets: [
      'Read & write files in home directory',
      'Shell commands scoped to home',
      'Git operations on any repo in home',
      'Blocks sudo, curl|sh, privilege escalation',
    ],
    ring: 'ring-sky-500/60',
    dot: 'bg-sky-500',
  },
  {
    value: 'root',
    label: 'Root',
    tagline: 'Full host access',
    bullets: [
      'Read & write files on host filesystem',
      'Shell commands with cwd on host',
      'Git operations on any host repo',
      'Only blocks fork bombs, mkfs, dd, rm -rf /',
    ],
    ring: 'ring-red-500/60',
    dot: 'bg-red-500',
  },
  {
    value: 'isolated',
    label: 'Isolated',
    tagline: 'Pure reasoning mode',
    bullets: [
      'No filesystem access',
      'No shell commands',
      'No git operations',
      'Text responses only',
    ],
    ring: 'ring-stone-400/60 dark:ring-stone-500/60',
    dot: 'bg-stone-400 dark:bg-stone-500',
  },
]
```

- [ ] **Step 3: Replace `CAPABILITY_ROWS` (lines 75-84)**

```typescript
const CAPABILITY_ROWS: { label: string; values: Record<TierValue, string> }[] = [
  { label: 'Filesystem scope', values: { workspace: '/workspace', home: '~ (home dir)', root: '/ (entire host)', isolated: 'None' } },
  { label: 'File read & write', values: { workspace: 'Scoped', home: 'Scoped', root: 'Unrestricted', isolated: 'Blocked' } },
  { label: 'Shell commands', values: { workspace: 'Scoped', home: 'Scoped', root: 'Unrestricted', isolated: 'Blocked' } },
  { label: 'Git operations', values: { workspace: 'Scoped', home: 'Scoped', root: 'Unrestricted', isolated: 'Blocked' } },
  { label: 'sudo / su', values: { workspace: 'Blocked', home: 'Blocked', root: 'Allowed', isolated: 'N/A' } },
  { label: 'Remote exec (curl|sh)', values: { workspace: 'Blocked', home: 'Blocked', root: 'Allowed', isolated: 'N/A' } },
  { label: 'Destructive commands', values: { workspace: 'Blocked', home: 'Blocked', root: 'Blocked', isolated: 'N/A' } },
  { label: 'Best for', values: { workspace: 'Project work', home: 'Multi-project', root: 'Sysadmin', isolated: 'Reasoning' } },
]
```

- [ ] **Step 4: Verify dashboard builds**

```bash
cd /home/jeremy/workspace/arialabs/nova/dashboard && npm run build
```

Expected: no TypeScript errors.

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/pages/settings/SandboxSection.tsx
git commit -m "feat(dashboard): update sandbox UI — Workspace, Home, Root, Isolated"
```

---

### Task 10: Dashboard UI — Pods Sandbox Selector

**Files:**
- Modify: `dashboard/src/pages/Pods.tsx:527-538`

- [ ] **Step 1: Update `SANDBOX_TIERS` and `SANDBOX_DESCRIPTIONS` (lines 527-538)**

```typescript
const SANDBOX_TIERS = [
  { value: 'workspace', label: 'workspace' },
  { value: 'home', label: 'home' },
  { value: 'root', label: 'root' },
  { value: 'isolated', label: 'isolated' },
]

const SANDBOX_DESCRIPTIONS: Record<string, string> = {
  workspace: 'Paths scoped to workspace directory',
  home:      'Paths scoped to home directory',
  root:      'Full host filesystem access',
  isolated:  'No filesystem or shell access',
}
```

- [ ] **Step 2: Verify dashboard builds**

```bash
cd /home/jeremy/workspace/arialabs/nova/dashboard && npm run build
```

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/pages/Pods.tsx
git commit -m "feat(dashboard): update pod sandbox selector with new tier names"
```

---

### Task 11: Integration Test

**Files:**
- Modify: `tests/test_tool_permissions.py`

- [ ] **Step 1: Add sandbox tier rename test**

Append to `tests/test_tool_permissions.py`:

```python
class TestSandboxTierRename:
    """Verify sandbox tier rename and backward compat."""

    async def test_sandbox_setting_uses_new_names(
        self, orchestrator: httpx.AsyncClient, admin_headers: dict
    ):
        """Platform config should accept new tier names."""
        # Set to 'home' (new name)
        resp = await orchestrator.patch(
            "/api/v1/config",
            json={"key": "shell.sandbox", "value": "home"},
            headers=admin_headers,
        )
        assert resp.status_code == 200

        # Read it back
        resp = await orchestrator.get("/api/v1/config", headers=admin_headers)
        entries = {e["key"]: e for e in resp.json()}
        assert entries["shell.sandbox"]["value"] == "home"

    async def test_sandbox_setting_backward_compat(
        self, orchestrator: httpx.AsyncClient, admin_headers: dict
    ):
        """Old tier names ('nova', 'host') should still be accepted."""
        resp = await orchestrator.patch(
            "/api/v1/config",
            json={"key": "shell.sandbox", "value": "nova"},
            headers=admin_headers,
        )
        assert resp.status_code == 200

    async def test_sandbox_setting_reset_to_workspace(
        self, orchestrator: httpx.AsyncClient, admin_headers: dict
    ):
        """Clean up: reset sandbox to workspace."""
        resp = await orchestrator.patch(
            "/api/v1/config",
            json={"key": "shell.sandbox", "value": "workspace"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
```

- [ ] **Step 2: Run the test**

```bash
cd /home/jeremy/workspace/arialabs/nova && python -m pytest tests/test_tool_permissions.py -v -k "Sandbox"
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_tool_permissions.py
git commit -m "test: sandbox tier rename and backward compat integration tests"
```

---

### Task 12: Update Module Docstring

**Files:**
- Modify: `orchestrator/app/tools/code_tools.py:1-14`

- [ ] **Step 1: Update the module docstring**

```python
"""
Code & Terminal Tools — filesystem and shell access for Nova agents.

Access scope is controlled by the sandbox tier:
  workspace — paths scoped to /workspace (default)
  home      — paths scoped to user's home directory
  root      — full host filesystem via /host-root mount
  isolated  — no filesystem or shell access

Tools provided:
  list_dir          — directory listing
  read_file         — read a file's contents
  write_file        — create or overwrite a file
  run_shell         — execute a shell command with timeout
  search_codebase   — ripgrep search
"""
```

- [ ] **Step 2: Final dashboard build check**

```bash
cd /home/jeremy/workspace/arialabs/nova/dashboard && npm run build
```

- [ ] **Step 3: Commit**

```bash
git add orchestrator/app/tools/code_tools.py
git commit -m "docs: update code_tools docstring for new sandbox tiers"
```
