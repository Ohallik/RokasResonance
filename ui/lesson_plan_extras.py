"""
Advanced feature panels for the Lesson Plans module.
Includes concert countdown dashboard, reflection analytics, substitute plan generator,
and print/export dialog.
"""

import tkinter as tk
from tkinter import filedialog
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
from datetime import datetime, timedelta
from ui.theme import muted_fg, subtle_fg, fg, fs, is_dark


class ConcertCountdownDashboard(ttk.Frame):
    """Shows all upcoming concerts with countdowns and preparation tracking."""

    def __init__(self, parent, db):
        super().__init__(parent)
        self.db = db
        self.pack(fill=BOTH, expand=True, padx=10, pady=10)

        # Header
        header_frame = ttk.Frame(self)
        header_frame.pack(fill=X, pady=(0, 15))

        title_label = ttk.Label(
            header_frame,
            text="Concert Countdown",
            font=("Segoe UI", fs(16), "bold")
        )
        title_label.pack(anchor=W)

        subtitle_label = ttk.Label(
            header_frame,
            text="Track your upcoming performances and preparation status",
            foreground=subtle_fg(),
            font=("Segoe UI", fs(9))
        )
        subtitle_label.pack(anchor=W)

        # Content frame (scrollable)
        self.main_frame = ttk.Frame(self)
        self.main_frame.pack(fill=BOTH, expand=True)

        # Create canvas with scrollbar for many concerts
        canvas = tk.Canvas(self.main_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.main_frame, orient=VERTICAL, command=canvas.yview)
        self.scrollable_frame = ttk.Frame(canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)

        self.refresh()

    def refresh(self):
        """Reload concerts from database."""
        # Clear existing cards
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()

        concerts = self.db.get_concert_dates() if hasattr(self.db, 'get_concert_dates') else []

        if not concerts:
            no_concerts = ttk.Label(
                self.scrollable_frame,
                text="No upcoming concerts scheduled",
                foreground=subtle_fg(),
                font=("Segoe UI", fs(10))
            )
            no_concerts.pack(pady=20)
            return

        # Sort by date (nearest first)
        today = datetime.now().date()
        concerts_sorted = sorted(
            concerts,
            key=lambda x: datetime.strptime(x.get('concert_date', '2099-12-31'), '%Y-%m-%d').date()
        )

        for concert in concerts_sorted:
            self._create_concert_card(concert, today)

    def _create_concert_card(self, concert, today):
        """Create a card widget for a single concert."""
        concert_date = datetime.strptime(concert.get('concert_date', '2099-12-31'), '%Y-%m-%d').date()
        delta = concert_date - today

        # Determine urgency color
        if delta.days < 0:
            urgency_color = "#999999"
            countdown_text = "PAST"
        elif delta.days < 14:
            urgency_color = "#FF6B6B"
            weeks = delta.days // 7
            days = delta.days % 7
            countdown_text = f"{weeks}w, {days}d away"
        elif delta.days < 28:
            urgency_color = "#FFA94D"
            weeks = delta.days // 7
            days = delta.days % 7
            countdown_text = f"{weeks}w, {days}d away"
        elif delta.days < 56:
            urgency_color = "#FFD93D"
            weeks = delta.days // 7
            days = delta.days % 7
            countdown_text = f"{weeks}w, {days}d away"
        else:
            urgency_color = "#6BCB77"
            weeks = delta.days // 7
            days = delta.days % 7
            countdown_text = f"{weeks}w, {days}d away"

        # Card frame
        card = ttk.Frame(self.scrollable_frame, relief=RIDGE, borderwidth=1)
        card.pack(fill=X, pady=8, padx=0)

        # Left color bar
        color_bar = ttk.Frame(card, height=60)
        color_bar.pack(side=LEFT, fill=Y, padx=(0, 10))

        # Urgency indicator (use canvas for colored bar)
        color_canvas = tk.Canvas(
            color_bar,
            width=5,
            height=60,
            bg=urgency_color,
            highlightthickness=0,
            relief=FLAT
        )
        color_canvas.pack(fill=BOTH, expand=True, padx=(5, 0), pady=5)

        # Content
        content = ttk.Frame(card)
        content.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 10), pady=8)

        # Concert name and class
        name_frame = ttk.Frame(content)
        name_frame.pack(fill=X)

        ttk.Label(
            name_frame,
            text=concert.get('event_name', 'Unnamed Concert'),
            font=("Segoe UI", fs(11), "bold")
        ).pack(anchor=W)

        ttk.Label(
            name_frame,
            text=f"Class: {concert.get('class_name', 'Unknown')}",
            foreground=subtle_fg(),
            font=("Segoe UI", fs(9))
        ).pack(anchor=W)

        # Date and location
        info_frame = ttk.Frame(content)
        info_frame.pack(fill=X, pady=(5, 0))

        ttk.Label(
            info_frame,
            text=f"📅 {concert.get('concert_date', 'N/A')} | 📍 {concert.get('location', 'TBD')}",
            foreground=muted_fg(),
            font=("Segoe UI", fs(9))
        ).pack(anchor=W)

        # Countdown
        countdown_frame = ttk.Frame(card)
        countdown_frame.pack(side=RIGHT, fill=Y, padx=10, pady=8)

        ttk.Label(
            countdown_frame,
            text=countdown_text,
            font=("Segoe UI", fs(11), "bold"),
            foreground=urgency_color
        ).pack()

        if delta.days >= 0:
            ttk.Label(
                countdown_frame,
                text="days to go",
                foreground=subtle_fg(),
                font=("Segoe UI", fs(8))
            ).pack()


class ReflectionAnalytics(ttk.Frame):
    """Shows aggregate analysis of teacher's lesson plan reflections."""

    def __init__(self, parent, db):
        super().__init__(parent)
        self.db = db
        self.pack(fill=BOTH, expand=True, padx=10, pady=10)

        # Header
        header_label = ttk.Label(
            self,
            text="Reflection Analytics",
            font=("Segoe UI", fs(16), "bold")
        )
        header_label.pack(anchor=W, pady=(0, 15))

        # Filter frame
        filter_frame = ttk.Frame(self)
        filter_frame.pack(fill=X, pady=(0, 15))

        ttk.Label(filter_frame, text="Filter by Class:", font=("Segoe UI", fs(10))).pack(side=LEFT, padx=(0, 10))

        self.class_var = tk.StringVar()
        self.class_combo = ttk.Combobox(
            filter_frame,
            textvariable=self.class_var,
            state="readonly",
            width=30
        )
        self.class_combo.pack(side=LEFT, padx=(0, 10))
        self.class_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh())

        ttk.Button(filter_frame, text="Refresh", command=self.refresh).pack(side=LEFT)

        # Stats frame
        stats_frame = ttk.LabelFrame(self, text="Summary Statistics")
        stats_frame.pack(fill=X, pady=(0, 15))

        self.total_label = ttk.Label(stats_frame, text="Total Lessons: 0", font=("Segoe UI", fs(10)))
        self.total_label.pack(anchor=W, pady=5)

        self.went_well_label = ttk.Label(stats_frame, text="Went Well: 0 (0%)", font=("Segoe UI", fs(10)))
        self.went_well_label.pack(anchor=W, pady=5)

        self.needs_adjust_label = ttk.Label(stats_frame, text="Needs Adjustment: 0 (0%)", font=("Segoe UI", fs(10)))
        self.needs_adjust_label.pack(anchor=W, pady=5)

        self.didnt_work_label = ttk.Label(stats_frame, text="Didn't Work: 0 (0%)", font=("Segoe UI", fs(10)))
        self.didnt_work_label.pack(anchor=W, pady=5)

        # Reflections treeview
        tree_frame = ttk.LabelFrame(self, text="Recent Reflections")
        tree_frame.pack(fill=BOTH, expand=True)

        self.tree = ttk.Treeview(
            tree_frame,
            columns=("date", "class", "topic", "rating", "reflection"),
            show="headings",
            height=15
        )

        self.tree.column("date", width=80)
        self.tree.column("class", width=100)
        self.tree.column("topic", width=150)
        self.tree.column("rating", width=80)
        self.tree.column("reflection", width=300)

        self.tree.heading("date", text="Date")
        self.tree.heading("class", text="Class")
        self.tree.heading("topic", text="Topic")
        self.tree.heading("rating", text="Rating")
        self.tree.heading("reflection", text="Reflection Notes")

        scrollbar = ttk.Scrollbar(tree_frame, orient=VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)

        self._load_classes()
        self.refresh()

    def _load_classes(self):
        """Load class list for filter dropdown."""
        classes = self.db.get_all_classes() if hasattr(self.db, 'get_all_classes') else []
        class_names = ["All Classes"] + [c.get('class_name', f"Class {i}") for i, c in enumerate(classes)]
        self.class_combo['values'] = class_names
        self.class_combo.current(0)

    def refresh(self):
        """Reload reflections from database."""
        class_filter = self.class_var.get()
        class_id = None if class_filter == "All Classes" else class_filter

        self._load_reflections(class_id)

    def _load_reflections(self, class_id=None):
        """Query and display reflections."""
        reflections = []
        if hasattr(self.db, 'get_lesson_plans'):
            plans = self.db.get_lesson_plans(class_id) if class_id else self.db.get_lesson_plans()
            for plan in plans:
                if plan.get('reflection'):
                    reflections.append(plan)

        # Clear treeview
        for item in self.tree.get_children():
            self.tree.delete(item)

        # Calculate stats
        total = len(reflections)
        went_well = sum(1 for r in reflections if r.get('reflection_rating') == "went_well")
        needs_adjust = sum(1 for r in reflections if r.get('reflection_rating') == "needs_adjustment")
        didnt_work = sum(1 for r in reflections if r.get('reflection_rating') == "didnt_work")

        self.total_label.configure(text=f"Total Lessons: {total}")
        self.went_well_label.configure(
            text=f"Went Well: {went_well} ({int(went_well/total*100) if total > 0 else 0}%)"
        )
        self.needs_adjust_label.configure(
            text=f"Needs Adjustment: {needs_adjust} ({int(needs_adjust/total*100) if total > 0 else 0}%)"
        )
        self.didnt_work_label.configure(
            text=f"Didn't Work: {didnt_work} ({int(didnt_work/total*100) if total > 0 else 0}%)"
        )

        # Sort by date descending
        reflections_sorted = sorted(
            reflections,
            key=lambda x: x.get('concert_date', '1900-01-01'),
            reverse=True
        )

        # Populate treeview
        for reflection in reflections_sorted:
            rating = reflection.get('reflection_rating', 'unknown').replace('_', ' ').title()
            self.tree.insert("", END, values=(
                reflection.get('date', 'N/A'),
                reflection.get('class_name', 'Unknown'),
                reflection.get('topic', 'N/A'),
                rating,
                reflection.get('reflection', '')[:100]
            ))


class SubstitutePlanDialog(ttk.Toplevel):
    """Dialog for generating simplified substitute teacher lesson plans."""

    def __init__(self, parent, db, class_id, date_str, base_dir):
        super().__init__(parent)
        self.db = db
        self.class_id = class_id
        self.date_str = date_str
        self.base_dir = base_dir
        self.generated_plan = ""

        self.title("Generate Substitute Plan")
        self.geometry("700x600")

        # Header frame
        header = ttk.Frame(self)
        header.pack(fill=X, padx=15, pady=15)

        ttk.Label(
            header,
            text="Substitute Teacher Lesson Plan",
            font=("Segoe UI", fs(14), "bold")
        ).pack(anchor=W)

        class_name = self.db.get_class_name(class_id) if hasattr(self.db, 'get_class_name') else "Unknown"
        ttk.Label(
            header,
            text=f"Class: {class_name} | Date: {date_str}",
            foreground=muted_fg()
        ).pack(anchor=W, pady=(5, 0))

        # Status label
        self.status_label = ttk.Label(header, text="Ready to generate", foreground=subtle_fg())
        self.status_label.pack(anchor=W, pady=(5, 0))

        # Generate button
        button_frame = ttk.Frame(self)
        button_frame.pack(fill=X, padx=15, pady=(0, 15))

        ttk.Button(
            button_frame,
            text="Generate Plan",
            command=self._generate_plan
        ).pack(side=LEFT, padx=(0, 10))

        ttk.Button(
            button_frame,
            text="Copy to Clipboard",
            command=self._copy_to_clipboard,
            state=DISABLED
        ).pack(side=LEFT, padx=(0, 10))
        self.copy_button = button_frame.winfo_children()[-1]

        ttk.Button(
            button_frame,
            text="Save as Text",
            command=self._save_as_text,
            state=DISABLED
        ).pack(side=LEFT)
        self.save_button = button_frame.winfo_children()[-1]

        # Text display
        text_frame = ttk.LabelFrame(self, text="Generated Plan")
        text_frame.pack(fill=BOTH, expand=True, padx=15, pady=(0, 15))

        scrollbar = ttk.Scrollbar(text_frame)
        scrollbar.pack(side=RIGHT, fill=Y)

        self.text_widget = tk.Text(
            text_frame,
            wrap=WORD,
            yscrollcommand=scrollbar.set,
            state=DISABLED
        )
        self.text_widget.pack(fill=BOTH, expand=True)
        scrollbar.config(command=self.text_widget.yview)

    def _generate_plan(self):
        """Generate the substitute plan."""
        self.status_label.configure(text="Generating plan...")
        self.update()

        try:
            # Placeholder: in production, call lesson_plan_ai.generate_sub_plan()
            lesson_plan = self.db.get_lesson_plan(self.class_id, self.date_str)

            if lesson_plan:
                self.generated_plan = self._format_sub_plan(lesson_plan)
            else:
                self.generated_plan = f"No lesson plan found for {self.date_str}\n\nSubstitute Instructions:\n- Follow the curriculum guide\n- Contact admin if questions arise"

            # Display in text widget
            self.text_widget.config(state=NORMAL)
            self.text_widget.delete("1.0", END)
            self.text_widget.insert("1.0", self.generated_plan)
            self.text_widget.config(state=DISABLED)

            self.status_label.configure(text="Plan generated successfully")
            self.copy_button.config(state=NORMAL)
            self.save_button.config(state=NORMAL)

        except Exception as e:
            self.status_label.configure(text=f"Error: {str(e)}")
            Messagebox.show_error("Generation Error", str(e), parent=self)

    def _format_sub_plan(self, lesson_plan):
        """Format lesson plan for substitute teacher."""
        lines = [
            "SUBSTITUTE TEACHER LESSON PLAN",
            "=" * 50,
            "",
        ]

        if lesson_plan.get('objectives'):
            lines.append("OBJECTIVES")
            lines.append("-" * 30)
            lines.append(lesson_plan['objectives'])
            lines.append("")

        if lesson_plan.get('activities'):
            lines.append("ACTIVITIES")
            lines.append("-" * 30)
            lines.append(lesson_plan['activities'])
            lines.append("")

        if lesson_plan.get('notes'):
            lines.append("SPECIAL NOTES")
            lines.append("-" * 30)
            lines.append(lesson_plan['notes'])
            lines.append("")

        lines.extend([
            "CONTACT INFO",
            "-" * 30,
            "If questions arise during class, contact the main office.",
            "Thank you for covering this lesson!"
        ])

        return "\n".join(lines)

    def _copy_to_clipboard(self):
        """Copy generated plan to clipboard."""
        self.clipboard_clear()
        self.clipboard_append(self.generated_plan)
        Messagebox.show_info("Success", "Plan copied to clipboard", parent=self)

    def _save_as_text(self):
        """Save generated plan as text file."""
        filename = filedialog.asksaveasfilename(
            parent=self,
            defaultextension=".txt",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")],
            initialfile=f"sub_plan_{self.date_str}.txt"
        )

        if filename:
            try:
                with open(filename, 'w') as f:
                    f.write(self.generated_plan)
                Messagebox.show_info("Success", f"Plan saved to {filename}", parent=self)
            except Exception as e:
                Messagebox.show_error("Save Error", str(e), parent=self)


class PrintExportDialog(ttk.Toplevel):
    """Export and print dialog for lesson plans and curriculum."""

    def __init__(self, parent, db, class_id=None, date_str=None):
        super().__init__(parent)
        self.db = db
        self.class_id = class_id
        self.date_str = date_str

        self.title("Print & Export")
        self.geometry("800x700")

        # Header
        header = ttk.Frame(self)
        header.pack(fill=X, padx=15, pady=15)

        ttk.Label(
            header,
            text="Export Lesson Plans & Curriculum",
            font=("Segoe UI", fs(14), "bold")
        ).pack(anchor=W)

        # Options frame
        options_frame = ttk.LabelFrame(self, text="Export Options")
        options_frame.pack(fill=X, padx=15, pady=(0, 15))

        # Export type
        ttk.Label(options_frame, text="Export Type:", font=("Segoe UI", fs(10))).grid(row=0, column=0, sticky=W, pady=5)

        self.export_type_var = tk.StringVar(value="single")
        export_types = [
            ("single", "Single Lesson Plan"),
            ("week", "Week View"),
            ("curriculum", "Full Curriculum Overview"),
            ("practice", "Practice Assignment")
        ]

        self.export_type_combo = ttk.Combobox(
            options_frame,
            values=[t[1] for t in export_types],
            state="readonly",
            width=40
        )
        self.export_type_combo.grid(row=0, column=1, sticky=W, pady=5, padx=(10, 0))
        self.export_type_combo.current(0)

        # Format selector
        ttk.Label(options_frame, text="Format:", font=("Segoe UI", fs(10))).grid(row=1, column=0, sticky=W, pady=5)

        self.format_var = tk.StringVar(value="txt")
        format_combo = ttk.Combobox(
            options_frame,
            values=["Text File (.txt)", "Markdown (.md)"],
            state="readonly",
            width=40
        )
        format_combo.grid(row=1, column=1, sticky=W, pady=5, padx=(10, 0))
        format_combo.current(0)
        self.format_var.trace("w", lambda *args: self._update_format())
        self.format_combo = format_combo

        # Class info
        if self.class_id:
            class_name = self.db.get_class_name(self.class_id) if hasattr(self.db, 'get_class_name') else "Unknown"
            ttk.Label(options_frame, text=f"Class: {class_name}", foreground=muted_fg()).grid(row=2, column=0, columnspan=2, sticky=W, pady=5)

        if self.date_str:
            ttk.Label(options_frame, text=f"Date: {self.date_str}", foreground=muted_fg()).grid(row=3, column=0, columnspan=2, sticky=W, pady=5)

        # Preview area
        preview_frame = ttk.LabelFrame(self, text="Preview")
        preview_frame.pack(fill=BOTH, expand=True, padx=15, pady=(0, 15))

        scrollbar = ttk.Scrollbar(preview_frame)
        scrollbar.pack(side=RIGHT, fill=Y)

        self.preview_text = tk.Text(
            preview_frame,
            wrap=WORD,
            height=15,
            yscrollcommand=scrollbar.set,
            state=DISABLED
        )
        self.preview_text.pack(fill=BOTH, expand=True)
        scrollbar.config(command=self.preview_text.yview)

        # Button frame
        button_frame = ttk.Frame(self)
        button_frame.pack(fill=X, padx=15, pady=15)

        ttk.Button(button_frame, text="Generate Preview", command=self._generate_preview).pack(side=LEFT, padx=(0, 10))
        ttk.Button(button_frame, text="Export", command=self._do_export).pack(side=LEFT)
        ttk.Button(button_frame, text="Close", command=self.destroy).pack(side=RIGHT)

        self._generate_preview()

    def _update_format(self):
        """Update format selection."""
        selected = self.format_combo.get()
        if "Markdown" in selected:
            self.format_var.set("md")
        else:
            self.format_var.set("txt")

    def _generate_preview(self):
        """Generate and display preview."""
        export_type = self.export_type_combo.get()

        preview_text = ""

        if export_type == "Single Lesson Plan":
            if self.class_id and self.date_str:
                lesson = self.db.get_lesson_plan(self.class_id, self.date_str)
                if lesson:
                    preview_text = self._format_lesson_plan(lesson)
                else:
                    preview_text = "No lesson plan found for selected date."

        elif export_type == "Week View":
            preview_text = "Week of " + (self.date_str or "TBD") + "\n\n[Week curriculum overview would appear here]"

        elif export_type == "Full Curriculum Overview":
            if self.class_id:
                preview_text = "FULL CURRICULUM OVERVIEW\n\n[All curriculum items for this class would appear here]"
            else:
                preview_text = "Select a class to view curriculum overview."

        else:  # Practice Assignment
            preview_text = "PRACTICE ASSIGNMENT\n\n[Student-facing practice assignment would appear here]"

        self.preview_text.config(state=NORMAL)
        self.preview_text.delete("1.0", END)
        self.preview_text.insert("1.0", preview_text)
        self.preview_text.config(state=DISABLED)

    def _format_lesson_plan(self, lesson):
        """Format lesson plan for export."""
        lines = [
            "═" * 51,
            f"LESSON PLAN: {lesson.get('class_name', 'Unknown Class')}",
            f"Date: {lesson.get('date', 'N/A')}  |  Unit: {lesson.get('unit_name', 'N/A')}",
            "═" * 51,
            "",
            "OBJECTIVES",
            lesson.get('objectives', '[No objectives]'),
            "",
            "STANDARDS",
            lesson.get('standards', '[No standards]'),
            "",
            "WARM-UP",
            f"{lesson.get('warmup_minutes', 'N/A')} min",
            lesson.get('warmup', '[No warm-up activity]'),
            "",
            "ACTIVITIES",
        ]

        activities = lesson.get('activities', [])
        if isinstance(activities, list):
            for i, activity in enumerate(activities, 1):
                lines.append(f"{i}. {activity.get('type', 'Activity')} — {activity.get('title', 'Untitled')} ({activity.get('duration', '?')} min)")
                lines.append(f"   {activity.get('description', '')}")
                lines.append("")

        lines.extend([
            "ASSESSMENT",
            f"Type: {lesson.get('assessment_type', 'Formative')}",
            lesson.get('assessment', '[No assessment details]'),
            "",
            "DIFFERENTIATION",
            f"Advanced: {lesson.get('diff_advanced', '[None specified]')}",
            f"Struggling: {lesson.get('diff_struggling', '[None specified]')}",
            f"IEP/504: {lesson.get('diff_iep', '[None specified]')}",
            "",
            "NOTES",
            lesson.get('notes', '[No notes]'),
            "",
        ])

        if lesson.get('reflection'):
            lines.extend([
                "REFLECTION",
                lesson.get('reflection', '[No reflection]'),
                f"Rating: {lesson.get('reflection_rating', 'Not rated')}",
            ])

        return "\n".join(lines)

    def _do_export(self):
        """Save export to file."""
        ext = ".md" if self.format_var.get() == "md" else ".txt"

        filename = filedialog.asksaveasfilename(
            parent=self,
            defaultextension=ext,
            filetypes=[
                ("Text Files", "*.txt") if ext == ".txt" else ("Markdown Files", "*.md"),
                ("All Files", "*.*")
            ],
            initialfile=f"lesson_plan_{self.date_str or 'export'}{ext}"
        )

        if filename:
            try:
                preview_content = self.preview_text.get("1.0", END)
                with open(filename, 'w') as f:
                    f.write(preview_content)
                Messagebox.show_info("Success", f"Exported to {filename}", parent=self)
            except Exception as e:
                Messagebox.show_error("Export Error", str(e), parent=self)
