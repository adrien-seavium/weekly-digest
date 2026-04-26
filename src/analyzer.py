"""
analyzer.py
Sends email thread data to GPT-4o and returns structured classification
across the five digest sections.
"""

import os
import json
import logging
from openai import OpenAI

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert sales analyst. You will receive a batch of email thread summaries
from a company's Gmail inbox covering the past 7 days.

Your task is to classify each thread and extract key business intelligence.

The company's own email domain(s) will be excluded from threads — all remaining
participants are external contacts (prospects, clients, partners).

Return ONLY valid JSON matching the schema below — no markdown, no explanation.

Schema:
{
  "all_companies": [
    {
      "company_name": "string — best guess at company name from email domain or content",
      "domain": "string — primary external email domain",
      "contacts": ["list of external email addresses"],
      "thread_ids": ["list of thread_ids involving this company"]
    }
  ],
  "replied_to_us": [
    {
      "company_name": "string",
      "domain": "string",
      "last_reply_date": "YYYY-MM-DD",
      "topic": "string — 1 sentence summary of the discussion",
      "next_action": "string — suggested follow-up in 1 sentence",
      "heat": "hot|warm|cold"
    }
  ],
  "no_reply": [
    {
      "company_name": "string",
      "domain": "string",
      "last_contact_date": "YYYY-MM-DD",
      "topic": "string",
      "days_waiting": integer,
      "suggested_followup": "string — 1 sentence"
    }
  ],
  "we_didnt_reply": [
    {
      "company_name": "string",
      "domain": "string",
      "last_inbound_date": "YYYY-MM-DD",
      "topic": "string",
      "urgency": "high|medium|low"
    }
  ],
  "active_projects": [
    {
      "company_name": "string",
      "domain": "string",
      "project_type": "string — e.g. SaaS demo, consulting, partnership, chartering, etc.",
      "project_name": "string — inferred name or description",
      "current_stage": "string — e.g. initial contact, proposal sent, negotiation, signed",
      "key_info": "string — most important detail from the thread",
      "next_step": "string"
    }
  ],
  "saas_discussions": [
    {
      "company_name": "string",
      "domain": "string",
      "discussion_type": "string — e.g. trial request, pricing question, renewal, upsell",
      "status": "string",
      "next_action": "string"
    }
  ]
}

Classification rules:
- "replied_to_us": the last message in the thread was sent by an EXTERNAL contact
- "no_reply": we sent the last message and received no reply; thread is at least 2 days old
- "we_didnt_reply": the last message was sent by an external contact and predates our last outbound by at least 24h, OR we have never replied
- "active_projects": any thread where a concrete project, deal, or collaboration is being discussed (can overlap with other sections)
- "saas_discussions": threads specifically about software/platform/subscription topics
- "heat" scoring: hot = reply within 48h or explicit meeting/demo request; warm = reply within the week; cold = reply but low engagement
- A single company can appear in multiple sections if they have multiple threads
"""


class EmailAnalyzer:
    def __init__(self, config: dict):
        self.config = config
        self.client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        self.model = config["openai"]["model"]
        self.batch_size = config["openai"]["batch_size"]
        self.max_tokens = config["openai"]["max_tokens"]

    def analyze(self, threads: list[dict]) -> dict:
        """Analyze all threads in batches and merge results."""
        batches = [
            threads[i : i + self.batch_size]
            for i in range(0, len(threads), self.batch_size)
        ]
        log.info("Sending %d batch(es) to GPT-4o…", len(batches))

        results = []
        for i, batch in enumerate(batches):
            log.debug("Batch %d/%d (%d threads)…", i + 1, len(batches), len(batch))
            result = self._analyze_batch(batch)
            if result:
                results.append(result)

        return self._merge_results(results)

    def _analyze_batch(self, threads: list[dict]) -> dict | None:
        user_content = json.dumps(
            [
                {
                    "thread_id": t["thread_id"],
                    "subject": t["subject"],
                    "primary_domain": t["primary_domain"],
                    "external_emails": t["external_emails"],
                    "last_sender": t["last_sender"],
                    "last_date": t["last_date"],
                    "message_count": t["message_count"],
                    "messages": t["messages"],
                    "snippet": t["snippet"],
                }
                for t in threads
            ],
            ensure_ascii=False,
            indent=2,
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content
            return json.loads(raw)
        except Exception as e:
            log.error("GPT-4o batch analysis failed: %s", e)
            return None

    def _merge_results(self, results: list[dict]) -> dict:
        """Merge multiple batch results, deduplicating by domain."""
        merged: dict = {
            "all_companies": [],
            "replied_to_us": [],
            "no_reply": [],
            "we_didnt_reply": [],
            "active_projects": [],
            "saas_discussions": [],
        }
        seen_domains: dict[str, dict[str, set]] = {k: {} for k in merged}

        for result in results:
            for section, items in result.items():
                if section not in merged or not isinstance(items, list):
                    continue
                for item in items:
                    domain = item.get("domain", "")
                    if domain and domain in seen_domains[section]:
                        continue
                    merged[section].append(item)
                    if domain:
                        seen_domains[section][domain] = set()

        log.debug(
            "Merged results: replied=%d, no_reply=%d, we_didnt_reply=%d, projects=%d, saas=%d",
            len(merged["replied_to_us"]),
            len(merged["no_reply"]),
            len(merged["we_didnt_reply"]),
            len(merged["active_projects"]),
            len(merged["saas_discussions"]),
        )
        return merged
