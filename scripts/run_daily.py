"""
CLI entrypoint for the daily job. Use this instead of the in-app APScheduler if you'd
rather run a separate Railway "Cron Job" service (Railway's own scheduler) that
executes this script on a schedule, instead of relying on the always-on web process.

Usage:
    python scripts/run_daily.py            # normal run, respects the 9:45/market gate
    python scripts/run_daily.py --force     # bypass the gate — local testing only

See docs/DEPLOYMENT.md for how to wire this up as a Railway Cron Job instead of the
default APScheduler-in-app approach.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.daily_job import run_daily_job  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Bypass the market/time gate. Local testing only.")
    args = parser.parse_args()

    if args.force:
        print("WARNING: --force bypasses the 9:45 AM ET / market-day gate. "
              "Use this for local testing only, never in a real scheduled deployment.")

    payload = run_daily_job(force=args.force)
    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
