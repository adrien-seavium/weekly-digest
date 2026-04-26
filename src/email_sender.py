"""
email_sender.py
Renders the weekly digest as an HTML email and sends it via Gmail API.
"""

import os
import logging
from datetime import datetime
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape

from gmail_client import GmailClient

log = logging.getLogger(__name__)

HEAT_EMOJI = {"hot": "🔥", "warm": "🌡️", "cold": "❄️"}
URGENCY_EMOJI = {"high": "🚨", "medium": "⚠️", "low": "💬"}


class EmailSender:
    def __init__(self, config: dict):
        self.config = config
        self.gmail = GmailClient(config)
        self.recipient = os.environ["DIGEST_RECIPIENT_EMAIL"]
        template_dir = Path(__file__).parent.parent / "templates"
        self.env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=select_autoescape(["html"]),
        )
        self.env.globals["heat_emoji"] = HEAT_EMOJI
        self.env.globals["urgency_emoji"] = URGENCY_EMOJI

    def send(self, analysis: dict, run_date: datetime, team_name: str):
        sections = self.config["digest_sections"]
        week_label = run_date.strftime("%b %d, %Y")
        subject = f"[Weekly Digest] {team_name} — {week_label}"

        template = self.env.get_template("digest.html")
        html_body = template.render(
            team_name=team_name,
            week_label=week_label,
            sections=sections,
            replied_to_us=analysis.get("replied_to_us", []) if sections.get("replied_to_us") else [],
            no_reply=analysis.get("no_reply", []) if sections.get("no_reply") else [],
            we_didnt_reply=analysis.get("we_didnt_reply", []) if sections.get("we_didnt_reply") else [],
            active_projects=analysis.get("active_projects", []) if sections.get("active_projects") else [],
            saas_discussions=analysis.get("saas_discussions", []) if sections.get("saas_discussions") else [],
            crm_gaps=analysis.get("crm_gaps", []) if sections.get("crm_gaps") else [],
        )

        self.gmail.send_email(
            to=self.recipient,
            subject=subject,
            html_body=html_body,
        )
        log.info("Digest email sent to %s", self.recipient)
