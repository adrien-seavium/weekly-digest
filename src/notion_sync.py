"""
notion_sync.py
Cross-checks analysed companies against Notion CRM databases.
Detects CRM gaps (companies in emails but missing from Notion).
Archives each weekly digest as a Notion page.
"""

import os
import json
import logging
from datetime import datetime, timezone

from notion_client import Client

log = logging.getLogger(__name__)


class NotionSync:
    def __init__(self, config: dict):
        self.config = config
        self.client = Client(auth=os.environ["NOTION_TOKEN"])
        self.companies_db = os.environ["NOTION_COMPANIES_DB_ID"]
        self.contacts_db = os.environ["NOTION_CONTACTS_DB_ID"]
        self.opportunities_db = os.environ["NOTION_OPPORTUNITIES_DB_ID"]
        self.archive_db = os.environ.get("NOTION_DIGEST_ARCHIVE_DB_ID", "")
        self.cfg = config["notion"]

    # ── Public ────────────────────────────────────────────────────────────────

    def enrich(self, analysis: dict) -> dict:
        """
        Cross-check each company from the email analysis against Notion.
        Adds 'crm_gaps' list and 'notion_status' to each company entry.
        """
        notion_companies = self._fetch_all_companies()
        notion_domains = {
            self._extract_domain(c.get("domain", "")): c
            for c in notion_companies
            if c.get("domain")
        }
        notion_names = {c["name"].lower(): c for c in notion_companies if c.get("name")}

        crm_gaps = []
        for company in analysis.get("all_companies", []):
            domain = company.get("domain", "")
            name = company.get("company_name", "")
            match = notion_domains.get(domain) or notion_names.get(name.lower())
            if match:
                company["notion_status"] = match.get("status", "In CRM")
                company["in_crm"] = True
            else:
                company["notion_status"] = "Missing"
                company["in_crm"] = False
                crm_gaps.append(
                    {
                        "company_name": name,
                        "domain": domain,
                        "contacts": company.get("contacts", []),
                        "why_flagged": "Appeared in email threads — not found in Notion Companies DB",
                    }
                )

        analysis["crm_gaps"] = crm_gaps
        log.info(
            "CRM cross-check: %d in CRM, %d gaps detected.",
            len(analysis["all_companies"]) - len(crm_gaps),
            len(crm_gaps),
        )
        return analysis

    def archive_digest(self, analysis: dict, run_date: datetime, team_name: str):
        """Push a summary page to the Notion digest archive database."""
        if not self.archive_db:
            log.warning("NOTION_DIGEST_ARCHIVE_DB_ID not set — skipping archive.")
            return

        week_label = run_date.strftime("Week of %b %d, %Y")
        summary = self._build_summary_text(analysis)

        cfg = self.cfg["digest_archive_db"]
        try:
            self.client.pages.create(
                parent={"database_id": self.archive_db},
                properties={
                    cfg["name_property"]: {
                        "title": [{"text": {"content": f"{team_name} — {week_label}"}}]
                    },
                    cfg["week_property"]: {
                        "rich_text": [{"text": {"content": week_label}}]
                    },
                },
                children=[
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{"type": "text", "text": {"content": summary}}]
                        },
                    }
                ],
            )
            log.info("Digest archived to Notion — %s", week_label)
        except Exception as e:
            log.error("Failed to archive digest to Notion: %s", e)

    # ── Private ───────────────────────────────────────────────────────────────

    def _fetch_all_companies(self) -> list[dict]:
        """Fetch all company records from Notion (handles pagination)."""
        cfg = self.cfg["companies_db"]
        results = []
        cursor = None
        while True:
            kwargs: dict = {"database_id": self.companies_db}
            if cursor:
                kwargs["start_cursor"] = cursor
            try:
                response = self.client.databases.query(**kwargs)
            except Exception as e:
                log.error("Failed to query Notion Companies DB: %s", e)
                break

            for page in response.get("results", []):
                props = page.get("properties", {})
                name = self._extract_text(props.get(cfg["name_property"]))
                domain = self._extract_text(props.get(cfg.get("domain_property", "Domain")))
                status = self._extract_select(props.get(cfg.get("status_property", "Status")))
                results.append({"name": name, "domain": domain, "status": status})

            if not response.get("has_more"):
                break
            cursor = response.get("next_cursor")

        log.debug("Fetched %d companies from Notion.", len(results))
        return results

    @staticmethod
    def _extract_text(prop: dict | None) -> str:
        if not prop:
            return ""
        prop_type = prop.get("type", "")
        if prop_type == "title":
            items = prop.get("title", [])
        elif prop_type == "rich_text":
            items = prop.get("rich_text", [])
        elif prop_type == "url":
            return prop.get("url", "") or ""
        else:
            return ""
        return "".join(i.get("plain_text", "") for i in items).strip()

    @staticmethod
    def _extract_select(prop: dict | None) -> str:
        if not prop:
            return ""
        sel = prop.get("select") or {}
        return sel.get("name", "")

    @staticmethod
    def _extract_domain(value: str) -> str:
        """Normalize domain: strip www., lowercase."""
        return value.lower().replace("www.", "").strip("/").strip()

    @staticmethod
    def _build_summary_text(analysis: dict) -> str:
        lines = [
            f"Replied to us: {len(analysis.get('replied_to_us', []))} companies",
            f"No reply: {len(analysis.get('no_reply', []))} companies",
            f"We didn't reply: {len(analysis.get('we_didnt_reply', []))} companies",
            f"Active projects: {len(analysis.get('active_projects', []))}",
            f"SaaS discussions: {len(analysis.get('saas_discussions', []))}",
            f"CRM gaps: {len(analysis.get('crm_gaps', []))} companies to add",
        ]
        return "\n".join(lines)
