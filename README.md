# Dot - Email Triage System

Dot is an AI-powered email triage tool for Hunch. Forward emails to dot@hunch.co.nz and receive structured briefs with auto-assigned job numbers.

## How It Works

```
Email → Power Automate → Railway (Claude) → Airtable → Email back
```

1. Email arrives at dot@hunch.co.nz
2. Power Automate triggers, sends content to Railway
3. Railway calls Claude with DOT prompt
4. Claude analyzes and returns structured JSON
5. Railway looks up client in Airtable, assigns next job number
6. Power Automate sends formatted triage email back

## Tech Stack

- **Power Automate**: Email trigger and response
- **Railway**: Hosts Flask app (app.py)
- **Claude API**: Sonnet for analysis
- **Airtable**: Job number sequences per client

## Environment Variables (Railway)

- `ANTHROPIC_API_KEY` - Claude API key
- `AIRTABLE_API_KEY` - Airtable personal access token
- `GOOGLE_SCRIPT_URL` - (legacy, not currently used)

## Airtable Setup

Base: Hunch Hub (`app8CI7NAZqhQ4G1Y`)
Table: Job Numbers

| Client code | Clients | Next # | Next Job # |
|-------------|---------|--------|------------|
| ONE | One NZ | 85 | ONE 085 |
| SKY | Sky | 15 | SKY 015 |
| TOW | Tower | 22 | TOW 022 |

## Files

- `app.py` - Flask app, handles requests, calls Claude and Airtable
- `dot_prompt.txt` - System prompt for Claude
- `requirements.txt` - Python dependencies

---

## Done

- [x] Basic email → Claude → email flow
- [x] Railway hosting with auto-deploy from GitHub
- [x] Claude integration (Sonnet)
- [x] Structured JSON output (client, job name, project owner, triage)
- [x] Airtable job number lookup and auto-increment
- [x] Power Automate formatting with job number in subject

## TODO

### High Priority
- [ ] **New vs Update detection** - Check for "RE:" + existing job number, don't increment if update (~30-45 mins)
- [ ] **CC-to-client flow** - If Michael CCs Dot, send triage to the client in TO field (~45-60 mins)

### Medium Priority
- [ ] **Word attachment extraction** - Extract .docx content for Claude to analyze (~60-90 mins)
- [ ] **Attachment pass-through** - Forward attachments on outgoing email, handle null case (~15 mins)
- [ ] **Update flow (Dot 2.0)** - Separate flow for updates, append to job history in Airtable (~2-3 hours)

### Low Priority
- [ ] **HTML formatting** - Prettier triage emails (~15 mins)
- [ ] **Teams integration** - Post to channel as well as email (~20 mins)
- [ ] **Prompt refinement** - Ongoing tweaks to dot_prompt.txt

---

## Maintenance / What Could Break

| Component | Risk | Signs of failure |
|-----------|------|------------------|
| Claude model string | Model deprecated | 404 errors in Railway logs |
| Airtable token | Expires/revoked | "No Airtable API key" or 401 errors |
| Power Automate auth | Token expires | Flow fails, asks to re-auth |
| Anthropic billing | Card expired | 401/402 errors |
| Client code missing | Data gap | Job number shows "TBC" |

**Current model**: `claude-sonnet-4-20250514`
**Last verified working**: December 2025

---

## Development

Edit files in GitHub → Railway auto-deploys in ~1 min.

To test: Forward an email to dot@hunch.co.nz, check Railway logs.

Health check: `https://dotdownloadorganisetriage-production.up.railway.app/health`
