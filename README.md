# 📬 weekly-digest

> **Automated weekly email digest of your Gmail inbox** — powered by GPT-4o + Notion CRM cross-check.
> Runs every Sunday at 16:00 UTC via GitHub Actions. Zero infrastructure, zero cost to host.

---

## What it does

Every Sunday afternoon, this GitHub Action:

1. **Fetches all your Gmail threads** from the past 7 days
2. **Analyses them with GPT-4o** and classifies every external company into:
   - ✅ **Replied to us** — keep the momentum (with heat score 🔥/🌡️/❄️)
   - 📭 **No reply** — they haven't answered our outreach
   - 🚨 **They're waiting for us** — we haven't replied yet (priority!)
   - 📁 **Active projects & deals** — concrete discussions with stage tracking
   - 💻 **SaaS / platform discussions** — software-specific threads
   - ⚠️ **CRM gaps** — companies in emails but missing from your Notion
3. **Cross-checks your Notion CRM** (Companies, Contacts, Opportunities)
4. **Sends a clean HTML digest email** to your team address
5. **Archives the digest** as a Notion page for historical reference

---

## Prerequisites

- A Gmail account (personal or Google Workspace)
- A Google Cloud Platform (GCP) project (free)
- An OpenAI account with API access
- A Notion workspace with a connected integration
- A GitHub repository (public or private)

---

## Setup guide

### Step 1 — Clone & configure

```bash
git clone https://github.com/your-org/weekly-digest.git
cd weekly-digest
cp config.yaml.example config.yaml
cp .env.example .env
```

Edit `config.yaml` to match your team name, language, and Notion property names.

---

### Step 2 — Create a GCP project and Gmail OAuth credentials

This is the most involved step. Follow carefully.

**2a. Create a GCP project**

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Click **Select a project → New Project**
3. Name it `weekly-digest` → **Create**

**2b. Enable the Gmail API**

1. In your project, go to **APIs & Services → Library**
2. Search for **Gmail API** → click it → **Enable**

**2c. Configure the OAuth consent screen**

1. Go to **APIs & Services → OAuth consent screen**
2. Choose **External** → **Create**
3. Fill in:
   - App name: `Weekly Digest`
   - User support email: your email
   - Developer contact: your email
4. Click **Save and Continue** through all steps
5. On the **Test users** screen, add your Gmail address → **Save**

**2d. Create OAuth 2.0 credentials**

1. Go to **APIs & Services → Credentials → Create Credentials → OAuth client ID**
2. Application type: **Desktop app**
3. Name: `weekly-digest-cli` → **Create**
4. Download the JSON — you'll need `client_id` and `client_secret`

**2e. Get your refresh token** (one-time, run locally)

Install dependencies locally:
```bash
pip install google-auth-oauthlib google-api-python-client
```

Run this script once (it will open a browser for you to log in):

```python
# get_token.py
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
creds = flow.run_local_server(port=0)

print("CLIENT_ID:", creds.client_id)
print("CLIENT_SECRET:", creds.client_secret)
print("REFRESH_TOKEN:", creds.refresh_token)
```

Save the `credentials.json` you downloaded in step 2d, then:
```bash
python get_token.py
```

Copy the three values printed — you'll add them as GitHub Secrets.

> **Security**: The refresh token never expires unless revoked. Store it only in GitHub Secrets, never in code.

---

### Step 3 — Get your OpenAI API key

1. Go to [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
2. **Create new secret key** → copy it

---

### Step 4 — Set up Notion integration

**4a. Create a Notion integration**

1. Go to [notion.so/my-integrations](https://www.notion.so/my-integrations)
2. **New integration** → name it `Weekly Digest` → **Submit**
3. Copy the **Internal Integration Token** (starts with `secret_`)

**4b. Connect integration to your databases**

For each of your databases (Companies, Contacts, Opportunities, and optionally a Digest Archive):

1. Open the database in Notion
2. Click **···** (top right) → **Add connections** → select `Weekly Digest`
3. Copy the database ID from the URL:
   `https://notion.so/workspace/`**`xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`**`?v=...`

**4c. Set Notion property names in config.yaml**

Open `config.yaml` and update the property names under `notion:` to match your actual database column names (case-sensitive).

**4d. Create a Digest Archive database** (optional)

Create a new Notion database with these properties:
| Property | Type |
|---|---|
| Name | Title |
| Week | Text |
| Content | Text |

---

### Step 5 — Add GitHub Secrets

In your GitHub repository → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret name | Value |
|---|---|
| `GMAIL_CLIENT_ID` | From step 2d |
| `GMAIL_CLIENT_SECRET` | From step 2d |
| `GMAIL_REFRESH_TOKEN` | From step 2e |
| `GMAIL_SENDER_ADDRESS` | Your Gmail address |
| `OPENAI_API_KEY` | From step 3 |
| `NOTION_TOKEN` | From step 4a |
| `NOTION_COMPANIES_DB_ID` | From step 4b |
| `NOTION_CONTACTS_DB_ID` | From step 4b |
| `NOTION_OPPORTUNITIES_DB_ID` | From step 4b |
| `NOTION_DIGEST_ARCHIVE_DB_ID` | From step 4b (optional) |
| `DIGEST_RECIPIENT_EMAIL` | Email address to receive the digest |
| `DIGEST_TEAM_NAME` | e.g. `Acme Sales Team` |

---

### Step 6 — Test it

Trigger the workflow manually before waiting for Sunday:

1. Go to **Actions → Weekly Email Digest → Run workflow**
2. Click **Run workflow**
3. Check the logs — each step is clearly labelled
4. Check your inbox in a few minutes

---

## Project structure

```
weekly-digest/
├── .github/
│   └── workflows/
│       └── weekly_digest.yml   # GitHub Actions cron (Sunday 16:00 UTC)
├── src/
│   ├── main.py                 # Orchestrator
│   ├── gmail_client.py         # Gmail OAuth2 fetch + send
│   ├── analyzer.py             # GPT-4o classification
│   ├── notion_sync.py          # Notion CRM cross-check + archive
│   └── email_sender.py         # HTML email rendering + send
├── templates/
│   └── digest.html             # Jinja2 email template
├── config.yaml.example         # Configuration template
├── .env.example                # Local dev secrets template
├── requirements.txt
└── README.md
```

---

## Customisation

**Change the schedule**: Edit the cron expression in `.github/workflows/weekly_digest.yml`
```yaml
- cron: "0 16 * * 0"   # Sunday 16:00 UTC
```
Use [crontab.guru](https://crontab.guru) to build your own.

**Toggle sections**: In `config.yaml`, set any section to `false` to hide it from the digest.

**Exclude internal emails**: Add your company domain(s) to `gmail.exclude_domains` in `config.yaml`.

**Change the lookback window**: Set `digest.lookback_days` (default: 7).

**Adapt to your Notion schema**: Update property names under `notion:` in `config.yaml`.

---

## Cost estimate

| Service | Usage | Estimated cost |
|---|---|---|
| GitHub Actions | ~5 min/week | Free (within free tier) |
| OpenAI GPT-4o | ~50–200 threads/week | ~$0.05–0.30/week |
| Gmail API | Read + send | Free |
| Notion API | Read + write | Free |

**Total: roughly $1–2/month** depending on email volume.

---

## Privacy & security

- **No email content is stored** — only metadata and snippets are sent to OpenAI
- All credentials are stored in GitHub Secrets (encrypted at rest)
- The refresh token grants access to your Gmail — treat it like a password
- For team use, consider a dedicated `digest@yourdomain.com` Gmail account

---

## Contributing

PRs welcome. Ideas for future improvements:
- Slack / Teams notification alongside email
- Support for multiple Gmail accounts
- CSV export of CRM gaps
- Linear / HubSpot / Salesforce CRM connectors

---

## License

MIT — use freely, attribution appreciated.
