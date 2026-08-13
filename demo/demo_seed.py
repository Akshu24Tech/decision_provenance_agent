"""
Demo script for Decision Provenance Agent.

Seeds the exact scenario from the README:
  1. Ingest: "We're using Postgres" (reasoning: simplicity)
  2. Ingest: "We're using Postgres with read replicas" (reasoning: load test bottleneck)
  3. Query current state -> shows record #2
  4. Query provenance -> shows both records + diff + trigger

Run this after starting the server:
  uvicorn app.main:app --reload

Usage:
  python demo/demo_seed.py
"""

import httpx
import time
import sys
import json

BASE_URL = "http://127.0.0.1:8000"


def pretty_print(title, data):
    """Print a section with formatting."""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")
    print(json.dumps(data, indent=2, default=str))


def check_server():
    """Check if the server is running."""
    try:
        r = httpx.get(f"{BASE_URL}/health", timeout=5)
        r.raise_for_status()
        print("[OK] Server is healthy")
        return True
    except Exception:
        print("[FAIL] Server is not running. Start it with:")
        print("  uvicorn app.main:app --reload")
        return False


def run_demo():
    """Run the full demo scenario."""
    if not check_server():
        sys.exit(1)

    client = httpx.Client(base_url=BASE_URL, timeout=30)

    # -- Step 1: Ingest initial database decision --
    print("\n\n[INGEST] STEP 1: Ingesting initial database decision...")
    print("   Input: 'We have decided to use Postgres for the user service. The team is familiar with it and it is simple to set up.'")

    r = client.post("/ingest", json={
        "text": (
            "We have decided to use Postgres for the user service. "
            "The team is familiar with it, most of our developers have "
            "experience with PostgreSQL, and it is simple to set up for "
            "our current scale. Decision made during the architecture "
            "review meeting on January 15th."
        )
    })
    result1 = r.json()
    pretty_print("Step 1 Result", result1)

    # Small delay to simulate time passing
    time.sleep(2)

    # -- Step 2: Ingest revised decision (3 "weeks" later) --
    print("\n\n[INGEST] STEP 2: Ingesting revised database decision (simulating 3 weeks later)...")
    print("   Input: 'After load testing, we are adding read replicas to Postgres.'")

    r = client.post("/ingest", json={
        "text": (
            "After running load tests for the past two weeks, we have discovered "
            "that a single Postgres instance cannot handle our projected Q3 traffic. "
            "We are switching to Postgres with read replicas. The load test report "
            "showed 3x the expected query volume on the read path. Decision updated "
            "based on load test results from February 5th."
        )
    })
    result2 = r.json()
    pretty_print("Step 2 Result", result2)

    time.sleep(1)

    # -- Step 3: Query current state --
    print("\n\n[QUERY] STEP 3: Querying current state -- 'what is the database decision NOW?'")

    # We need to find the topic_key that was assigned
    topic_key = None
    r = client.get("/topics")
    topics = r.json()
    pretty_print("Available Topics", topics)

    if topics.get("topics"):
        topic_key = topics["topics"][0]  # Use the first (likely only) topic
    else:
        print("[WARNING] No topics found -- the pipeline may not have stored anything.")
        return

    r = client.get(f"/query/{topic_key}?mode=current")
    current = r.json()
    pretty_print(f"Current State for '{topic_key}'", current)

    # -- Step 4: Query provenance --
    print(f"\n\n[QUERY] STEP 4: Querying provenance -- 'WHY did the database decision change?'")
    print("   This is what flat memory stores CANNOT answer.\n")

    r = client.get(f"/query/{topic_key}?mode=provenance")
    provenance = r.json()
    pretty_print(f"Decision Provenance for '{topic_key}'", provenance)

    # -- Summary --
    print("\n\n" + "="*60)
    print("  DEMO SUMMARY")
    print("="*60)
    records = provenance.get("records", [])
    print(f"\n  Total revisions tracked: {len(records)}")
    for i, rec in enumerate(records):
        trigger = rec.get("change_trigger", "--initial decision--")
        print(f"\n  Revision {i+1}:")
        print(f"     Claim: {rec['claim']}")
        print(f"     Trigger: {trigger}")
        print(f"     Confidence: {rec['confidence']}")
        if rec.get("supersedes"):
            print(f"     Supersedes: {rec['supersedes'][:8]}...")

    print(f"\n\n[DONE] This is decision provenance -- not just 'what is true now'")
    print(f"   but 'why we changed our minds, and when, and because of what.'")
    print()


if __name__ == "__main__":
    run_demo()
