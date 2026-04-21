"""
onenote_client.py - Microsoft OneNote integration via Graph API.

Provides read/write access to OneNote notebooks for importing and
exporting lesson plans. Uses MSAL for OAuth authentication with
delegated permissions (personal or work Microsoft accounts).

Features:
  - Page hierarchy creation (month pages with day sub-pages)
  - Reading content from OneNote pages
  - Sync operations (bidirectional app ↔ OneNote)

Setup:
  1. Register an app at https://portal.azure.com → App registrations
  2. Set "Redirect URI" to http://localhost (Mobile/Desktop type)
  3. Under API permissions, add: Microsoft Graph → Delegated →
     Notes.ReadWrite, Notes.Read, User.Read
  4. Copy the Application (client) ID into settings.json

Dependencies: pip install msal httpx
"""

import json
import os
import re
import time
import httpx
from datetime import datetime, date
import calendar

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
AUTHORITY = "https://login.microsoftonline.com/common"
SCOPES = ["Notes.ReadWrite", "User.Read"]

# Roka's Resonance Azure AD app registration (multi-tenant public client)
# Registered by the developer — all users authenticate with their own Microsoft account
DEFAULT_CLIENT_ID = "afc07fe0-cc42-4ba8-aa5c-9ff1c576a3ad"


class OneNoteClient:
    """Microsoft Graph API client for OneNote operations."""

    def __init__(self, client_id: str = None, token_cache_path: str = None):
        """
        Initialize the OneNote client.

        Args:
            client_id: Azure AD Application (client) ID
            token_cache_path: Path to persist the MSAL token cache
        """
        self.client_id = client_id or DEFAULT_CLIENT_ID
        if not self.client_id:
            raise ValueError(
                "No OneNote client ID configured. Please register an Azure AD app "
                "and enter the Application (client) ID in Settings → LLM tab."
            )

        self.token_cache_path = token_cache_path
        self._app = None
        self._token = None
        self._http = httpx.Client(timeout=30.0)

    def _get_msal_app(self):
        """Get or create the MSAL public client application."""
        if self._app:
            return self._app

        try:
            import msal
        except ImportError:
            raise RuntimeError(
                "The 'msal' package is required for OneNote integration.\n"
                "Install it with: pip install msal"
            )

        # Load token cache if available
        cache = msal.SerializableTokenCache()
        if self.token_cache_path and os.path.exists(self.token_cache_path):
            try:
                with open(self.token_cache_path, "r") as f:
                    cache.deserialize(f.read())
            except Exception:
                pass

        self._app = msal.PublicClientApplication(
            client_id=self.client_id,
            authority=AUTHORITY,
            token_cache=cache,
        )
        return self._app

    def _save_cache(self):
        """Persist the token cache to disk."""
        if not self.token_cache_path or not self._app:
            return
        cache = self._app.token_cache
        if cache.has_state_changed:
            try:
                os.makedirs(os.path.dirname(self.token_cache_path), exist_ok=True)
                with open(self.token_cache_path, "w") as f:
                    f.write(cache.serialize())
            except Exception:
                pass

    def authenticate(self, on_status=None) -> bool:
        """
        Authenticate with Microsoft Graph using interactive browser flow.
        Returns True if successful.

        Args:
            on_status: Optional callback(message_str) for status updates
        """
        app = self._get_msal_app()

        # Try silent token acquisition first (cached token)
        accounts = app.get_accounts()
        if accounts:
            if on_status:
                on_status("Using cached credentials...")
            result = app.acquire_token_silent(SCOPES, account=accounts[0])
            if result and "access_token" in result:
                self._token = result["access_token"]
                self._save_cache()
                return True

        # Interactive login required
        if on_status:
            on_status("Opening browser for Microsoft sign-in...")

        try:
            result = app.acquire_token_interactive(
                scopes=SCOPES,
                prompt="select_account",
            )
        except Exception as e:
            raise RuntimeError(f"Authentication failed: {e}")

        if "access_token" in result:
            self._token = result["access_token"]
            self._save_cache()
            return True
        else:
            error = result.get("error_description", result.get("error", "Unknown error"))
            raise RuntimeError(f"Authentication failed: {error}")

    def _headers(self, content_type: str = "application/json") -> dict:
        """Get HTTP headers with auth token."""
        if not self._token:
            raise RuntimeError("Not authenticated. Call authenticate() first.")
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": content_type,
        }

    def _get(self, endpoint: str, params: dict = None) -> dict:
        """Make authenticated GET request to Graph API."""
        url = f"{GRAPH_BASE}{endpoint}"
        resp = self._http.get(url, headers=self._headers(), params=params)
        if resp.status_code == 401:
            raise RuntimeError("Authentication expired. Please re-authenticate.")
        resp.raise_for_status()
        return resp.json()

    def _post(self, endpoint: str, data=None, headers=None) -> dict:
        """Make authenticated POST request to Graph API."""
        url = f"{GRAPH_BASE}{endpoint}"
        hdrs = self._headers()
        if headers:
            hdrs.update(headers)
        resp = self._http.post(url, headers=hdrs, content=data)
        if resp.status_code == 401:
            raise RuntimeError("Authentication expired. Please re-authenticate.")
        resp.raise_for_status()
        return resp.json()

    def _patch(self, endpoint: str, data=None, content_type: str = "application/json") -> dict:
        """Make authenticated PATCH request to Graph API."""
        url = f"{GRAPH_BASE}{endpoint}"
        hdrs = self._headers(content_type=content_type)
        resp = self._http.patch(url, headers=hdrs, content=data)
        if resp.status_code == 401:
            raise RuntimeError("Authentication expired. Please re-authenticate.")
        resp.raise_for_status()
        try:
            return resp.json()
        except:
            return {}

    # ─── OneNote Operations ───────────────────────────────────────────────────

    def get_user_info(self) -> dict:
        """Get the authenticated user's display name and email."""
        return self._get("/me")

    def list_notebooks(self) -> list:
        """List all OneNote notebooks for the authenticated user."""
        result = self._get("/me/onenote/notebooks")
        return result.get("value", [])

    def list_sections(self, notebook_id: str) -> list:
        """List all sections in a notebook."""
        result = self._get(f"/me/onenote/notebooks/{notebook_id}/sections")
        return result.get("value", [])

    def list_pages(self, section_id: str) -> list:
        """List all pages in a section, ordered by creation date."""
        result = self._get(
            f"/me/onenote/sections/{section_id}/pages",
            params={"$orderby": "createdDateTime"},
        )
        return result.get("value", [])

    def get_page_content(self, page_id: str) -> str:
        """Get the HTML content of a page."""
        url = f"{GRAPH_BASE}/me/onenote/pages/{page_id}/content"
        resp = self._http.get(url, headers=self._headers())
        resp.raise_for_status()
        return resp.text

    def create_page(self, section_id: str, title: str, html_body: str) -> dict:
        """
        Create a new page in a OneNote section.

        Args:
            section_id: The section to create the page in
            title: Page title
            html_body: HTML content for the page body

        Returns:
            Created page metadata dict
        """
        # OneNote API requires simple HTML posted as text/html
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>{title}</title>
</head>
<body>
{html_body}
</body>
</html>"""

        url = f"{GRAPH_BASE}/me/onenote/sections/{section_id}/pages"
        hdrs = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "text/html",
        }
        resp = self._http.post(url, headers=hdrs, content=html.encode("utf-8"))
        if resp.status_code == 401:
            raise RuntimeError("Authentication expired. Please re-authenticate.")
        resp.raise_for_status()
        return resp.json()

    def set_page_level(self, page_id: str, level: int) -> None:
        """
        Set the indentation level of a page (for sub-pages).

        Args:
            page_id: ID of the page to update
            level: 0 for parent, 1+ for sub-pages
        """
        self._patch(f"/me/onenote/pages/{page_id}", json.dumps({"level": level}).encode())

    def update_page_content(self, page_id: str, changes: list) -> None:
        """
        Update (PATCH) a page's content.

        Args:
            page_id: ID of the page to update
            changes: List of change objects per Graph API PATCH spec
                     e.g. [{"target": "body", "action": "append", "content": "<p>New</p>"}]
        """
        url = f"{GRAPH_BASE}/me/onenote/pages/{page_id}/content"
        hdrs = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
        resp = self._http.patch(url, headers=hdrs, content=json.dumps(changes).encode())
        resp.raise_for_status()

    # ─── Lesson Plan Export ───────────────────────────────────────────────────

    def format_lesson_plan_html(self, db, class_id: int, date_str: str) -> str:
        """
        Format a day's curriculum and lesson plan as OneNote-friendly HTML.

        Args:
            db: Database instance
            class_id: Teaching class ID
            date_str: Date string YYYY-MM-DD

        Returns:
            HTML string for the page body
        """
        cls = db.get_class(class_id)
        class_name = cls.get("class_name", "Unknown") if cls else "Unknown"
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        formatted_date = date_obj.strftime("%A, %B %d, %Y")

        item = db.get_curriculum_item_by_date(class_id, date_str)
        plan = None
        blocks = []
        if item:
            plan = db.get_lesson_plan_by_curriculum_item(item["id"])
            if plan:
                blocks = db.get_lesson_blocks(plan["id"])

        parts = []
        parts.append(f'<h1>{class_name} — {formatted_date}</h1>')

        if item:
            parts.append(f'<p><strong>Topic:</strong> {item.get("summary", "")}</p>')
            unit = item.get("unit_name", "")
            if unit:
                parts.append(f'<p><strong>Unit:</strong> {unit}</p>')
            atype = item.get("activity_type", "")
            if atype:
                parts.append(f'<p><strong>Activity Type:</strong> {atype}</p>')

        if plan:
            if plan.get("objectives"):
                parts.append(f'<h2>Objectives</h2>')
                parts.append(f'<p>{plan["objectives"]}</p>')

            if plan.get("standards"):
                parts.append(f'<h2>Standards</h2>')
                parts.append(f'<p>{plan["standards"]}</p>')

            if plan.get("warmup_text"):
                parts.append(f'<h2>Warm-Up</h2>')
                parts.append(f'<p>{plan["warmup_text"]}</p>')

        if blocks:
            parts.append('<h2>Activity Blocks</h2>')
            parts.append('<table border="1" style="border-collapse:collapse;width:100%">')
            parts.append(
                '<tr style="background:#4A90D9;color:white">'
                '<th style="padding:6px">Activity</th>'
                '<th style="padding:6px">Duration</th>'
                '<th style="padding:6px">Description</th>'
                '</tr>'
            )
            for block in blocks:
                title = block.get("title", "")
                dur = block.get("duration_minutes", 0)
                desc = block.get("description", "")
                parts.append(
                    f'<tr>'
                    f'<td style="padding:6px"><strong>{title}</strong></td>'
                    f'<td style="padding:6px;text-align:center">{dur} min</td>'
                    f'<td style="padding:6px">{desc}</td>'
                    f'</tr>'
                )
            parts.append('</table>')

        if plan:
            if plan.get("assessment_type") and plan["assessment_type"] != "None":
                parts.append(f'<h2>Assessment</h2>')
                parts.append(f'<p><strong>Type:</strong> {plan["assessment_type"]}</p>')
                if plan.get("assessment_details"):
                    parts.append(f'<p>{plan["assessment_details"]}</p>')

            if plan.get("differentiation_advanced") or plan.get("differentiation_struggling"):
                parts.append(f'<h2>Differentiation</h2>')
                if plan.get("differentiation_advanced"):
                    parts.append(f'<p><strong>Advanced:</strong> {plan["differentiation_advanced"]}</p>')
                if plan.get("differentiation_struggling"):
                    parts.append(f'<p><strong>Struggling:</strong> {plan["differentiation_struggling"]}</p>')
                if plan.get("differentiation_iep"):
                    parts.append(f'<p><strong>IEP/504:</strong> {plan["differentiation_iep"]}</p>')

            if plan.get("reflection_text"):
                parts.append(f'<h2>Reflection</h2>')
                parts.append(f'<p>{plan["reflection_text"]}</p>')
                if plan.get("reflection_rating"):
                    parts.append(f'<p><em>Rating: {plan["reflection_rating"]}</em></p>')

            if plan.get("notes"):
                parts.append(f'<h2>Notes</h2>')
                parts.append(f'<p>{plan["notes"]}</p>')

        if not item:
            parts.append('<p style="color:gray"><em>No curriculum item for this date.</em></p>')

        return "\n".join(parts)

    def format_curriculum_summary_html(self, db, class_id: int,
                                        start_date: str, end_date: str) -> str:
        """
        Format a date range of curriculum items as a summary HTML table.

        Returns:
            HTML string for the page body
        """
        cls = db.get_class(class_id)
        class_name = cls.get("class_name", "Unknown") if cls else "Unknown"

        items = db.get_curriculum_items(class_id, start_date, end_date)

        parts = []
        parts.append(f'<h1>{class_name} — Curriculum Overview</h1>')
        parts.append(f'<p>{start_date} to {end_date}</p>')

        if items:
            parts.append('<table border="1" style="border-collapse:collapse;width:100%">')
            parts.append(
                '<tr style="background:#4A90D9;color:white">'
                '<th style="padding:6px">Date</th>'
                '<th style="padding:6px">Topic</th>'
                '<th style="padding:6px">Type</th>'
                '<th style="padding:6px">Unit</th>'
                '</tr>'
            )
            for i, item in enumerate(items):
                bg = "" if i % 2 == 0 else ' style="background:#F0F4F8"'
                date_obj = datetime.strptime(item["item_date"], "%Y-%m-%d")
                day_name = date_obj.strftime("%a %m/%d")
                parts.append(
                    f'<tr{bg}>'
                    f'<td style="padding:4px 6px">{day_name}</td>'
                    f'<td style="padding:4px 6px">{item.get("summary", "")}</td>'
                    f'<td style="padding:4px 6px">{item.get("activity_type", "")}</td>'
                    f'<td style="padding:4px 6px">{item.get("unit_name", "")}</td>'
                    f'</tr>'
                )
            parts.append('</table>')
        else:
            parts.append('<p>No curriculum items for this date range.</p>')

        return "\n".join(parts)

    def export_month_to_section(self, db, class_id: int, section_id: str,
                                 year: int, month: int,
                                 on_status=None) -> dict:
        """
        Export a month of curriculum items as individual pages in a OneNote section.
        Creates one page per school day.

        Args:
            db: Database instance
            class_id: Teaching class ID
            section_id: OneNote section ID to create pages in
            year: Year
            month: Month (1-12)
            on_status: Optional callback(message_str) for progress

        Returns:
            {"created": int, "skipped": int, "errors": list}
        """
        result = {"created": 0, "skipped": 0, "errors": []}

        cls = db.get_class(class_id)
        class_name = cls.get("class_name", "Unknown") if cls else "Unknown"

        # Get all school days in the month
        _, num_days = calendar.monthrange(year, month)
        month_name = calendar.month_name[month]

        for day_num in range(1, num_days + 1):
            d = date(year, month, day_num)
            # Skip weekends
            if d.weekday() >= 5:
                continue

            date_str = d.strftime("%Y-%m-%d")
            item = db.get_curriculum_item_by_date(class_id, date_str)

            if not item:
                result["skipped"] += 1
                continue

            day_name = d.strftime("%A %b %d")
            title = f"{day_name} — {item.get('summary', 'No topic')[:60]}"

            if on_status:
                on_status(f"Creating page: {day_name}...")

            try:
                html = self.format_lesson_plan_html(db, class_id, date_str)
                self.create_page(section_id, title, html)
                result["created"] += 1
                # Small delay to avoid rate limiting
                time.sleep(0.5)
            except Exception as e:
                result["errors"].append(f"{day_name}: {str(e)}")

        return result

    # ─── Export Date Range with Hierarchy ─────────────────────────────────────

    def export_date_range_to_section(self, db, class_id: int, section_id: str,
                                      start_date: str, end_date: str, on_status=None) -> dict:
        """
        Export curriculum as month pages (level 0) with day sub-pages (level 1).

        Structure:
          - Page (Level 0): "March 2026 Agendas"
            - Sub-page (Level 1): "3/3 — Mon: Topic"
            - Sub-page (Level 1): "3/4 — Tue: Topic"
          - Page (Level 0): "April 2026 Agendas"
            - Sub-page (Level 1): "4/1 — Wed: Topic"

        Args:
            db: Database instance
            class_id: Teaching class ID
            section_id: OneNote section ID
            start_date: Start date string (YYYY-MM-DD)
            end_date: End date string (YYYY-MM-DD)
            on_status: Optional callback(message_str) for progress

        Returns:
            {"created": int, "errors": list}
        """
        result = {"created": 0, "errors": []}

        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError as e:
            result["errors"].append(f"Invalid date format: {e}")
            return result

        # Group curriculum items by month
        items = db.get_curriculum_items(class_id, start_date, end_date)
        if not items:
            result["errors"].append("No curriculum items found for date range")
            return result

        # Organize by (year, month)
        months = {}
        for item in items:
            item_date = datetime.strptime(item["item_date"], "%Y-%m-%d")
            key = (item_date.year, item_date.month)
            if key not in months:
                months[key] = []
            months[key].append(item)

        # Create pages for each month
        for (year, month), month_items in sorted(months.items()):
            month_name = calendar.month_name[month]
            parent_title = f"{month_name} {year} Agendas"

            if on_status:
                on_status(f"Creating month page: {parent_title}...")

            try:
                # Create parent page (month header)
                html = self.format_curriculum_summary_html(
                    db, class_id,
                    f"{year}-{month:02d}-01",
                    f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"
                )
                parent_resp = self.create_page(section_id, parent_title, html)
                parent_id = parent_resp.get("id")
                result["created"] += 1
                time.sleep(0.3)  # Rate limiting

                # Create sub-pages for each day (skip empty/no-summary items)
                for item in month_items:
                    summary = (item.get("summary") or "").strip()
                    if not summary:
                        continue  # Skip days with no content

                    item_date_str = item["item_date"]
                    item_date = datetime.strptime(item_date_str, "%Y-%m-%d")

                    # Skip weekends
                    if item_date.weekday() >= 5:
                        continue

                    day_name = item_date.strftime("%a")
                    if os.name == "nt":
                        day_short = item_date.strftime("%#m/%#d")
                    else:
                        day_short = item_date.strftime("%-m/%-d")
                    sub_title = f"{day_short} — {day_name}: {summary[:50]}"

                    if on_status:
                        on_status(f"Exporting {day_short} {day_name}...")

                    try:
                        html = self.format_lesson_plan_html(db, class_id, item_date_str)
                        sub_resp = self.create_page(section_id, sub_title, html)
                        sub_id = sub_resp.get("id")
                        result["created"] += 1

                        # Try to set sub-page level (may fail if page not yet indexed)
                        # Wait a moment then try — non-fatal if it fails
                        time.sleep(1.0)
                        try:
                            self.set_page_level(sub_id, 1)
                        except Exception:
                            pass  # Page still created, just not indented

                        time.sleep(0.3)
                    except Exception as e:
                        result["errors"].append(f"Day {item_date_str}: {str(e)}")

            except Exception as e:
                result["errors"].append(f"Month {month_name} {year}: {str(e)}")

        return result

    # ─── Import from Section ──────────────────────────────────────────────────

    def parse_date_from_title(self, title: str) -> str:
        """
        Extract a date from a OneNote page title.

        Matches patterns like:
          - "3/20", "03/20" (assumes current year)
          - "3/20/2026", "03/20/2026"
          - "March 20", "Mar 20"
          - "Mon 3/20", "Monday 3/20"

        Args:
            title: Page title to parse

        Returns:
            Date string in YYYY-MM-DD format, or None if no date found
        """
        if not title:
            return None

        current_year = datetime.now().year

        # Try M/D or MM/DD patterns
        match = re.search(r'(\d{1,2})/(\d{1,2})(?:/(\d{4}))?', title)
        if match:
            month, day, year = match.groups()
            year = int(year) if year else current_year
            try:
                dt = datetime(int(year), int(month), int(day))
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                pass

        # Try "Month Day" or "Mon Day" patterns
        month_names = {
            'january': 1, 'february': 2, 'march': 3, 'april': 4,
            'may': 5, 'june': 6, 'july': 7, 'august': 8,
            'september': 9, 'october': 10, 'november': 11, 'december': 12,
            'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
            'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
        }

        for month_str, month_num in month_names.items():
            match = re.search(rf'{month_str}\s+(\d{{1,2}})', title, re.IGNORECASE)
            if match:
                day = int(match.group(1))
                try:
                    dt = datetime(current_year, month_num, day)
                    return dt.strftime("%Y-%m-%d")
                except ValueError:
                    pass

        return None

    def html_to_text(self, html: str) -> str:
        """
        Strip HTML tags and return plain text.

        Args:
            html: HTML content

        Returns:
            Plain text without tags
        """
        # Remove script and style tags and their content
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)

        # Remove HTML tags
        html = re.sub(r'<[^>]+>', ' ', html)

        # Decode HTML entities
        html = html.replace('&nbsp;', ' ')
        html = html.replace('&lt;', '<')
        html = html.replace('&gt;', '>')
        html = html.replace('&amp;', '&')
        html = html.replace('&quot;', '"')

        # Clean up whitespace
        html = re.sub(r'\s+', ' ', html).strip()

        return html

    def find_page_by_date(self, section_id: str, date_str: str) -> dict:
        """
        Find a page in a section that matches a specific date.

        Args:
            section_id: OneNote section ID
            date_str: Date string in YYYY-MM-DD format

        Returns:
            Page dict if found, None otherwise
        """
        pages = self.list_pages(section_id)
        for page in pages:
            title = page.get("title", "")
            parsed_date = self.parse_date_from_title(title)
            if parsed_date == date_str:
                return page
        return None

    def import_from_section(self, db, class_id: int, section_id: str,
                             start_date: str, end_date: str, on_status=None) -> dict:
        """
        Read pages from a OneNote section and import as curriculum items.

        Logic:
          1. List all pages in the section
          2. Extract date from each page title
          3. Get page content (HTML)
          4. Parse HTML to extract text
          5. Use first paragraph as curriculum summary
          6. Create curriculum_items in database

        Args:
            db: Database instance
            class_id: Teaching class ID
            section_id: OneNote section ID
            start_date: Start date filter (YYYY-MM-DD)
            end_date: End date filter (YYYY-MM-DD)
            on_status: Optional callback(message_str) for progress

        Returns:
            {"imported": int, "skipped": int, "errors": list}
        """
        result = {"imported": 0, "skipped": 0, "errors": []}

        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError as e:
            result["errors"].append(f"Invalid date format: {e}")
            return result

        pages = self.list_pages(section_id)
        if not pages:
            result["skipped"] += 1
            return result

        for page in pages:
            title = page.get("title", "")
            page_id = page.get("id")

            if on_status:
                on_status(f"Importing page: {title}...")

            # Skip month header pages (level 0, no sub-pages)
            level = page.get("level", 0)
            if level == 0 and "agendas" in title.lower():
                result["skipped"] += 1
                continue

            # Try to extract date from title
            parsed_date = self.parse_date_from_title(title)
            if not parsed_date:
                result["skipped"] += 1
                continue

            # Check if date is in range
            try:
                item_dt = datetime.strptime(parsed_date, "%Y-%m-%d")
                if not (start_dt <= item_dt <= end_dt):
                    result["skipped"] += 1
                    continue
            except ValueError:
                result["skipped"] += 1
                continue

            try:
                # Get page content
                html_content = self.get_page_content(page_id)
                text_content = self.html_to_text(html_content)

                # Extract summary from first meaningful paragraph
                summary = text_content[:100].split('\n')[0].strip()
                if not summary or len(summary) < 5:
                    summary = "Imported from OneNote"

                # Check if curriculum item already exists for this date
                existing = db.get_curriculum_item_by_date(class_id, parsed_date)
                if existing:
                    # Update existing
                    update_data = dict(existing)
                    update_data["summary"] = summary
                    update_data["notes"] = text_content[:500]
                    db.update_curriculum_item(existing["id"], update_data)
                    result["imported"] += 1
                else:
                    # Create new
                    db.add_curriculum_item({
                        "class_id": class_id,
                        "item_date": parsed_date,
                        "summary": summary,
                        "activity_type": "skill_building",
                        "unit_name": "",
                        "is_locked": 0,
                        "sort_order": 0,
                        "notes": text_content[:500],
                    })
                    result["imported"] += 1

                time.sleep(0.3)  # Rate limiting

            except Exception as e:
                result["errors"].append(f"Page '{title}': {str(e)}")

        return result

    # ─── Sync Operations ─────────────────────────────────────────────────────

    def sync_with_onenote(self, db, sync_config: dict, direction: str,
                          on_status=None) -> dict:
        """
        Bidirectional sync between app and OneNote.

        Args:
            db: Database instance
            sync_config: Dict with keys: class_id, section_id, start_date, end_date
            direction: "app_to_onenote" or "onenote_to_app"
            on_status: Optional callback(message_str) for progress

        Returns:
            {"synced": int, "created": int, "updated": int, "errors": list}
        """
        class_id = sync_config.get("class_id")
        section_id = sync_config.get("section_id")
        start_date = sync_config.get("start_date")
        end_date = sync_config.get("end_date")

        result = {"synced": 0, "created": 0, "updated": 0, "errors": []}

        if not all([class_id, section_id, start_date, end_date]):
            result["errors"].append("Missing sync_config parameters")
            return result

        if direction == "app_to_onenote":
            return self._sync_app_to_onenote(db, class_id, section_id, start_date, end_date, on_status)
        elif direction == "onenote_to_app":
            return self._sync_onenote_to_app(db, class_id, section_id, start_date, end_date, on_status)
        else:
            result["errors"].append(f"Unknown sync direction: {direction}")
            return result

    def _sync_app_to_onenote(self, db, class_id: int, section_id: str,
                             start_date: str, end_date: str, on_status=None) -> dict:
        """Sync app curriculum items to OneNote (create/update pages)."""
        result = {"synced": 0, "created": 0, "updated": 0, "errors": []}

        items = db.get_curriculum_items(class_id, start_date, end_date)
        if not items:
            return result

        for item in items:
            item_date = item["item_date"]
            summary = item.get("summary", "No topic")

            if on_status:
                on_status(f"Syncing {item_date}...")

            try:
                # Look for existing page with this date
                existing_page = self.find_page_by_date(section_id, item_date)

                html = self.format_lesson_plan_html(db, class_id, item_date)
                date_obj = datetime.strptime(item_date, "%Y-%m-%d")
                day_name = date_obj.strftime("%a")
                day_short = date_obj.strftime("%-m/%-d") if os.name != "nt" else date_obj.strftime("%m/%d").lstrip("0")
                title = f"{day_short} — {day_name}: {summary[:40]}"

                if existing_page:
                    # Update existing page
                    page_id = existing_page["id"]
                    changes = [
                        {"target": "body", "action": "replace", "content": html}
                    ]
                    self.update_page_content(page_id, changes)
                    result["updated"] += 1
                else:
                    # Create new page
                    self.create_page(section_id, title, html)
                    result["created"] += 1

                result["synced"] += 1
                time.sleep(0.3)

            except Exception as e:
                result["errors"].append(f"Date {item_date}: {str(e)}")

        return result

    def _sync_onenote_to_app(self, db, class_id: int, section_id: str,
                             start_date: str, end_date: str, on_status=None) -> dict:
        """Sync OneNote pages to app curriculum items (update existing)."""
        result = {"synced": 0, "created": 0, "updated": 0, "errors": []}

        pages = self.list_pages(section_id)
        if not pages:
            return result

        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError as e:
            result["errors"].append(f"Invalid date format: {e}")
            return result

        for page in pages:
            title = page.get("title", "")
            page_id = page.get("id")

            if on_status:
                on_status(f"Syncing from OneNote: {title}...")

            parsed_date = self.parse_date_from_title(title)
            if not parsed_date:
                continue

            try:
                item_dt = datetime.strptime(parsed_date, "%Y-%m-%d")
                if not (start_dt <= item_dt <= end_dt):
                    continue
            except ValueError:
                continue

            try:
                html_content = self.get_page_content(page_id)
                text_content = self.html_to_text(html_content)
                summary = text_content[:100].split('\n')[0].strip()
                if not summary or len(summary) < 5:
                    summary = title

                # Look for existing curriculum item
                existing = db.get_curriculum_item_by_date(class_id, parsed_date)
                if existing:
                    # Update existing
                    update_data = dict(existing)
                    update_data["summary"] = summary
                    update_data["notes"] = text_content[:500]
                    db.update_curriculum_item(existing["id"], update_data)
                    result["updated"] += 1
                else:
                    # Create new
                    db.add_curriculum_item({
                        "class_id": class_id,
                        "item_date": parsed_date,
                        "summary": summary,
                        "activity_type": "skill_building",
                        "unit_name": "",
                        "is_locked": 0,
                        "sort_order": 0,
                        "notes": text_content[:500],
                    })
                    result["created"] += 1

                result["synced"] += 1
                time.sleep(0.3)

            except Exception as e:
                result["errors"].append(f"Page '{title}': {str(e)}")

        return result


# ─── Helper: Create client from app settings ──────────────────────────────────

def create_client_from_settings(base_dir: str) -> OneNoteClient:
    """
    Create a OneNoteClient using the built-in app registration.
    Token cache is stored per-profile so each teacher stays signed in.
    """
    token_cache = os.path.join(base_dir, ".onenote_cache.json")
    return OneNoteClient(client_id=DEFAULT_CLIENT_ID, token_cache_path=token_cache)
