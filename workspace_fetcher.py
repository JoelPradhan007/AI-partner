"""
workspace_fetcher.py
~~~~~~~~~~~~~~~~~~~~
Fetches live snippets from Gmail, Drive, and Calendar.
Returns plain-text ready to inject into the Gemini system prompt.
"""
import logging
from datetime import datetime, timezone

from googleapiclient.discovery import build

logger = logging.getLogger(__name__)


def fetch_recent_emails(credentials, max_results: int = 10) -> str:
    try:
        svc  = build("gmail", "v1", credentials=credentials)
        resp = svc.users().messages().list(userId="me", maxResults=max_results, labelIds=["INBOX"]).execute()
        msgs = resp.get("messages", [])
        if not msgs:
            return "Gmail: No recent messages."

        lines = ["=== Recent Gmail (last 10) ==="]
        for m in msgs:
            full = svc.users().messages().get(
                userId="me", id=m["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            ).execute()
            h = {x["name"]: x["value"] for x in full["payload"].get("headers", [])}
            lines.append(
                f"• From: {h.get('From','?')} | Subject: {h.get('Subject','(none)')} | {h.get('Date','?')}\n"
                f"  Preview: {full.get('snippet','')[:120]}"
            )
        return "\n".join(lines)
    except Exception as e:
        logger.warning("Gmail error: %s", e)
        return f"Gmail: unavailable ({e})"


def fetch_recent_drive_files(credentials, max_results: int = 10) -> str:
    try:
        svc  = build("drive", "v3", credentials=credentials)
        resp = svc.files().list(
            pageSize=max_results,
            orderBy="modifiedTime desc",
            fields="files(name,mimeType,modifiedTime)",
        ).execute()
        files = resp.get("files", [])
        if not files:
            return "Google Drive: No recent files."

        lines = ["=== Recent Drive Files ==="]
        for f in files:
            lines.append(f"• {f['name']} — modified {f.get('modifiedTime','?')[:10]}")
        return "\n".join(lines)
    except Exception as e:
        logger.warning("Drive error: %s", e)
        return f"Google Drive: unavailable ({e})"


def fetch_upcoming_events(credentials, max_results: int = 10) -> str:
    try:
        svc     = build("calendar", "v3", credentials=credentials)
        now_iso = datetime.now(timezone.utc).isoformat()
        resp    = svc.events().list(
            calendarId="primary", timeMin=now_iso,
            maxResults=max_results, singleEvents=True, orderBy="startTime",
        ).execute()
        events = resp.get("items", [])
        if not events:
            return "Google Calendar: No upcoming events."

        lines = ["=== Upcoming Calendar Events ==="]
        for e in events:
            start = e["start"].get("dateTime", e["start"].get("date", "?"))
            lines.append(f"• {e.get('summary','(no title)')} — {start[:16]}")
        return "\n".join(lines)
    except Exception as e:
        logger.warning("Calendar error: %s", e)
        return f"Google Calendar: unavailable ({e})"


def build_workspace_context(credentials) -> str:
    return "\n\n".join([
        fetch_recent_emails(credentials),
        fetch_recent_drive_files(credentials),
        fetch_upcoming_events(credentials),
    ])
