# Nova Workspace

This directory is mounted into the orchestrator container at `/workspace`.

Nova agents can read and write files here using the `read_file`, `write_file`,
`list_dir`, `run_shell`, `search_codebase`, and git tools.

## Using your own project

Point agents at your actual project by setting `NOVA_WORKSPACE` in `.env`:

```
NOVA_WORKSPACE=/Users/you/my-project
```

Then restart the orchestrator:

```bash
docker compose up -d --no-deps orchestrator
```

The `/workspace` mount updates automatically — no rebuild required.

## Security note

Everything in this directory is accessible to Nova agents.
Do not place secrets, credentials, or `.env` files here.
