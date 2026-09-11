"""
Gunicorn server config.

The scheduler (daily 9:45 AM job + weekly review) must start EXACTLY once. A
module-level side effect in app.py (`else: start_scheduler()`) is NOT a reliable way
to guarantee that under gunicorn: this module gets imported in more than one process
context — gunicorn's master process resolving `app:app`, and separately each actual
worker process after forking — and in practice both imports ran the side effect,
producing two independent live schedulers (see docs/REVISIONS.md for the incident this
caused: every recurring job, including the weekly review's billed Anthropic API call,
silently fired twice).

`post_fork` is a gunicorn server hook that is guaranteed to run exactly once per actual
worker process, and is never invoked in the master. Combined with `--workers 1` in the
Procfile, this guarantees the scheduler starts in exactly one place, exactly once.
"""


def post_fork(server, worker):
    from app import start_scheduler
    start_scheduler()
