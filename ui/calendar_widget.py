"""
CalendarView - Custom Canvas-based calendar widget for tkinter/ttkbootstrap.

A professional curriculum planner calendar supporting month, week, and year views
with activity type color coding, event management, and interactive date selection.
"""

import tkinter as tk
from datetime import datetime, timedelta
from tkinter import ttk

import ttkbootstrap as ttk
from ttkbootstrap.constants import *

from ui.theme import fg, is_dark, muted_fg, subtle_fg, fs


class CalendarView(ttk.Frame):
    """Canvas-based calendar widget with month, week, and year views."""

    # Activity type background colors (light mode, dark mode)
    ACTIVITY_COLORS = {
        "skill_building": ("#E3F2FD", "#1A3A5C"),
        "concert_prep": ("#FFF3E0", "#4A3520"),
        "concert": ("#FFEBEE", "#5C1A1A"),
        "assessment": ("#F3E5F5", "#3D1A4A"),
        "sight_reading": ("#E8F5E9", "#1A3D1A"),
        "theory": ("#E0F7FA", "#1A3D3D"),
        "composition": ("#FFF8E1", "#4A4520"),
        "listening": ("#F1F8E9", "#2A3D1A"),
        "flex": ("#FFFDE7", "#4A4A20"),
        "no_class": ("#F5F5F5", "#2A2A2A"),
    }

    def __init__(self, parent, **kwargs):
        """Initialize CalendarView.

        Args:
            parent: Parent tkinter widget
            **kwargs: Additional ttk.Frame kwargs
        """
        super().__init__(parent, **kwargs)

        # Instance variables
        self._mode = "month"  # "month", "week", or "year"
        self._current_date = datetime.now()
        self._items = {}  # {"YYYY-MM-DD": [{"summary": str, "activity_type": str, "is_locked": bool}]}
        self._selected_date = None
        self._on_date_click = None
        self._on_date_double_click = None

        # Canvas for rendering
        self._canvas = tk.Canvas(
            self,
            bg=self._get_bg_color(),
            highlightthickness=0,
            cursor="arrow",
        )
        self._canvas.pack(fill=BOTH, expand=True)

        # Hit test regions: [(x1, y1, x2, y2, date_str), ...]
        self._click_regions = []

        # Bind events
        self._canvas.bind("<Button-1>", self._on_canvas_click)
        self._canvas.bind("<Double-1>", self._on_canvas_double_click)
        self._canvas.bind("<Configure>", self._on_canvas_resize)

        # Debounce resize events
        self._resize_after_id = None

    def _get_bg_color(self):
        """Get background color based on theme."""
        return "#1E1E1E" if is_dark() else "#FFFFFF"

    def _get_cell_bg_color(self, activity_type):
        """Get cell background color for activity type."""
        colors = self.ACTIVITY_COLORS.get(activity_type, self.ACTIVITY_COLORS["no_class"])
        return colors[1] if is_dark() else colors[0]

    def set_mode(self, mode):
        """Switch between 'month', 'week', or 'year' view.

        Args:
            mode: One of "month", "week", "year"
        """
        if mode not in ("month", "week", "year"):
            raise ValueError(f"Invalid mode: {mode}")
        self._mode = mode
        self.refresh()

    def set_date(self, date):
        """Navigate to a specific date.

        Args:
            date: datetime object or "YYYY-MM-DD" string
        """
        if isinstance(date, str):
            self._current_date = datetime.strptime(date, "%Y-%m-%d")
        else:
            self._current_date = date
        self.refresh()

    def next_period(self):
        """Navigate forward by one month/week/year depending on mode."""
        if self._mode == "month":
            month = self._current_date.month + 1
            year = self._current_date.year
            if month > 12:
                month = 1
                year += 1
            self._current_date = self._current_date.replace(year=year, month=month)
        elif self._mode == "week":
            self._current_date += timedelta(weeks=1)
        elif self._mode == "year":
            self._current_date = self._current_date.replace(
                year=self._current_date.year + 1
            )
        self.refresh()

    def prev_period(self):
        """Navigate backward by one month/week/year depending on mode."""
        if self._mode == "month":
            month = self._current_date.month - 1
            year = self._current_date.year
            if month < 1:
                month = 12
                year -= 1
            self._current_date = self._current_date.replace(year=year, month=month)
        elif self._mode == "week":
            self._current_date -= timedelta(weeks=1)
        elif self._mode == "year":
            self._current_date = self._current_date.replace(
                year=self._current_date.year - 1
            )
        self.refresh()

    def set_items(self, items_dict):
        """Set curriculum items.

        Args:
            items_dict: {
                "YYYY-MM-DD": [
                    {"summary": str, "activity_type": str, "is_locked": bool},
                    ...
                ],
                ...
            }
        """
        self._items = items_dict or {}
        self.refresh()

    def set_on_date_click(self, callback):
        """Register single-click callback.

        Args:
            callback: Callable(date_str) or None
        """
        self._on_date_click = callback

    def set_on_date_double_click(self, callback):
        """Register double-click callback.

        Args:
            callback: Callable(date_str) or None
        """
        self._on_date_double_click = callback

    def get_selected_date(self):
        """Return currently selected date string or None."""
        return self._selected_date

    def get_title(self):
        """Return display title for current view.

        Returns:
            String like "September 2025", "Week of Sep 1, 2025", or "2025-2026"
        """
        if self._mode == "month":
            return self._current_date.strftime("%B %Y")
        elif self._mode == "week":
            week_start = self._current_date - timedelta(days=self._current_date.weekday())
            week_end = week_start + timedelta(days=4)  # Mon-Fri
            return f"Week of {week_start.strftime('%b %d')}, {self._current_date.year}"
        elif self._mode == "year":
            year_start = self._current_date.year
            return f"{year_start}-{year_start + 1}"

    def refresh(self):
        """Redraw the calendar."""
        self._canvas.delete("all")
        self._click_regions = []

        width = self._canvas.winfo_width()
        height = self._canvas.winfo_height()

        if width <= 1 or height <= 1:
            return

        if self._mode == "month":
            self._draw_month_view(width, height)
        elif self._mode == "week":
            self._draw_week_view(width, height)
        elif self._mode == "year":
            self._draw_year_view(width, height)

    # ==================== Month View ====================

    def _get_month_days(self, year, month):
        """Get list of (date, is_current_month) for a 6-week grid starting Monday.

        Returns:
            List of (datetime, bool) tuples
        """
        first_day = datetime(year, month, 1)
        # Start on Monday of the week containing the 1st
        start = first_day - timedelta(days=first_day.weekday())

        result = []
        for i in range(42):  # 6 weeks * 7 days
            day = start + timedelta(days=i)
            is_current = day.month == month
            result.append((day, is_current))

        return result

    def _truncate(self, text, max_chars):
        """Truncate text to max_chars with ellipsis."""
        if not text:
            return ""
        if len(text) <= max_chars:
            return text
        return text[:max_chars - 1].rstrip() + "…"

    def _draw_month_view(self, width, height):
        """Render month view — compact weekends, no title (nav bar shows it)."""
        full_height = height  # preserve for legend positioning
        padding = 4
        header_height = 20
        gap = 1
        legend_reserve = 20
        height = height - legend_reserve  # reduce drawing area for cells

        # Weekend columns are narrow (just enough for day number + event dot)
        weekend_w = max(30, (width - 2 * padding) // 14)  # ~half a weekday
        weekday_w = (width - 2 * padding - 2 * weekend_w - 6 * gap) // 5

        # Column widths: Mon-Fri full, Sat-Sun compact
        col_widths = [weekday_w] * 5 + [weekend_w] * 2
        cell_height = (height - padding - header_height - 5 * gap) // 6

        line_h = max(13, fs(8) + 4)
        day_num_h = max(16, fs(8) + 6)  # enough room for day number + gap

        # Draw day headers
        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sa", "Su"]
        x_cursor = padding
        col_positions = []  # (x_start, width) for each column
        for i, name in enumerate(day_names):
            w = col_widths[i]
            col_positions.append((x_cursor, w))
            self._canvas.create_text(
                x_cursor + w // 2, header_height // 2,
                text=name,
                font=("Segoe UI", fs(8), "bold"),
                fill=muted_fg(), anchor="center",
            )
            x_cursor += w + gap

        # Get days for this month
        days_list = self._get_month_days(
            self._current_date.year, self._current_date.month
        )
        today = datetime.now().date()
        item_font = ("Segoe UI", fs(8))
        item_font_bold = ("Segoe UI", fs(8), "bold")
        day_font = ("Segoe UI", fs(8), "bold")

        for idx, (day, is_current_month) in enumerate(days_list):
            row = idx // 7
            col = idx % 7
            col_x, col_w = col_positions[col]
            x1 = col_x
            y1 = header_height + row * (cell_height + gap)
            x2 = x1 + col_w
            y2 = y1 + cell_height
            is_weekend = col >= 5

            day_str = day.strftime("%Y-%m-%d")
            items = self._items.get(day_str, [])

            # ── Cell background ──
            if not is_current_month:
                bg = "#2A2A2A" if is_dark() else "#ECECEC"
            elif is_weekend and not items:
                bg = "#2E2E2E" if is_dark() else "#E8E8E8"
            elif not items:
                bg = self._get_bg_color()
            elif len(items) == 1:
                bg = self._get_cell_bg_color(
                    items[0].get("activity_type", "no_class"))
            else:
                non_concert = [
                    it for it in items if it.get("activity_type") != "concert"]
                if non_concert:
                    bg = self._get_cell_bg_color(
                        non_concert[0].get("activity_type", "skill_building"))
                else:
                    bg = self._get_cell_bg_color("concert")

            self._canvas.create_rectangle(
                x1, y1, x2, y2, fill=bg, outline=subtle_fg(), width=1)

            # ── Today highlight ──
            if day.date() == today:
                self._canvas.create_rectangle(
                    x1, y1, x2, y2, fill="", outline="#4A90E2", width=3)

            # ── Selected highlight ──
            if day_str == self._selected_date:
                self._canvas.create_rectangle(
                    x1 + 1, y1 + 1, x2 - 1, y2 - 1,
                    fill="", outline="#E67E22", width=2)

            text_color = fg() if is_current_month else subtle_fg()

            if is_weekend:
                # ── Weekend: compact — just day number centered + event dot ──
                self._canvas.create_text(
                    x1 + col_w // 2, y1 + 4,
                    text=str(day.day), font=("Segoe UI", fs(7)),
                    fill=text_color, anchor="n")
                # Event indicator
                has_event = bool(items)
                has_concert = any(
                    it.get("activity_type") == "concert" for it in items)
                if has_concert:
                    self._canvas.create_text(
                        x1 + col_w // 2, y1 + 18,
                        text="★", font=("Segoe UI", fs(10)),
                        fill="#E74C3C", anchor="n")
                elif has_event:
                    self._canvas.create_oval(
                        x1 + col_w // 2 - 3, y1 + 20,
                        x1 + col_w // 2 + 3, y1 + 26,
                        fill="#4A90D9", outline="")
            else:
                # ── Weekday: full content ──
                self._canvas.create_text(
                    x1 + 3, y1 + 1,
                    text=str(day.day), font=day_font,
                    fill=text_color, anchor="nw")

                # Concert star (top-right)
                has_concert = any(
                    it.get("activity_type") == "concert" for it in items)
                if has_concert:
                    self._canvas.create_text(
                        x2 - 3, y1 + 1, text="★",
                        font=("Segoe UI", fs(10)),
                        fill="#E74C3C", anchor="ne")

            # ── Item text lines (weekdays only — weekends handled above) ──
            if items and is_current_month and not is_weekend:
                text_x = x1 + 3
                text_w = col_w - 8  # available width for wrapped text
                y_cursor = y1 + day_num_h
                space_left = y2 - y_cursor - 4
                items_shown = 0

                for item in items:
                    if space_left < line_h:
                        break

                    summary = item.get("summary", "")
                    atype = item.get("activity_type", "")

                    # For concerts, show with emphasis
                    if atype == "concert":
                        display = "★ " + summary
                        font_to_use = item_font_bold
                        color = "#E74C3C" if not is_dark() else "#FF6B6B"
                    else:
                        display = summary
                        font_to_use = item_font
                        color = text_color

                    # Use canvas text wrapping — let tkinter handle line breaks
                    # But limit how much vertical space this one item can use
                    max_h_for_item = min(space_left, line_h * 2)  # max 2 lines per item

                    tid = self._canvas.create_text(
                        text_x, y_cursor,
                        text=display, font=font_to_use,
                        fill=color, anchor="nw",
                        width=text_w,
                    )

                    # Measure how tall the rendered text actually is
                    bbox = self._canvas.bbox(tid)
                    if bbox:
                        rendered_h = bbox[3] - bbox[1]
                        if rendered_h > max_h_for_item:
                            # Text is too tall — truncate and redraw
                            self._canvas.delete(tid)
                            # Estimate chars that fit in 2 lines
                            chars_per_line = max(10, text_w // 6)
                            truncated = display[:chars_per_line * 2 - 1].rstrip() + "…"
                            tid = self._canvas.create_text(
                                text_x, y_cursor,
                                text=truncated, font=font_to_use,
                                fill=color, anchor="nw",
                                width=text_w,
                            )
                            bbox = self._canvas.bbox(tid)
                            rendered_h = bbox[3] - bbox[1] if bbox else line_h

                        y_cursor += rendered_h + 2
                        space_left -= rendered_h + 2
                    else:
                        y_cursor += line_h
                        space_left -= line_h

                    items_shown += 1

                # Show "+N more" if items were skipped
                remaining = len(items) - items_shown
                if remaining > 0 and space_left >= line_h:
                    self._canvas.create_text(
                        text_x, y_cursor,
                        text=f"+{remaining} more",
                        font=("Segoe UI", fs(7), "italic"),
                        fill=muted_fg(), anchor="nw",
                    )

            # ── Record click region ──
            self._click_regions.append((x1, y1, x2, y2, day_str))

        # ── Legend at bottom ──
        self._draw_legend(width, full_height)

    # ==================== Week View ====================

    def _get_week_days(self, date):
        """Get list of dates for the week (Mon-Fri) containing date.

        Returns:
            List of datetime objects
        """
        start = date - timedelta(days=date.weekday())
        return [start + timedelta(days=i) for i in range(5)]

    def _draw_week_view(self, width, height):
        """Render week view on canvas — tall columns with full item detail."""
        full_height = height
        padding = 10
        title_height = 28
        day_header_h = 28
        gap = 3
        legend_reserve = 20
        day_width = (width - 2 * padding - 4 * gap) // 5
        col_top = title_height + day_header_h
        col_bottom = height - padding - legend_reserve
        line_h = max(16, fs(9) + 5)
        char_width = max(1, (day_width - 16) // 7)

        # Draw title
        self._canvas.create_text(
            width // 2, title_height // 2 + 2,
            text=self.get_title(),
            font=("Segoe UI", fs(13), "bold"),
            fill=fg(), anchor="center",
        )

        days_list = self._get_week_days(self._current_date)
        today = datetime.now().date()

        for col, day in enumerate(days_list):
            x1 = padding + col * (day_width + gap)
            x2 = x1 + day_width
            day_str = day.strftime("%Y-%m-%d")
            items = self._items.get(day_str, [])

            # Background
            if items:
                non_concert = [it for it in items if it.get("activity_type") != "concert"]
                if non_concert:
                    bg = self._get_cell_bg_color(non_concert[0].get("activity_type", "skill_building"))
                else:
                    bg = self._get_cell_bg_color("concert")
            else:
                bg = self._get_bg_color()

            self._canvas.create_rectangle(
                x1, col_top, x2, col_bottom,
                fill=bg, outline=subtle_fg(), width=1,
            )

            # Day header
            is_today = day.date() == today
            hdr = day.strftime("%A %b %d")
            if is_today:
                hdr += " (Today)"
                # Header highlight
                self._canvas.create_rectangle(
                    x1, title_height, x2, col_top,
                    fill="#4A90E2", outline="#4A90E2",
                )
                hdr_color = "#FFFFFF"
            else:
                self._canvas.create_rectangle(
                    x1, title_height, x2, col_top,
                    fill="#E8E8E8" if not is_dark() else "#333333",
                    outline=subtle_fg(),
                )
                hdr_color = fg()

            self._canvas.create_text(
                x1 + day_width // 2, title_height + day_header_h // 2,
                text=hdr, font=("Segoe UI", fs(9), "bold"),
                fill=hdr_color, anchor="center",
            )

            # Selected border
            if day_str == self._selected_date:
                self._canvas.create_rectangle(
                    x1, col_top, x2, col_bottom,
                    fill="", outline="#E67E22", width=2,
                )

            # Items — use Canvas text wrapping for full-width display
            text_x = x1 + 8
            text_w = day_width - 16  # available width for wrapped text
            y_cursor = col_top + 8
            space_left = col_bottom - y_cursor - 8

            for item in items:
                if space_left < 20:
                    break
                summary = item.get("summary", "")
                atype = item.get("activity_type", "")

                if atype == "concert":
                    display = "★ " + summary
                    font_use = ("Segoe UI", fs(10), "bold")
                    color = "#E74C3C" if not is_dark() else "#FF6B6B"
                else:
                    display = summary
                    font_use = ("Segoe UI", fs(10))
                    color = fg()

                # Draw with text wrapping at the column width
                tid = self._canvas.create_text(
                    text_x, y_cursor,
                    text=display, font=font_use,
                    fill=color, anchor="nw",
                    width=text_w,
                )

                # Measure rendered height
                bbox = self._canvas.bbox(tid)
                if bbox:
                    rendered_h = bbox[3] - bbox[1]
                    y_cursor += rendered_h + 6
                    space_left -= rendered_h + 6
                else:
                    y_cursor += 20
                    space_left -= 20

            self._click_regions.append((x1, col_top, x2, col_bottom, day_str))

        # ── Legend at bottom ──
        self._draw_legend(width, full_height)

    # ==================== Year View ====================

    def _get_school_year_months(self, year):
        """Get list of (year, month) for school year (Sep through Jun).

        Args:
            year: Starting year (September of this year)

        Returns:
            List of (year, month) tuples
        """
        return [
            (year, 9), (year, 10), (year, 11), (year, 12),
            (year + 1, 1), (year + 1, 2), (year + 1, 3),
            (year + 1, 4), (year + 1, 5), (year + 1, 6),
        ]

    def _draw_year_view(self, width, height):
        """Render year view — 10 mini-calendars (Sep-Jun) with color legend."""
        padding = 10
        label_h = 20  # height for month label above each mini-cal
        legend_h = 24  # height for color legend at bottom
        gap_x = 8
        gap_y = 6

        # 5 columns, 2 rows of months
        month_width = (width - 2 * padding - 4 * gap_x) // 5
        month_height = (height - 2 * padding - legend_h - gap_y) // 2

        # Get school year months
        school_year = self._current_date.year
        if self._current_date.month < 9:
            school_year -= 1
        months = self._get_school_year_months(school_year)

        for idx, (year, month) in enumerate(months):
            row = idx // 5
            col = idx % 5
            x = padding + col * (month_width + gap_x)
            y = padding + row * (month_height + gap_y)

            # Month label — centered above the grid
            month_name = datetime(year, month, 1).strftime("%b %Y")
            self._canvas.create_text(
                x + month_width // 2, y + label_h // 2,
                text=month_name,
                font=("Segoe UI", fs(9), "bold"),
                fill=fg(), anchor="center",
            )

            # Mini calendar grid
            days_list = self._get_month_days(year, month)
            grid_x = x + 2
            grid_y = y + label_h
            cell_w = (month_width - 4) // 7
            cell_h = (month_height - label_h - 4) // 6

            for day_idx, (day, is_current_month) in enumerate(days_list):
                gr = day_idx // 7
                gc = day_idx % 7
                cx = grid_x + gc * cell_w
                cy = grid_y + gr * cell_h

                day_str = day.strftime("%Y-%m-%d")
                items = self._items.get(day_str, [])

                if is_current_month and items:
                    atype = items[0].get("activity_type", "no_class")
                    bg = self._get_cell_bg_color(atype)
                elif is_current_month:
                    bg = self._get_bg_color()
                else:
                    bg = "#2E2E2E" if is_dark() else "#ECECEC"

                self._canvas.create_rectangle(
                    cx, cy, cx + cell_w - 1, cy + cell_h - 1,
                    fill=bg, outline="",
                )

                # Concert star
                has_concert = any(
                    it.get("activity_type") == "concert" for it in items)
                if has_concert:
                    self._canvas.create_text(
                        cx + cell_w // 2, cy + cell_h // 2,
                        text="★", font=("Segoe UI", fs(7)),
                        fill="#E74C3C", anchor="center",
                    )

            # Click region for the month
            self._click_regions.append(
                (x, y, x + month_width, y + month_height,
                 f"{year}-{month:02d}-01")
            )

        self._draw_legend(width, height)

    # ==================== Shared Legend ====================

    def _draw_legend(self, width, height):
        """Draw a compact color legend at the bottom of the canvas."""
        items = [
            ("Skill", "skill_building"),
            ("Prep", "concert_prep"),
            ("Concert", "concert"),
            ("Test", "assessment"),
            ("S-Read", "sight_reading"),
            ("Theory", "theory"),
            ("Flex", "flex"),
        ]
        legend_font = ("Segoe UI", fs(7))
        swatch_size = 10
        item_spacing = 4

        # Measure total width needed
        # Each item = swatch + 2px gap + text + spacing
        # Estimate text at ~5px per char
        total_w = sum(swatch_size + 3 + len(label) * 6 + item_spacing for label, _ in items)
        legend_y = height - 18
        start_x = max(4, (width - total_w) // 2)

        x_cursor = start_x
        for label, atype in items:
            color = self._get_cell_bg_color(atype)
            self._canvas.create_rectangle(
                x_cursor, legend_y + 2,
                x_cursor + swatch_size, legend_y + 2 + swatch_size,
                fill=color, outline=muted_fg(),
            )
            self._canvas.create_text(
                x_cursor + swatch_size + 3, legend_y + 2 + swatch_size // 2,
                text=label, font=legend_font,
                fill=muted_fg(), anchor="w",
            )
            # Measure actual text width for next position
            tid = self._canvas.create_text(0, 0, text=label, font=legend_font)
            bbox = self._canvas.bbox(tid)
            text_w = (bbox[2] - bbox[0]) if bbox else len(label) * 6
            self._canvas.delete(tid)
            x_cursor += swatch_size + 3 + text_w + item_spacing + 6

    # ==================== Event Handling ====================

    def _hit_test(self, x, y):
        """Find which date cell was clicked.

        Args:
            x, y: Canvas coordinates

        Returns:
            Date string "YYYY-MM-DD" or None
        """
        for x1, y1, x2, y2, date_str in self._click_regions:
            if x1 <= x <= x2 and y1 <= y <= y2:
                return date_str
        return None

    def _on_canvas_click(self, event):
        """Handle single click on canvas."""
        date_str = self._hit_test(event.x, event.y)
        if date_str:
            self._selected_date = date_str
            if self._on_date_click:
                self._on_date_click(date_str)
            # Auto-switch to month view if in year view
            if self._mode == "year":
                self.set_date(date_str)
                self.set_mode("month")
            else:
                # Delay the refresh so double-click can still fire
                # (immediate refresh rebuilds click regions before the
                #  double-click event arrives, breaking hit-test)
                if self._resize_after_id:
                    self.after_cancel(self._resize_after_id)
                self._resize_after_id = self.after(300, self.refresh)

    def _on_canvas_double_click(self, event):
        """Handle double click on canvas."""
        # Cancel the pending single-click refresh
        if self._resize_after_id:
            self.after_cancel(self._resize_after_id)
            self._resize_after_id = None

        # Try hit-test first; fall back to already-selected date
        date_str = self._hit_test(event.x, event.y)
        if not date_str:
            date_str = self._selected_date

        if date_str and self._on_date_double_click:
            self._selected_date = date_str
            self._on_date_double_click(date_str)
            self.refresh()  # refresh after the handler runs

    def _on_canvas_resize(self, event):
        """Handle canvas resize with debouncing."""
        if self._resize_after_id:
            self.after_cancel(self._resize_after_id)
        self._resize_after_id = self.after(50, self.refresh)
