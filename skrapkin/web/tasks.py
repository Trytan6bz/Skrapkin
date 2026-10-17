"""Background tasks for the web interface: one at a time, with progress, log lines and live results."""

import logging
import threading
import time
import uuid
from collections import deque

log = logging.getLogger("skrapkin.tasks")

MAX_LOG_LINES = 300
KEEP_TASKS = 20


class Busy(Exception):
    """Another task is already running."""


class Task:
    def __init__(self, kind):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.state = "running"          # running | done | stopped | error
        self.done = self.total = 0
        self.logs = deque(maxlen=MAX_LOG_LINES)
        self.leads = []
        self.result = None
        self.error = ""
        self.stop = threading.Event()
        self.started = time.time()
        self._lock = threading.Lock()

    def log(self, message):
        with self._lock:
            self.logs.append(str(message)[:300])

    def progress(self, done, total):
        with self._lock:
            self.done, self.total = done, total

    def add_lead(self, lead):
        slim = {k: lead.get(k, "") for k in ("business", "website", "emails", "phones", "city", "confidence")}
        with self._lock:
            self.leads.append(slim)

    def snapshot(self, lead_cursor=0):
        with self._lock:
            return {
                "id": self.id, "kind": self.kind, "state": self.state, "error": self.error,
                "done": self.done, "total": self.total, "logs": list(self.logs),
                "leads": self.leads[lead_cursor:], "lead_count": len(self.leads), "result": self.result,
                "elapsed": round(time.time() - self.started, 1),
            }


class TaskManager:
    def __init__(self, describe_error=str, expected_errors=()):
        self.tasks = {}
        self._lock = threading.Lock()
        self._describe = describe_error
        self._expected = tuple(expected_errors)  # failures the user can act on: logged without a traceback

    def active(self):
        with self._lock:
            return next((t for t in self.tasks.values() if t.state == "running"), None)

    def get(self, task_id):
        with self._lock:
            return self.tasks.get(task_id)

    def start(self, kind, fn):
        """Run fn(task) on a background thread. Raises Busy if something else is running."""
        with self._lock:
            if any(t.state == "running" for t in self.tasks.values()):
                raise Busy()
            task = Task(kind)
            self.tasks[task.id] = task
            for old in sorted(self.tasks.values(), key=lambda t: t.started)[:-KEEP_TASKS]:
                if old.state != "running":
                    del self.tasks[old.id]

        def run():
            log.info("task %s (%s) started", task.id, kind)
            try:
                fn(task)
                task.state = "stopped" if task.stop.is_set() else "done"
            except Exception as e:  # surfaced to the UI and the log, never swallowed
                task.error = self._describe(e)
                task.state = "error"
                if isinstance(e, self._expected):
                    log.warning("task %s (%s) failed: %s", task.id, kind, task.error)
                else:
                    log.exception("task %s (%s) crashed", task.id, kind)
            log.info("task %s (%s) %s after %.0fs", task.id, kind, task.state, time.time() - task.started)

        threading.Thread(target=run, daemon=True).start()
        return task
