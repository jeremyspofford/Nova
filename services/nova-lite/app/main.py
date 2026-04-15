import logging
import signal
import time

from app.client import NovaClient, NovaClientError
from app.config import settings
from app.logic import executor, planner, summarizer, triage
from app.state import CursorState

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger(__name__)

_running = True


def _handle_signal(signum, frame):
    global _running
    log.info("Received signal %s, shutting down after current tick", signum)
    _running = False


def process_task(client, task: dict) -> None:
    """Act on a single pending task: approve, plan, execute, or summarize."""
    task_id = task["id"]

    if task.get("risk_class") == "high" or task.get("approval_required"):
        # POST /tasks/{id}/approvals sets task status=needs_approval server-side;
        # no separate patch_task call needed here.
        client.post_approval(task_id, {
            "summary": f"Nova-lite wants to act on: {task['title']}",
            "consequence": task.get("description"),
        })
        return

    current_plan = planner.plan(client, task)

    if not current_plan.actions:
        client.patch_task(task_id, {
            "status": "done",
            "result_summary": "No action needed. " + current_plan.reasoning,
        })
        return

    client.patch_task(task_id, {"status": "running"})
    results = executor.execute(client, task, current_plan)

    all_succeeded = bool(results) and all(r.get("status") == "succeeded" for r in results)
    summary = summarizer.summarize(client, task, current_plan, results)
    client.patch_task(task_id, {
        "status": "done" if all_succeeded else "failed",
        "result_summary": summary,
    })


def run_loop(client: NovaClient, state: CursorState) -> None:
    """Main polling loop. Runs until SIGTERM/SIGINT."""
    while _running:
        try:
            cursor = state.load_cursor()

            # ── 1. Triage new events ──────────────────────────
            events = client.get_events(since=cursor, limit=10)
            for event in events:
                try:
                    triage.classify_and_create(client, event)
                    cursor = event["timestamp"]
                except NovaClientError as e:
                    log.warning("Triage failed for event %s: %s", event.get("id"), e)
            state.save_cursor(cursor)

            # ── 2. Act on pending tasks ──────────────────────────
            tasks = client.get_tasks(status="pending", limit=5)
            for task in tasks:
                try:
                    process_task(client, task)
                except NovaClientError as e:
                    log.warning("Processing failed for task %s: %s", task.get("id"), e)

        except Exception as e:
            log.error("Loop error: %s", e, exc_info=True)

        if _running:
            time.sleep(settings.loop_interval_seconds)


def main() -> None:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    client = NovaClient(settings.nova_api_url)
    state = CursorState(settings.cursor_file)

    log.info("Nova-lite starting. API=%s interval=%ds", settings.nova_api_url, settings.loop_interval_seconds)
    try:
        run_loop(client, state)
    finally:
        client.close()
        log.info("Nova-lite stopped.")


if __name__ == "__main__":
    main()
