#!/usr/bin/env python3
"""Terminal triage (replaces `workbench triage`). Run via `make triage`."""

from __future__ import annotations

import argparse
import os
import sys

import httpx


def triage(server_url: str, token: str) -> None:
    """Interactive triage loop -- fetch pending cards and read choices from stdin."""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    resp = httpx.get(f"{server_url}/api/triage/pending", headers=headers)
    if resp.status_code != 200:
        print(f"Error: {resp.status_code} {resp.text}")
        return

    cards = resp.json()
    if not cards:
        print("No pending triage cards.")
        return

    print(f"\n{len(cards)} card(s) pending triage.\n")

    for i, card in enumerate(cards):
        content = card.get("card_content", {})
        options = card.get("options", [])
        source = content.get("source_type", "unknown")
        summary = content.get("summary", "Unknown item")

        print(f"--- Card {i + 1}/{len(cards)} ---")
        print(f"[{source}] {summary}")
        print()
        for j, opt in enumerate(options, 1):
            print(f"  {j}. {opt['label']}")
        print("  s. Skip remaining")
        print()

        choice = input("Your choice: ").strip().lower()
        if choice == "s":
            print("Skipped remaining cards.")
            break

        try:
            choice_num = int(choice)
            if 1 <= choice_num <= len(options):
                resp = httpx.post(
                    f"{server_url}/api/triage/respond",
                    headers=headers,
                    json={"card_id": card["id"], "choice": choice_num},
                )
                if resp.status_code == 200:
                    action = resp.json().get("action", "unknown")
                    print(f"  -> {action}\n")
                else:
                    print(f"  Error: {resp.status_code}\n")
            else:
                print("  Invalid choice. Skipping.\n")
        except ValueError:
            print("  Invalid input. Skipping.\n")


def main() -> None:
    """Entry point for `scripts/triage.py` / `make triage`."""
    parser = argparse.ArgumentParser(
        prog="triage", description="Interactive terminal triage"
    )
    parser.add_argument(
        "--server",
        default="http://localhost:8421",
        help="Server URL",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="API token (or set WORKBENCH_API_TOKEN)",
    )
    args = parser.parse_args()

    token = args.token or os.environ.get("WORKBENCH_API_TOKEN", "")
    if not token:
        print("Error: --token or WORKBENCH_API_TOKEN required", file=sys.stderr)
        sys.exit(1)
    triage(args.server, token)


if __name__ == "__main__":
    main()
