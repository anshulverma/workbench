#!/usr/bin/env python3
"""Test ingestion from all configured source adapters.

Usage:
    ~/.venv/workbench/bin/python scripts/test_ingestion.py [--source NAME] [--submit]

Options:
    --source NAME   Test only this source (phabricator, meta_tasks, google_docs)
    --submit        Submit items to the Workbench API (requires running server)
    --dry-run       Just poll sources and print items (default)
"""
import argparse
import asyncio
import json
import os
import sys

import httpx

API_URL = "http://localhost:8421"
API_TOKEN = os.environ.get("WORKBENCH_API_TOKEN", "dev-token")


async def test_phabricator():
    print("\n=== Phabricator ===")
    try:
        env = {**os.environ, "LD_LIBRARY_PATH": "/usr/local/fbcode/platform010/lib"}
        proc = await asyncio.create_subprocess_exec(
            "meta", "phabricator.diff", "list",
            "--author-is-me", "--include-only-open",
            "--output", "json", "--limit", "10",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode != 0:
            print(f"  FAIL: exit {proc.returncode} — {stderr.decode()[:200]}")
            return []
        diffs = json.loads(stdout.decode())
        print(f"  OK: {len(diffs)} diffs found")
        for d in diffs[:3]:
            print(f"    {d['number']} — {d['title'][:60]}")

        items = []
        for d in diffs:
            items.append({
                "text": json.dumps(d),
                "source_type": "diff",
                "source_id": f"{d['number']}_{d.get('updated', '')}",
                "label": f"{d['number']} — {d['title']}",
            })
        return items
    except Exception as e:
        print(f"  ERROR: {e}")
        return []


async def test_meta_tasks():
    print("\n=== Meta Tasks ===")
    owner = os.environ.get("USER", "anshulverma")
    try:
        env = {**os.environ, "LD_LIBRARY_PATH": "/usr/local/fbcode/platform010/lib"}
        proc = await asyncio.create_subprocess_exec(
            "meta", "tasks.task", "list",
            "--owner-is", owner,
            "--output", "json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode != 0:
            print(f"  FAIL: exit {proc.returncode} — {stderr.decode()[:200]}")
            return []
        tasks = json.loads(stdout.decode())
        print(f"  OK: {len(tasks)} tasks found")
        for t in tasks[:3]:
            print(f"    {t['number']} — {t['title'][:60]}")

        items = []
        for t in tasks:
            items.append({
                "text": json.dumps(t),
                "source_type": "meta_tasks",
                "source_id": f"T{t['number']}_{t.get('updated', '')}",
                "label": f"T{t['number']} — {t['title']}",
            })
        return items
    except Exception as e:
        print(f"  ERROR: {e}")
        return []


async def test_google_docs():
    print("\n=== Google Docs ===")
    from urllib.parse import quote
    query = quote("mimeType='application/vnd.google-apps.document'")
    endpoint = (
        f"https://www.googleapis.com/drive/v3/files"
        f"?q={query}"
        f"&orderBy=modifiedTime%20desc"
        f"&pageSize=10"
        f"&fields=files(id,name,modifiedTime,owners,lastModifyingUser)"
    )
    try:
        env = {**os.environ, "LD_LIBRARY_PATH": "/usr/local/fbcode/platform010/lib"}
        proc = await asyncio.create_subprocess_exec(
            "google-api-proxy", "api", "call", "GET", endpoint,
            "--token-class", "GoogleDriveAuthTokenAsSelf",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode != 0:
            print(f"  FAIL: exit {proc.returncode} — {stderr.decode()[:200]}")
            return []

        output = stdout.decode()
        json_start = output.find("{")
        if json_start < 0:
            print(f"  FAIL: no JSON in output — {output[:200]}")
            return []

        result = json.loads(output[json_start:])
        files = result.get("files", [])
        print(f"  OK: {len(files)} docs found")
        for f in files[:3]:
            print(f"    {f['name'][:60]} (modified {f.get('modifiedTime', 'N/A')[:10]})")

        items = []
        for f in files:
            doc_id = f["id"]
            modified = f.get("modifiedTime", "")
            items.append({
                "text": json.dumps(f),
                "source_type": "google_docs",
                "source_id": f"gdoc_{doc_id}_{modified}",
                "label": f"Doc: {f.get('name', '')}",
            })
        return items
    except Exception as e:
        print(f"  ERROR: {e}")
        return []


async def submit_items(items: list[dict]):
    """Submit items to the Workbench API."""
    print(f"\n=== Submitting {len(items)} items to Workbench API ===")

    async with httpx.AsyncClient() as client:
        # Check server health
        try:
            resp = await client.get(f"{API_URL}/health", timeout=5)
            health = resp.json()
            print(f"  Server: {health.get('status', 'unknown')} (v{health.get('version', '?')})")
        except Exception as e:
            print(f"  Server unreachable: {e}")
            return

        submitted = 0
        failed = 0
        for item in items:
            try:
                resp = await client.post(
                    f"{API_URL}/api/process",
                    json={"text": item["text"], "source_type": item["source_type"]},
                    headers={"Authorization": f"Bearer {API_TOKEN}"},
                    timeout=10,
                )
                if resp.status_code == 200:
                    result = resp.json()
                    submitted += 1
                    print(f"  [{submitted}] {item['label'][:50]} → job {result['job_id'][:8]}... ({result['status']})")
                else:
                    failed += 1
                    print(f"  FAIL: {item['label'][:50]} → {resp.status_code}: {resp.text[:100]}")
            except Exception as e:
                failed += 1
                print(f"  ERROR: {item['label'][:50]} → {e}")

        print(f"\n  Done: {submitted} submitted, {failed} failed")


async def check_results():
    """Check what's been processed."""
    print("\n=== Current State ===")
    async with httpx.AsyncClient() as client:
        headers = {"Authorization": f"Bearer {API_TOKEN}"}

        try:
            resp = await client.get(f"{API_URL}/api/items", headers=headers, timeout=5)
            items = resp.json()
            print(f"  Items: {len(items)}")
            for i in items[:5]:
                print(f"    [{i.get('priority', '?')}] {i.get('summary', '')[:60]} ({i.get('status', '')})")
        except Exception as e:
            print(f"  Items fetch failed: {e}")

        try:
            resp = await client.get(f"{API_URL}/api/triage/pending", headers=headers, timeout=5)
            cards = resp.json()
            print(f"  Pending triage cards: {len(cards)}")
        except Exception:
            pass

        try:
            resp = await client.get(f"{API_URL}/api/queue/dead-letter", headers=headers, timeout=5)
            dead = resp.json()
            if dead:
                print(f"  Dead letters: {len(dead)}")
                for d in dead[:3]:
                    print(f"    {d.get('source_type', '?')}: {d.get('error', '')[:60]}")
        except Exception:
            pass


SOURCE_MAP = {
    "phabricator": test_phabricator,
    "meta_tasks": test_meta_tasks,
    "google_docs": test_google_docs,
}


async def main():
    parser = argparse.ArgumentParser(description="Test Workbench ingestion")
    parser.add_argument("--source", choices=list(SOURCE_MAP.keys()), help="Test only this source")
    parser.add_argument("--submit", action="store_true", help="Submit items to Workbench API")
    parser.add_argument("--status", action="store_true", help="Just check current state")
    args = parser.parse_args()

    if args.status:
        await check_results()
        return

    all_items = []

    if args.source:
        items = await SOURCE_MAP[args.source]()
        all_items.extend(items)
    else:
        for name, test_fn in SOURCE_MAP.items():
            items = await test_fn()
            all_items.extend(items)

    print(f"\n=== Summary: {len(all_items)} total items from all sources ===")

    if args.submit and all_items:
        await submit_items(all_items)
        # Wait a bit for processing
        print("\nWaiting 5s for pipeline processing...")
        await asyncio.sleep(5)
        await check_results()
    elif all_items:
        print("  (Use --submit to send items to the Workbench API)")


if __name__ == "__main__":
    asyncio.run(main())
