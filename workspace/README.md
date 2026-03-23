# Nova Workspace (legacy default)

The default workspace location has moved to `~/.nova/workspace/`.

This directory exists for backward compatibility. If you have `NOVA_WORKSPACE`
set to this path in your `.env`, update it or remove the override to use the
new default.

## Configuring your workspace

Set `NOVA_WORKSPACE` in `.env` to point at any directory:

```
NOVA_WORKSPACE=/home/you/projects/my-app
```

Then restart the orchestrator:

```bash
docker compose up -d --no-deps orchestrator
```

## Security note

Everything in the workspace directory is accessible to Nova agents.
Do not place secrets, credentials, or `.env` files there.
