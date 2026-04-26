#!/usr/bin/env python
"""
Send investment proposals to Slack.
Usage: .venv/bin/python scripts/send_slack_proposals.py --file /tmp/proposals.json
       .venv/bin/python scripts/send_slack_proposals.py --json '[{"ticker":...}]'
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", help="Path to JSON file containing proposals array")
    group.add_argument("--json", help="Inline JSON string of proposals array")
    args = parser.parse_args()

    if args.file:
        proposals = json.loads(Path(args.file).read_text())
    else:
        proposals = json.loads(args.json)

    if not isinstance(proposals, list):
        print(json.dumps({"error": "Expected a JSON array of proposals"}))
        sys.exit(1)

    if not proposals:
        print("No proposals to send.")
        return

    from investor.notifications.slack import SlackNotifier
    notifier = SlackNotifier()
    ok = notifier.send_proposals(proposals)
    if ok:
        print(f"Sent {len(proposals)} proposal(s) to Slack.")
    else:
        print("Slack send failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
