"""
notion_sync.py — cross-check CRM and create weekly follow-up note.
Compatible with notion-client v3.
Matches companies by email domain against Notion Contacts DB email field.
"""

import os
import logging
from datetime import datetime

from notion_client import Client

log = logging.getLogger(__name__)

WEEKLY_DEBRIEF_PAGE_ID = "34ee7ec88d9280efa636cfb44c41b8a9"


class NotionSync:
    def __init__(self, config: dict):
        self.config = config
        self.client = Client(auth=os.environ["NOTION_TOKEN"])
        self.companies_db = os.environ["NOTION_COMPANIES_DB_ID"]
        self.contacts_db = os.environ["NOTION_CONTACTS_DB_ID"]
        self.opportunities_db = os.environ["NOTION_OPPORTUNITIES_DB_ID"]
        self.cfg = self.config["notion"]

    def enrich(self, analysis: dict) -> dict:
        """Cross-check emails against Notion Contacts DB (match by email domain)."""
        notion_domains = self._fetch_contact_domains()

        crm_gaps = []
        for company in analysis.get("all_companies", []):
            domain = company.get("domain", "")
            name = company.get("company_name", "")
            if self._norm(domain) in notion_domains:
                company["in_crm"] = True
                company["notion_status"] = "In CRM"
            else:
                company["in_crm"] = False
                company["notion_status"] = "Missing"
                crm_gaps.append({
                    "company_name": name,
                    "domain": domain,
                    "contacts": company.get("contacts", []),
                })

        analysis["crm_gaps"] = crm_gaps
        log.info("CRM check: %d in CRM, %d gaps.", len(analysis["all_companies"]) - len(crm_gaps), len(crm_gaps))
        return analysis

    def create_weekly_note(self, analysis: dict, run_date: datetime, team_name: str):
        """Create a weekly follow-up checklist page under Weekly Debrief."""
        week_label = run_date.strftime("Week %d %b %Y")
        content = self._build_checklist(analysis)

        try:
            self.client.pages.create(
                parent={"page_id": WEEKLY_DEBRIEF_PAGE_ID},
                properties={
                    "title": {"title": [{"text": {"content": f"🗓 {week_label} — Follow-up"}}]}
                },
                children=content,
            )
            log.info("Weekly Notion note created — %s", week_label)
        except Exception as e:
            log.error("Failed to create weekly Notion note: %s", e)

    # ── Private ───────────────────────────────────────────────────────────────

    def _fetch_contact_domains(self) -> set:
        """Fetch all email domains from the Contacts DB."""
        cfg = self.cfg["contacts_db"]
        email_prop = cfg.get("email_property", "Email Address")
        domains = set()
        cursor = None
        while True:
            try:
                kwargs = {"database_id": self.contacts_db}
                if cursor:
                    kwargs["start_cursor"] = cursor
                response = self.client.databases.query(**kwargs)
            except Exception as e:
                log.error("Failed to query Notion Contacts DB: %s", e)
                break
            for page in response.get("results", []):
                props = page.get("properties", {})
                email = self._text(props.get(email_prop))
                if "@" in email:
                    domain = email.split("@")[-1].lower().strip()
                    domains.add(self._norm(domain))
            if not response.get("has_more"):
                break
            cursor = response.get("next_cursor")
        log.info("Fetched %d contact domains from Notion.", len(domains))
        return domains

    def _build_checklist(self, analysis: dict) -> list:
        """Build Notion block content for the weekly follow-up checklist."""
        blocks = []

        def heading(text):
            return {
                "object": "block", "type": "heading_2",
                "heading_2": {"rich_text": [{"type": "text", "text": {"content": text}}]}
            }

        def todo(text, checked=False):
            return {
                "object": "block", "type": "to_do",
                "to_do": {
                    "rich_text": [{"type": "text", "text": {"content": text}}],
                    "checked": checked
                }
            }

        def divider():
            return {"object": "block", "type": "divider", "divider": {}}

        # They replied — follow up
        replied = analysis.get("replied_to_us", [])
        if replied:
            blocks.append(heading("✅ They replied — keep the momentum"))
            for c in replied:
                action = c.get("next_action", "Follow up")
                blocks.append(todo(f"{c['company_name']} — {action}"))
            blocks.append(divider())

        # We didn't reply — priority
        to_reply = analysis.get("we_didnt_reply", [])
        if to_reply:
            blocks.append(heading("🚨 They're waiting — reply first"))
            for c in sorted(to_reply, key=lambda x: x.get("urgency", "low"), reverse=True):
                blocks.append(todo(f"{c['company_name']} — {c.get('topic', '')}"))
            blocks.append(divider())

        # No reply — push
        no_reply = analysis.get("no_reply", [])
        if no_reply:
            blocks.append(heading("📭 No reply — push & follow up"))
            for c in no_reply:
                sender = c.get("last_sender_name", "")
                sender_str = f" (last sent by {sender})" if sender else ""
                blocks.append(todo(f"{c['company_name']}{sender_str} — {c.get('suggested_followup', 'Follow up')}"))
            blocks.append(divider())

        # Active projects
        projects = analysis.get("active_projects", [])
        if projects:
            blocks.append(heading("📁 Active projects — check status"))
            for p in projects:
                blocks.append(todo(f"{p['company_name']} [{p.get('current_stage', '')}] — {p.get('next_step', '')}"))
            blocks.append(divider())

        # CRM gaps
        gaps = analysis.get("crm_gaps", [])
        if gaps:
            blocks.append(heading("⚠️ Add to Notion CRM"))
            for g in gaps:
                blocks.append(todo(f"{g['company_name']} ({g.get('domain', '')})"))

        return blocks

    @staticmethod
    def _text(prop: dict | None) -> str:
        if not prop:
            return ""
        t = prop.get("type", "")
        if t == "title":
            items = prop.get("title", [])
        elif t == "rich_text":
            items = prop.get("rich_text", [])
        elif t == "email":
            return prop.get("email", "") or ""
        elif t == "url":
            return prop.get("url", "") or ""
        else:
            return ""
        return "".join(i.get("plain_text", "") for i in items).strip()

    @staticmethod
    def _norm(value: str) -> str:
        return value.lower().replace("www.", "").strip("/").strip()
