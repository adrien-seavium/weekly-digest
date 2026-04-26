"""
gmail_client.py — dual account: Adrien reads, Lisa sends.
"""

import os
import base64
import logging
import email.mime.multipart
import email.mime.text
from datetime import datetime, timedelta, timezone
from typing import Any

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


class GmailClient:
    def __init__(self, config: dict):
        self.config = config
        self.sender_address = os.environ["GMAIL_SENDER_ADDRESS"]

        self.sender_service = self._build_service(
            client_id=os.environ["GMAIL_CLIENT_ID"],
            client_secret=os.environ["GMAIL_CLIENT_SECRET"],
            refresh_token=os.environ["GMAIL_REFRESH_TOKEN"],
        )

        reader_refresh = os.environ.get("GMAIL_READER_REFRESH_TOKEN")
        if reader_refresh:
            self.reader_service = self._build_service(
                client_id=os.environ["GMAIL_READER_CLIENT_ID"],
                client_secret=os.environ["GMAIL_READER_CLIENT_SECRET"],
                refresh_token=reader_refresh,
            )
            self.reader_address = os.environ.get("GMAIL_READER_ADDRESS", "")
        else:
            self.reader_service = self.sender_service
            self.reader_address = self.sender_address

        log.info("Reader: %s | Sender: %s", self.reader_address, self.sender_address)

    def fetch_threads(self) -> list[dict]:
        lookback = self.config["digest"]["lookback_days"]
        exclude_labels = self.config["gmail"]["exclude_labels"]
        exclude_domains = set(self.config["gmail"]["exclude_domains"])
        min_messages = self.config["digest"]["min_thread_messages"]

        since_dt = datetime.now(timezone.utc) - timedelta(days=lookback)
        query = f"after:{int(since_dt.timestamp())}"
        for label in exclude_labels:
            query += f" -label:{label}"

        thread_ids = self._list_thread_ids(query)
        log.info("Found %d raw thread IDs.", len(thread_ids))

        threads = []
        for tid in thread_ids:
            thread = self._fetch_thread(tid, exclude_domains, min_messages)
            if thread:
                threads.append(thread)
        return threads

    def send_email(self, to: str, subject: str, html_body: str):
        msg = email.mime.multipart.MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.sender_address
        msg["To"] = to
        msg.attach(email.mime.text.MIMEText(html_body, "html"))
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        self.sender_service.users().messages().send(userId="me", body={"raw": raw}).execute()
        log.info("Email sent to %s", to)

    @staticmethod
    def _build_service(client_id: str, client_secret: str, refresh_token: str):
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
            token_uri="https://oauth2.googleapis.com/token",
            scopes=SCOPES,
        )
        creds.refresh(Request())
        return build("gmail", "v1", credentials=creds)

    def _list_thread_ids(self, query: str) -> list[str]:
        ids = []
        page_token = None
        while True:
            kwargs: dict[str, Any] = {"userId": "me", "q": query, "maxResults": 500}
            if page_token:
                kwargs["pageToken"] = page_token
            result = self.reader_service.users().threads().list(**kwargs).execute()
            ids += [t["id"] for t in result.get("threads", [])]
            page_token = result.get("nextPageToken")
            if not page_token:
                break
        return ids

    def _fetch_thread(self, thread_id: str, exclude_domains: set, min_messages: int) -> dict | None:
        data = self.reader_service.users().threads().get(userId="me", id=thread_id, format="full").execute()
        messages = data.get("messages", [])
        if len(messages) < min_messages:
            return None

        parsed_messages = [self._parse_message(m) for m in messages]

        external_emails = set()
        for m in parsed_messages:
            for addr in (m.get("from_addr", ""), *m.get("to_addrs", [])):
                domain = self._domain(addr)
                if domain and domain not in exclude_domains:
                    external_emails.add(addr.lower().strip())

        if not external_emails:
            return None

        domain_counts: dict[str, int] = {}
        for addr in external_emails:
            d = self._domain(addr)
            if d:
                domain_counts[d] = domain_counts.get(d, 0) + 1
        primary_domain = max(domain_counts, key=domain_counts.get) if domain_counts else ""

        last_message = parsed_messages[-1]
        return {
            "thread_id": thread_id,
            "subject": parsed_messages[0].get("subject", "(no subject)"),
            "message_count": len(parsed_messages),
            "primary_domain": primary_domain,
            "external_emails": list(external_emails),
            "last_sender": last_message.get("from_addr", ""),
            "last_date": last_message.get("date", ""),
            "snippet": data.get("snippet", ""),
            "messages": [
                {"from": m.get("from_addr"), "date": m.get("date"), "snippet": m.get("snippet", "")}
                for m in parsed_messages
            ],
        }

    def _parse_message(self, message: dict) -> dict:
        headers = {h["name"].lower(): h["value"] for h in message.get("payload", {}).get("headers", [])}
        return {
            "id": message["id"],
            "subject": headers.get("subject", ""),
            "from_addr": headers.get("from", ""),
            "to_addrs": [a.strip() for a in headers.get("to", "").split(",")],
            "date": headers.get("date", ""),
            "snippet": message.get("snippet", ""),
        }

    @staticmethod
    def _domain(email_addr: str) -> str:
        if "<" in email_addr:
            email_addr = email_addr.split("<")[-1].strip("> ")
        parts = email_addr.split("@")
        return parts[-1].lower().strip() if len(parts) == 2 else ""
