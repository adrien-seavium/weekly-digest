"""
weekly-digest — main.py
Entry point: orchestrates Gmail fetch → GPT-4o analysis → Notion cross-check → email send.
"""

import os
import sys
import yaml
import logging
from datetime import datetime, timezone
from pathlib import Path

from gmail_client import GmailClient
from analyzer import EmailAnalyzer
from notion_sync import NotionSync
from email_sender import EmailSender

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)


def load_config() -> dict:
    config_path = Path(__file__).parent.parent / "config.yaml"
    if not config_path.exists():
        config_path = Path(__file__).parent.parent / "config.yaml.example"
        log.warning("config.yaml not found — falling back to config.yaml.example")
    with open(config_path) as f:
        return yaml.safe_load(f)


def validate_env():
    required = [
        "GMAIL_CLIENT_ID",
        "GMAIL_CLIENT_SECRET",
        "GMAIL_REFRESH_TOKEN",
        "GMAIL_SENDER_ADDRESS",
        "OPENAI_API_KEY",
        "NOTION_TOKEN",
        "NOTION_COMPANIES_DB_ID",
        "NOTION_CONTACTS_DB_ID",
        "NOTION_OPPORTUNITIES_DB_ID",
        "DIGEST_RECIPIENT_EMAIL",
    ]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        log.error("Missing required environment variables: %s", ", ".join(missing))
        sys.exit(1)


def main():
    log.info("=== Weekly Digest starting ===")
    validate_env()
    config = load_config()

    run_date = datetime.now(timezone.utc)
    team_name = os.environ.get("DIGEST_TEAM_NAME") or config["digest"]["team_name"]

    # ── Step 1: Fetch emails from Gmail ──────────────────────────────────────
    log.info("Step 1/5 — Fetching Gmail threads (last %d days)…", config["digest"]["lookback_days"])
    gmail = GmailClient(config)
    threads = gmail.fetch_threads()
    log.info("Fetched %d email threads.", len(threads))

    if not threads:
        log.warning("No email threads found for the period. Exiting.")
        sys.exit(0)

    # ── Step 2: Analyse with GPT-4o ──────────────────────────────────────────
    log.info("Step 2/5 — Analysing threads with GPT-4o…")
    analyzer = EmailAnalyzer(config)
    analysis = analyzer.analyze(threads)
    log.info(
        "Analysis complete — %d companies identified.",
        len(analysis.get("all_companies", [])),
    )

    # ── Step 3: Cross-check with Notion CRM ──────────────────────────────────
    log.info("Step 3/5 — Cross-checking with Notion CRM…")
    notion = NotionSync(config)
    enriched = notion.enrich(analysis)
    log.info(
        "CRM gaps detected: %d companies missing from Notion.",
        len(enriched.get("crm_gaps", [])),
    )

    # ── Step 4: Archive digest to Notion ─────────────────────────────────────
    archive_db = os.environ.get("NOTION_DIGEST_ARCHIVE_DB_ID")
    if archive_db and config["digest_sections"].get("crm_gaps"):
        log.info("Step 4/5 — Archiving digest to Notion…")
        notion.archive_digest(enriched, run_date, team_name)
    else:
        log.info("Step 4/5 — Notion archive skipped (NOTION_DIGEST_ARCHIVE_DB_ID not set).")

    # ── Step 5: Send email digest ─────────────────────────────────────────────
    log.info("Step 5/5 — Sending email digest…")
    sender = EmailSender(config)
    sender.send(enriched, run_date, team_name)
    log.info("=== Weekly Digest complete ✓ ===")


if __name__ == "__main__":
    main()
