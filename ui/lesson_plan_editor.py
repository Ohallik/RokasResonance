import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
from datetime import datetime, timedelta
from ui.theme import muted_fg, subtle_fg, fg, fs, is_dark


class LessonPlanEditor(ttk.Toplevel):
    """
    Professional split-panel Lesson Plan Editor for Roka's Resonance.
    Left panel: scrollable form sections. Right panel: activity blocks.
    Opens when a teacher double-clicks a date in the Curriculum Planner.
    """

    def __init__(self, parent, db, class_id, date_str, on_save=None):
        """
        Initialize the Lesson Plan Editor.

        Args:
            parent: Parent window
            db: Database connection
            class_id: ID of the class
            date_str: Date string (YYYY-MM-DD format)
            on_save: Callback function when lesson plan is saved
        """
        super().__init__(parent)
        self.db = db
        self._class_id = class_id
        self._date_str = date_str
        self._on_save = on_save
        self._has_unsaved = False

        # Load class and date info
        self.class_info = db.get_class(class_id)
        self.class_name = self.class_info.get("class_name", "Unknown Class") if self.class_info else "Unknown Class"
        self.date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        self.formatted_date = self.date_obj.strftime("%A, %B %d, %Y")

        # Load curriculum item and lesson plan
        self.curriculum_item = db.get_curriculum_item_by_date(class_id, date_str)
        self._item_id = self.curriculum_item.get("id") if self.curriculum_item else None

        if self._item_id:
            self.lesson_plan = db.get_lesson_plan_by_curriculum_item(self._item_id)
            self._plan_id = self.lesson_plan.get("id") if self.lesson_plan else None
            self.lesson_blocks = db.get_lesson_blocks(self._plan_id) if self._plan_id else []
        else:
            self.lesson_plan = None
            self._plan_id = None
            self.lesson_blocks = []

        # Compute concert countdown (if within 8 weeks)
        self.concert_countdown = None
        self.next_concert_name = None
        try:
            concerts = db.get_concert_dates(class_id)
            for c in concerts:
                concert_d = datetime.strptime(c["concert_date"], "%Y-%m-%d")
                days_until = (concert_d - self.date_obj).days
                if 0 < days_until <= 56:  # 8 weeks
                    self.concert_countdown = days_until
                    self.next_concert_name = c.get("event_name", "Concert")
                    break  # use the nearest upcoming concert
        except Exception:
            pass

        # Setup window — no transient() so maximize button is available
        self.title(f"Lesson Plan — {self.class_name} — {self.formatted_date}")
        self.geometry("1100x700")
        self.resizable(True, True)
        self._fit_window()

        # Build UI
        self._build_ui()
        self._populate_fields()

    def _fit_window(self):
        """Center window on parent."""
        self.update_idletasks()
        self.geometry("+%d+%d" % (
            self.master.winfo_x() + 50,
            self.master.winfo_y() + 50
        ))

    def _build_ui(self):
        """Build the main UI structure."""
        # Main container
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=BOTH, expand=True, padx=0, pady=0)

        # Header bar
        self._build_header(main_frame)

        # Content area: fixed split (no drag sash)
        self._panel_mode = "split"  # "split" | "left" | "right"
        self._content_frame = ttk.Frame(main_frame)
        self._content_frame.pack(fill=BOTH, expand=True, padx=4, pady=0)

        self._left_panel = ttk.Frame(self._content_frame)
        self._right_panel = ttk.Frame(self._content_frame)

        self._build_left_panel(self._left_panel)
        self._build_right_panel(self._right_panel)
        self._apply_panel_layout()

        # Button bar
        self._build_button_bar(main_frame)

    def _build_header(self, parent):
        """Build the top header bar with class info and navigation."""
        header = ttk.Frame(parent)
        header.pack(fill=X, padx=0, pady=0)

        # Header content
        header_content = ttk.Frame(header)
        header_content.pack(fill=X, padx=16, pady=10)

        # Left side: class and date info
        info_frame = ttk.Frame(header_content)
        info_frame.pack(side=LEFT, fill=X, expand=True)

        title_label = ttk.Label(
            info_frame,
            text=f"{self.class_name} • {self.formatted_date}",
            font=("Segoe UI", fs(13)),
            foreground=fg()
        )
        title_label.pack(anchor=W)

        # Unit and concert info
        info_text = ""
        if self.curriculum_item and self.curriculum_item.get("unit_name"):
            info_text += f"Unit: {self.curriculum_item.get('unit_name')}"

        if self.concert_countdown:
            if info_text:
                info_text += " • "
            concert_name = getattr(self, 'next_concert_name', 'Concert')
            info_text += f"Concert in {self.concert_countdown} days ({concert_name})"

        if info_text:
            ttk.Label(
                info_frame,
                text=info_text,
                font=("Segoe UI", fs(9)),
                foreground=muted_fg()
            ).pack(anchor=W)

        # Right side: navigation buttons
        nav_frame = ttk.Frame(header_content)
        nav_frame.pack(side=RIGHT)

        self._panel_toggle_btn = ttk.Button(
            nav_frame,
            text="◀▶",
            width=4,
            bootstyle=SECONDARY,
            command=self._cycle_panel_mode,
        )
        self._panel_toggle_btn.pack(side=LEFT, padx=(0, 12))

        ttk.Button(
            nav_frame,
            text="◀ Prev",
            command=self._go_previous_day,
            width=10
        ).pack(side=LEFT, padx=4)

        ttk.Button(
            nav_frame,
            text="Next ▶",
            command=self._go_next_day,
            width=10
        ).pack(side=LEFT, padx=4)

        # Separator
        ttk.Separator(header, orient=HORIZONTAL).pack(fill=X)

    def _apply_panel_layout(self):
        """Pack left/right panels according to current mode."""
        self._left_panel.pack_forget()
        self._right_panel.pack_forget()
        if self._panel_mode == "split":
            self._left_panel.pack(side=LEFT, fill=BOTH, expand=True)
            self._right_panel.pack(side=LEFT, fill=BOTH, expand=True)
            self._panel_toggle_btn.config(text="◀▶")
        elif self._panel_mode == "left":
            self._left_panel.pack(fill=BOTH, expand=True)
            self._panel_toggle_btn.config(text="▶▶")
        else:  # "right"
            self._right_panel.pack(fill=BOTH, expand=True)
            self._panel_toggle_btn.config(text="◀◀")

    def _cycle_panel_mode(self):
        """Cycle: split → left-only → right-only → split."""
        modes = ["split", "left", "right"]
        self._panel_mode = modes[(modes.index(self._panel_mode) + 1) % 3]
        self._apply_panel_layout()

    def _build_left_panel(self, parent):
        """Build the left panel with scrollable form sections."""
        # Canvas with scrollbar for scrollable content
        canvas_frame = ttk.Frame(parent)
        canvas_frame.pack(fill=BOTH, expand=True)
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)

        canvas = tk.Canvas(canvas_frame, bg="white" if not is_dark() else "#1e1e1e", highlightthickness=0)
        scrollbar = ttk.Scrollbar(canvas_frame, orient=VERTICAL, command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        self._left_canvas_win = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        # Make the scrollable frame stretch to fill canvas width
        def _on_canvas_configure(event):
            canvas.itemconfig(self._left_canvas_win, width=event.width)
        canvas.bind("<Configure>", _on_canvas_configure)

        # Bind mousewheel
        self._bind_mousewheel(canvas)

        # Build form sections
        self._build_summary_card(scrollable_frame)
        self._build_standards_card(scrollable_frame)
        self._build_warmup_card(scrollable_frame)
        self._build_assessment_card(scrollable_frame)
        self._build_differentiation_card(scrollable_frame)
        self._build_reflection_card(scrollable_frame)
        self._build_notes_card(scrollable_frame)

        self.scrollable_frame = scrollable_frame

    def _bind_mousewheel(self, canvas):
        """Bind mousewheel scrolling to canvas."""
        def on_mousewheel(event):
            if isinstance(event.widget, tk.Canvas):
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", on_mousewheel)
        canvas.bind_all("<Button-4>", on_mousewheel)
        canvas.bind_all("<Button-5>", on_mousewheel)

    def _build_summary_card(self, parent):
        """Build Summary Card — topic, type, unit, status."""
        card = ttk.LabelFrame(parent, text="Summary Card")
        card.pack(fill=X, padx=12, pady=8)

        # Topic entry (full width)
        ttk.Label(card, text="Topic", font=("Segoe UI", fs(9))).pack(anchor=W, pady=(0, 2))
        self.entry_summary = ttk.Entry(card)
        self.entry_summary.pack(fill=X, pady=(0, 12))
        self.entry_summary.bind("<KeyRelease>", lambda e: self._mark_changed())

        # Row: Activity Type | Unit Name | Status
        row = ttk.Frame(card)
        row.pack(fill=X, pady=4)

        ttk.Label(row, text="Type", font=("Segoe UI", fs(9))).pack(side=LEFT, padx=(0, 4))
        self.combo_activity = ttk.Combobox(
            row,
            values=["skill_building", "concert_prep", "concert", "assessment",
                    "sight_reading", "theory", "composition", "listening", "flex", "no_class"],
            state="readonly",
            width=12
        )
        self.combo_activity.pack(side=LEFT, padx=(0, 16))
        self.combo_activity.bind("<<ComboboxSelected>>", lambda e: self._mark_changed())

        ttk.Label(row, text="Unit", font=("Segoe UI", fs(9))).pack(side=LEFT, padx=(0, 4))
        self.entry_unit = ttk.Entry(row, width=15)
        self.entry_unit.pack(side=LEFT, fill=X, expand=True, padx=(0, 16))
        self.entry_unit.bind("<KeyRelease>", lambda e: self._mark_changed())

        ttk.Label(row, text="Status", font=("Segoe UI", fs(9))).pack(side=LEFT, padx=(0, 4))
        self.combo_status = ttk.Combobox(
            row,
            values=["draft", "in_progress", "complete", "reviewed"],
            state="readonly",
            width=12
        )
        self.combo_status.pack(side=LEFT)
        self.combo_status.bind("<<ComboboxSelected>>", lambda e: self._mark_changed())

    def _build_standards_card(self, parent):
        """Build Standards & Objectives card."""
        card = ttk.LabelFrame(parent, text="Standards & Objectives")
        card.pack(fill=X, padx=12, pady=8)

        ttk.Label(card, text="Standards", font=("Segoe UI", fs(9))).pack(anchor=W, pady=(0, 2))
        self.text_standards = tk.Text(card, height=2, width=60, font=("Segoe UI", fs(9)))
        self.text_standards.pack(fill=X, pady=(0, 10))
        self.text_standards.bind("<KeyRelease>", lambda e: self._mark_changed())

        ttk.Label(card, text="Objectives", font=("Segoe UI", fs(9))).pack(anchor=W, pady=(0, 2))
        self.text_objectives = tk.Text(card, height=2, width=60, font=("Segoe UI", fs(9)))
        self.text_objectives.pack(fill=X, pady=(0, 10))
        self.text_objectives.bind("<KeyRelease>", lambda e: self._mark_changed())

        ttk.Label(card, text="Objective Type", font=("Segoe UI", fs(9))).pack(anchor=W, pady=(0, 2))
        self.combo_obj_type = ttk.Combobox(
            card,
            values=["Introducing new concept", "Reviewing/reinforcing", "Assessing"],
            state="readonly"
        )
        self.combo_obj_type.pack(fill=X)
        self.combo_obj_type.bind("<<ComboboxSelected>>", lambda e: self._mark_changed())

    def _build_warmup_card(self, parent):
        """Build Warm-Up card."""
        card = ttk.LabelFrame(parent, text="Warm-Up")
        card.pack(fill=X, padx=12, pady=8)

        ttk.Label(card, text="Warm-Up Activity", font=("Segoe UI", fs(9))).pack(anchor=W, pady=(0, 2))
        self.text_warmup = tk.Text(card, height=2, width=60, font=("Segoe UI", fs(9)))
        self.text_warmup.pack(fill=X, pady=(0, 10))
        self.text_warmup.bind("<KeyRelease>", lambda e: self._mark_changed())

        # Template selection row
        row = ttk.Frame(card)
        row.pack(fill=X)

        ttk.Label(row, text="Template", font=("Segoe UI", fs(9))).pack(side=LEFT, padx=(0, 4))
        self.combo_template = ttk.Combobox(row, state="readonly", width=20)
        self.combo_template.pack(side=LEFT, padx=(0, 8))
        self.combo_template.bind("<<ComboboxSelected>>", self._on_template_selected)

        ttk.Button(
            row,
            text="Save as Template",
            command=self._save_warmup_template,
            width=16
        ).pack(side=LEFT)

        # Load templates
        self._load_warmup_templates()

    def _load_warmup_templates(self):
        """Load warm-up templates from database."""
        templates = self.db.get_all_templates("warmup") if hasattr(self.db, "get_all_templates") else []
        template_names = [t.get("name", "Unknown") for t in templates] if templates else []
        self.combo_template.config(values=template_names)
        self.warmup_templates = templates

    def _on_template_selected(self, event):
        """Load selected warm-up template into text field."""
        idx = self.combo_template.current()
        if idx >= 0 and idx < len(self.warmup_templates):
            template = self.warmup_templates[idx]
            self.text_warmup.delete("1.0", END)
            self.text_warmup.insert("1.0", template.get("content", ""))
            self._mark_changed()

    def _save_warmup_template(self):
        """Save current warm-up text as a new template."""
        warmup_text = self.text_warmup.get("1.0", END).strip()
        if not warmup_text:
            Messagebox.show_warning("Empty Template", "Please enter warm-up text first.")
            return

        # Prompt for template name
        dialog = TemplateNameDialog(self, "Save Warm-Up Template")
        self.wait_window(dialog)

        if dialog.result:
            if hasattr(self.db, "add_template"):
                self.db.add_template("warmup", dialog.result, warmup_text)
                Messagebox.show_info("Success", f"Template '{dialog.result}' saved.")
                self._load_warmup_templates()
            else:
                Messagebox.show_warning("Not Implemented", "Template saving not yet implemented in database.")

    def _build_assessment_card(self, parent):
        """Build Assessment card."""
        card = ttk.LabelFrame(parent, text="Assessment")
        card.pack(fill=X, padx=12, pady=8)

        ttk.Label(card, text="Assessment Type", font=("Segoe UI", fs(9))).pack(anchor=W, pady=(0, 2))
        self.combo_assessment = ttk.Combobox(
            card,
            values=["None", "Exit ticket", "Playing test", "Written quiz",
                    "Observation rubric", "Peer evaluation", "Self-assessment"],
            state="readonly"
        )
        self.combo_assessment.pack(fill=X, pady=(0, 10))
        self.combo_assessment.bind("<<ComboboxSelected>>", self._on_assessment_type_changed)

        ttk.Label(card, text="Assessment Details", font=("Segoe UI", fs(9))).pack(anchor=W, pady=(0, 2))
        self.text_assessment = tk.Text(card, height=2, width=60, font=("Segoe UI", fs(9)))
        self.text_assessment.pack(fill=X)
        self.text_assessment.bind("<KeyRelease>", lambda e: self._mark_changed())

        # Exit ticket questions (hidden by default)
        self.exit_ticket_frame = ttk.LabelFrame(card, text="Exit Ticket Questions")
        self.exit_ticket_entries = []
        for i in range(5):
            ttk.Label(self.exit_ticket_frame, text=f"Q{i+1}:", font=("Segoe UI", fs(9))).pack(anchor=W, pady=(2, 0))
            entry = ttk.Entry(self.exit_ticket_frame)
            entry.pack(fill=X, pady=(0, 6))
            entry.bind("<KeyRelease>", lambda e: self._mark_changed())
            self.exit_ticket_entries.append(entry)

    def _on_assessment_type_changed(self, event):
        """Show/hide exit ticket fields based on assessment type."""
        self._mark_changed()
        if self.combo_assessment.get() == "Exit ticket":
            self.exit_ticket_frame.pack(fill=X, pady=8, after=self.text_assessment)
        else:
            self.exit_ticket_frame.pack_forget()

    def _build_differentiation_card(self, parent):
        """Build Differentiation card."""
        card = ttk.LabelFrame(parent, text="Differentiation")
        card.pack(fill=X, padx=12, pady=8)

        ttk.Label(card, text="Advanced Students", font=("Segoe UI", fs(9))).pack(anchor=W, pady=(0, 2))
        self.text_advanced = tk.Text(card, height=1, width=60, font=("Segoe UI", fs(9)))
        self.text_advanced.pack(fill=X, pady=(0, 10))
        self.text_advanced.bind("<KeyRelease>", lambda e: self._mark_changed())

        ttk.Label(card, text="Struggling Students", font=("Segoe UI", fs(9))).pack(anchor=W, pady=(0, 2))
        self.text_struggling = tk.Text(card, height=1, width=60, font=("Segoe UI", fs(9)))
        self.text_struggling.pack(fill=X, pady=(0, 10))
        self.text_struggling.bind("<KeyRelease>", lambda e: self._mark_changed())

        ttk.Label(card, text="IEP/504 Notes", font=("Segoe UI", fs(9))).pack(anchor=W, pady=(0, 2))
        self.text_iep = tk.Text(card, height=1, width=60, font=("Segoe UI", fs(9)))
        self.text_iep.pack(fill=X)
        self.text_iep.bind("<KeyRelease>", lambda e: self._mark_changed())

    def _build_reflection_card(self, parent):
        """Build Reflection card."""
        card = ttk.LabelFrame(parent, text="Reflection")
        card.pack(fill=X, padx=12, pady=8)

        ttk.Label(card, text="Post-Lesson Reflection", font=("Segoe UI", fs(9))).pack(anchor=W, pady=(0, 2))
        self.text_reflection = tk.Text(card, height=2, width=60, font=("Segoe UI", fs(9)))
        self.text_reflection.pack(fill=X, pady=(0, 10))
        self.text_reflection.bind("<KeyRelease>", lambda e: self._mark_changed())

        # Rating buttons
        button_frame = ttk.Frame(card)
        button_frame.pack(fill=X)

        self.reflection_rating = tk.StringVar(value="")

        for value, text in [("went_well", "✅ Went well"), ("needs_adjustment", "⚠️ Needs adjustment"), ("didnt_work", "❌ Didn't work")]:
            ttk.Radiobutton(
                button_frame,
                text=text,
                variable=self.reflection_rating,
                value=value,
                command=lambda: self._mark_changed()
            ).pack(side=LEFT, padx=4)

    def _build_notes_card(self, parent):
        """Build Notes & Materials card."""
        card = ttk.LabelFrame(parent, text="Notes & Materials")
        card.pack(fill=X, padx=12, pady=8)

        ttk.Label(card, text="General Notes", font=("Segoe UI", fs(9))).pack(anchor=W, pady=(0, 2))
        self.text_notes = tk.Text(card, height=2, width=60, font=("Segoe UI", fs(9)))
        self.text_notes.pack(fill=X)
        self.text_notes.bind("<KeyRelease>", lambda e: self._mark_changed())

    def _build_right_panel(self, parent):
        """Build the right panel with activity blocks."""
        # Use a canvas+scrollbar so right panel scrolls independently
        right_outer = ttk.Frame(parent)
        right_outer.pack(fill=BOTH, expand=True)

        canvas = tk.Canvas(right_outer,
                           bg="#1e1e1e" if is_dark() else "#FAFAFA",
                           highlightthickness=0)
        scrollbar = ttk.Scrollbar(right_outer, orient=VERTICAL, command=canvas.yview)
        right_scroll = ttk.Frame(canvas)

        right_scroll.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        self._right_canvas_win = canvas.create_window(
            (0, 0), window=right_scroll, anchor="nw"
        )
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=RIGHT, fill=Y)
        canvas.pack(side=LEFT, fill=BOTH, expand=True)

        def _on_right_canvas_cfg(event):
            canvas.itemconfig(self._right_canvas_win, width=event.width)
        canvas.bind("<Configure>", _on_right_canvas_cfg)

        # Time tracker header
        header_row = ttk.Frame(right_scroll)
        header_row.pack(fill=X, padx=8, pady=(8, 4))

        ttk.Label(
            header_row,
            text="Time: ",
            font=("Segoe UI", fs(10))
        ).pack(side=LEFT)

        self._time_planned_var = tk.StringVar(value="0")
        ttk.Label(
            header_row,
            textvariable=self._time_planned_var,
            font=("Segoe UI", fs(11), "bold"),
            foreground=fg()
        ).pack(side=LEFT, padx=(0, 2))

        cls = self.db.get_class(self._class_id)
        class_duration = cls.get("class_duration", 45) if cls else 45

        ttk.Label(
            header_row,
            text=f"/{class_duration} min",
            font=("Segoe UI", fs(10)),
            foreground=muted_fg()
        ).pack(side=LEFT)

        # Activity blocks widget — packed directly, no grid
        from ui.activity_blocks import ActivityBlocksWidget

        self._activity_blocks = ActivityBlocksWidget(
            right_scroll, self.db,
            lesson_plan_id=self._plan_id,
            class_duration=class_duration,
            on_change=self._on_blocks_changed,
        )
        self._activity_blocks.pack(fill=X, padx=4, pady=4)

    def _on_blocks_changed(self):
        """Called when activity blocks are modified."""
        if hasattr(self, '_time_planned_var'):
            total = self._activity_blocks.get_total_minutes()
            self._time_planned_var.set(str(total))
        self._mark_changed()

    def _build_button_bar(self, parent):
        """Build the bottom button bar."""
        button_frame = ttk.Frame(parent)
        button_frame.pack(fill=X, padx=16, pady=12)

        # Left side: Save and Cancel
        left_buttons = ttk.Frame(button_frame)
        left_buttons.pack(side=LEFT)

        ttk.Button(
            left_buttons,
            text="Save",
            command=self._on_save,
            width=12
        ).pack(side=LEFT, padx=4)

        ttk.Button(
            left_buttons,
            text="Cancel",
            command=self._on_cancel,
            width=12
        ).pack(side=LEFT, padx=4)

        # Right side: AI Assist
        ai_frame = ttk.Frame(button_frame)
        ai_frame.pack(side=RIGHT)

        ttk.Button(
            ai_frame, text="Regenerate Plan",
            bootstyle=INFO, width=16,
            command=self._ai_regenerate,
        ).pack(side=LEFT, padx=4)

        ttk.Button(
            ai_frame, text="AI Modify...",
            bootstyle=(INFO, OUTLINE), width=14,
            command=self._ai_modify_dialog,
        ).pack(side=LEFT, padx=4)

    def _populate_fields(self):
        """Populate all fields from loaded data."""
        def _s(v):
            """Coerce a DB value to str, treating None as empty string."""
            return "" if v is None else str(v)

        if self.curriculum_item:
            self.entry_summary.insert(0, _s(self.curriculum_item.get("summary")))
            self.entry_unit.insert(0, _s(self.curriculum_item.get("unit_name")))
            self.combo_activity.set(_s(self.curriculum_item.get("activity_type")) or "skill_building")
            self.combo_status.set(_s(self.curriculum_item.get("status")) or "draft")

        if self.lesson_plan:
            self.text_standards.insert("1.0", _s(self.lesson_plan.get("standards")))
            self.text_objectives.insert("1.0", _s(self.lesson_plan.get("objectives")))
            self.combo_obj_type.set(_s(self.lesson_plan.get("objective_type")) or "Introducing new concept")

            self.text_warmup.insert("1.0", _s(self.lesson_plan.get("warmup_text")))

            self.combo_assessment.set(_s(self.lesson_plan.get("assessment_type")) or "None")
            self.text_assessment.insert("1.0", _s(self.lesson_plan.get("assessment_details")))

            # Load exit ticket questions if applicable
            if self.lesson_plan.get("assessment_type") == "Exit ticket":
                exit_tickets = self.lesson_plan.get("exit_ticket_questions", [])
                for i, question in enumerate(exit_tickets[:5]):
                    self.exit_ticket_entries[i].insert(0, _s(question))
                self.exit_ticket_frame.pack(fill=X, pady=8)

            self.text_advanced.insert("1.0", _s(self.lesson_plan.get("differentiation_advanced")))
            self.text_struggling.insert("1.0", _s(self.lesson_plan.get("differentiation_struggling")))
            self.text_iep.insert("1.0", _s(self.lesson_plan.get("differentiation_iep")))

            self.text_reflection.insert("1.0", _s(self.lesson_plan.get("reflection_text")))
            if self.lesson_plan.get("reflection_rating"):
                self.reflection_rating.set(self.lesson_plan.get("reflection_rating"))

            self.text_notes.insert("1.0", _s(self.lesson_plan.get("notes")))

        # Set initial time display
        if hasattr(self, '_activity_blocks'):
            total = self._activity_blocks.get_total_minutes()
            self._time_planned_var.set(str(total))

        self._has_unsaved = False

    def _mark_changed(self):
        """Mark that there are unsaved changes."""
        self._has_unsaved = True

    # ═══════════════════════════ AI Assist ═══════════════════════════

    def _get_base_dir(self):
        import os
        return os.path.dirname(os.path.abspath(self.db.db_path))

    def _ai_regenerate(self):
        """Regenerate the lesson plan using AI — different approach, same topic."""
        topic = self.entry_summary.get().strip()
        if not topic:
            Messagebox.show_warning(
                "Please enter a topic in the Summary Card first.",
                title="Topic Required", parent=self,
            )
            return

        confirm = Messagebox.yesno(
            f"Regenerate the lesson plan for:\n\n"
            f"  {topic}\n\n"
            f"The AI will create a completely different approach\n"
            f"to teaching this material. Your current plan will\n"
            f"be replaced (you can undo by clicking Cancel).",
            title="Regenerate Lesson Plan?", parent=self,
        )
        if confirm != "Yes":
            return

        self._run_ai("regenerate", "")

    def _ai_modify_dialog(self):
        """Open a dialog for the teacher to describe how to modify the plan."""
        topic = self.entry_summary.get().strip()
        if not topic:
            Messagebox.show_warning(
                "Please enter a topic in the Summary Card first.",
                title="Topic Required", parent=self,
            )
            return

        dlg = tk.Toplevel(self)
        dlg.title("AI Modify Lesson Plan")
        dlg.resizable(True, True)

        # Center on parent
        dlg.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - 500) // 2
        y = self.winfo_y() + (self.winfo_height() - 300) // 2
        dlg.geometry(f"500x300+{max(0,x)}+{max(0,y)}")

        ttk.Label(
            dlg, text="How should the AI modify this lesson plan?",
            font=("Segoe UI", fs(11), "bold"),
        ).pack(padx=16, pady=(16, 4))

        ttk.Label(
            dlg,
            text=f"Topic: {topic[:60]}",
            foreground=muted_fg(), font=("Segoe UI", fs(9)),
        ).pack(padx=16, pady=(0, 8))

        ttk.Label(
            dlg,
            text="Describe what you want changed — the AI will interpret\n"
                 "your instructions and modify the plan accordingly:",
            font=("Segoe UI", fs(9)),
        ).pack(padx=16, pady=(0, 4), anchor=W)

        text_input = tk.Text(dlg, height=5, font=("Segoe UI", fs(10)))
        text_input.pack(fill=BOTH, expand=True, padx=16, pady=4)
        text_input.insert("1.0",
            "e.g., 'Make it more engaging for students who are struggling' or\n"
            "'Add a sight-reading component' or 'This class has behavior issues,\n"
            "keep activities short and varied'"
        )
        text_input.tag_add("placeholder", "1.0", "end")
        text_input.tag_config("placeholder", foreground="#999999")

        def _clear_placeholder(event):
            if text_input.tag_ranges("placeholder"):
                text_input.delete("1.0", "end")
                text_input.tag_delete("placeholder")

        text_input.bind("<FocusIn>", _clear_placeholder)

        btn_frame = ttk.Frame(dlg)
        btn_frame.pack(pady=(4, 16))

        def _do_modify():
            feedback = text_input.get("1.0", "end").strip()
            if not feedback or "e.g.," in feedback:
                Messagebox.show_warning(
                    "Please describe how you want the plan modified.",
                    title="Input Required", parent=dlg,
                )
                return
            dlg.destroy()
            self._run_ai("adjust", feedback)

        ttk.Button(
            btn_frame, text="Modify Plan", bootstyle=SUCCESS,
            command=_do_modify, width=14,
        ).pack(side=LEFT, padx=4)
        ttk.Button(
            btn_frame, text="Cancel", bootstyle=SECONDARY,
            command=dlg.destroy, width=10,
        ).pack(side=LEFT, padx=4)

    def _run_ai(self, mode, feedback):
        """Run the AI generation and apply results to the form."""
        from lesson_plan_ai import generate_lesson_plan

        # Show progress
        self.title(f"Lesson Plan — {self.class_name} — Generating...")
        self.update()

        try:
            result = generate_lesson_plan(
                base_dir=self._get_base_dir(),
                db=self.db,
                class_id=self._class_id,
                date_str=self._date_str,
                mode=mode,
                teacher_feedback=feedback,
            )

            if result.get("error"):
                self.title(f"Lesson Plan — {self.class_name} — {self.formatted_date}")
                Messagebox.show_error(
                    f"AI generation failed:\n{result['error']}",
                    title="AI Error", parent=self,
                )
                return

            plan = result.get("plan")
            if not plan:
                self.title(f"Lesson Plan — {self.class_name} — {self.formatted_date}")
                Messagebox.show_warning(
                    "AI did not return a lesson plan.",
                    title="AI Result", parent=self,
                )
                return

            # Apply AI results to the form fields
            self._apply_ai_plan(plan)
            self.title(f"Lesson Plan — {self.class_name} — {self.formatted_date}")
            self._mark_changed()

        except Exception as e:
            self.title(f"Lesson Plan — {self.class_name} — {self.formatted_date}")
            Messagebox.show_error(
                f"AI generation failed:\n{str(e)}",
                title="AI Error", parent=self,
            )

    def _apply_ai_plan(self, plan):
        """Apply AI-generated plan data to the form fields."""
        # Objectives
        if plan.get("objectives"):
            self.text_objectives.delete("1.0", "end")
            self.text_objectives.insert("1.0", plan["objectives"])

        # Standards
        if plan.get("standards"):
            self.text_standards.delete("1.0", "end")
            self.text_standards.insert("1.0", plan["standards"])

        # Warm-up
        if plan.get("warmup_text"):
            self.text_warmup.delete("1.0", "end")
            self.text_warmup.insert("1.0", plan["warmup_text"])

        # Assessment
        if plan.get("assessment_type"):
            self.combo_assessment.set(plan["assessment_type"])
        if plan.get("assessment_details"):
            self.text_assessment.delete("1.0", "end")
            self.text_assessment.insert("1.0", plan["assessment_details"])

        # Differentiation
        if plan.get("differentiation_advanced"):
            self.text_advanced.delete("1.0", "end")
            self.text_advanced.insert("1.0", plan["differentiation_advanced"])
        if plan.get("differentiation_struggling"):
            self.text_struggling.delete("1.0", "end")
            self.text_struggling.insert("1.0", plan["differentiation_struggling"])

        # Notes
        if plan.get("notes"):
            self.text_notes.delete("1.0", "end")
            self.text_notes.insert("1.0", plan["notes"])

        # Activity blocks — if the AI returned blocks, replace the current ones
        blocks = plan.get("blocks", [])
        if blocks and hasattr(self, '_activity_blocks'):
            new_blocks = []
            for i, block in enumerate(blocks):
                new_blocks.append({
                    "id": id(object()),
                    "lesson_plan_id": self._plan_id,
                    "block_type": block.get("block_type", "custom"),
                    "title": block.get("title", f"Activity {i+1}"),
                    "description": block.get("description", ""),
                    "duration_minutes": block.get("duration_minutes", 10),
                    "sort_order": i,
                    "notes": block.get("notes", ""),
                    "technique_focus": block.get("technique_focus", ""),
                    "grouping": block.get("grouping", ""),
                    "difficulty_level": block.get("difficulty_level", "Medium"),
                    "measure_start": block.get("measure_start"),
                    "measure_end": block.get("measure_end"),
                    "music_piece_id": None,
                })
            self._activity_blocks.blocks = new_blocks
            self._activity_blocks._redraw_blocks()
            self._on_blocks_changed()

    def _on_save(self):
        """Save the lesson plan and close the window."""
        # Collect all field values
        data = {
            "summary": self.entry_summary.get(),
            "unit_name": self.entry_unit.get(),
            "activity_type": self.combo_activity.get() or "skill_building",
            "status": self.combo_status.get() or "draft",
            "standards": self.text_standards.get("1.0", END).strip(),
            "learning_objectives": self.text_objectives.get("1.0", END).strip(),
            "objective_type": self.combo_obj_type.get() or "Introducing new concept",
            "warmup": self.text_warmup.get("1.0", END).strip(),
            "assessment_type": self.combo_assessment.get() or "None",
            "assessment_details": self.text_assessment.get("1.0", END).strip(),
            "exit_ticket_questions": [e.get() for e in self.exit_ticket_entries],
            "advanced_students": self.text_advanced.get("1.0", END).strip(),
            "struggling_students": self.text_struggling.get("1.0", END).strip(),
            "iep_504_notes": self.text_iep.get("1.0", END).strip(),
            "reflection": self.text_reflection.get("1.0", END).strip(),
            "reflection_rating": self.reflection_rating.get(),
            "notes": self.text_notes.get("1.0", END).strip(),
        }

        try:
            # Create or update curriculum item
            ci_data = {
                "class_id": self._class_id,
                "item_date": self._date_str,
                "summary": data["summary"],
                "activity_type": data["activity_type"],
                "unit_name": data["unit_name"],
                "is_locked": 0,
                "sort_order": 0,
                "notes": "",
            }
            if not self._item_id:
                self._item_id = self.db.add_curriculum_item(ci_data)
            else:
                self.db.update_curriculum_item(self._item_id, ci_data)

            # Combine exit ticket questions into assessment details
            exit_qs = [q for q in data.get("exit_ticket_questions", []) if q.strip()]
            assessment_details = data.get("assessment_details", "")
            if exit_qs and data.get("assessment_type") == "Exit ticket":
                assessment_details = "\n".join(
                    f"{i+1}. {q}" for i, q in enumerate(exit_qs)
                )

            # Create or update lesson plan
            plan_data = {
                "curriculum_item_id": self._item_id,
                "objectives": data.get("learning_objectives", ""),
                "standards": data.get("standards", ""),
                "warmup_text": data.get("warmup", ""),
                "warmup_template_id": None,
                "assessment_type": data.get("assessment_type", ""),
                "assessment_details": assessment_details,
                "differentiation_advanced": data.get("advanced_students", ""),
                "differentiation_struggling": data.get("struggling_students", ""),
                "differentiation_iep": data.get("iep_504_notes", ""),
                "reflection_text": data.get("reflection", ""),
                "reflection_rating": data.get("reflection_rating", ""),
                "status": data.get("status", "draft"),
                "total_minutes_planned": 0,
                "notes": data.get("notes", ""),
            }
            if not self._plan_id:
                self._plan_id = self.db.add_lesson_plan(plan_data)
            else:
                self.db.update_lesson_plan(self._plan_id, plan_data)

            # Save activity blocks
            if hasattr(self, '_activity_blocks') and self._plan_id:
                self._activity_blocks.save_blocks(self._plan_id)

            self._has_unsaved = False

            if self._on_save:
                self._on_save()

            Messagebox.show_info(
                "Lesson plan saved successfully.",
                title="Saved",
                parent=self,
            )
            self.destroy()

        except Exception as e:
            Messagebox.show_error(
                f"Failed to save lesson plan:\n{str(e)}",
                title="Save Error",
                parent=self,
            )

    def _on_cancel(self):
        """Cancel and close without saving."""
        if self._has_unsaved:
            response = Messagebox.show_question(
                "Unsaved Changes",
                "You have unsaved changes. Are you sure you want to close?",
                buttons=["Yes:info", "No:warning"]
            )
            if response != "Yes":
                return

        self.destroy()

    def _go_previous_day(self):
        """Navigate to previous school day."""
        if self._has_unsaved:
            response = Messagebox.show_question(
                "Unsaved Changes",
                "Save changes before navigating?",
                buttons=["Save:info", "Don't Save:warning", "Cancel:secondary"]
            )
            if response == "Save":
                self._on_save()
                return
            elif response == "Cancel":
                return

        # Find previous school day (skip weekends)
        prev_date = self.date_obj - timedelta(days=1)
        while prev_date.weekday() >= 5:  # Saturday = 5, Sunday = 6
            prev_date -= timedelta(days=1)

        self.destroy()
        parent = self.master
        editor = LessonPlanEditor(
            parent,
            self.db,
            self._class_id,
            prev_date.strftime("%Y-%m-%d"),
            self._on_save
        )

    def _go_next_day(self):
        """Navigate to next school day."""
        if self._has_unsaved:
            response = Messagebox.show_question(
                "Unsaved Changes",
                "Save changes before navigating?",
                buttons=["Save:info", "Don't Save:warning", "Cancel:secondary"]
            )
            if response == "Save":
                self._on_save()
                return
            elif response == "Cancel":
                return

        # Find next school day (skip weekends)
        next_date = self.date_obj + timedelta(days=1)
        while next_date.weekday() >= 5:
            next_date += timedelta(days=1)

        self.destroy()
        parent = self.master
        editor = LessonPlanEditor(
            parent,
            self.db,
            self._class_id,
            next_date.strftime("%Y-%m-%d"),
            self._on_save
        )


class TemplateNameDialog(ttk.Toplevel):
    """Simple dialog for entering a template name."""

    def __init__(self, parent, title="Enter Name"):
        super().__init__(parent)
        self.title(title)
        self.geometry("350x120")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.result = None

        # Prompt
        ttk.Label(self, text="Template Name:", font=("Segoe UI", fs(10))).pack(pady=8)

        # Entry
        self.entry = ttk.Entry(self, width=35)
        self.entry.pack(pady=8, padx=12)
        self.entry.focus()

        # Buttons
        button_frame = ttk.Frame(self)
        button_frame.pack(pady=8)

        ttk.Button(
            button_frame,
            text="OK",
            command=self._on_ok,
            width=10
        ).pack(side=LEFT, padx=4)

        ttk.Button(
            button_frame,
            text="Cancel",
            command=self._on_cancel,
            width=10
        ).pack(side=LEFT, padx=4)

        self.entry.bind("<Return>", lambda e: self._on_ok())
        self.entry.bind("<Escape>", lambda e: self._on_cancel())

    def _on_ok(self):
        """Return the entered name."""
        name = self.entry.get().strip()
        if name:
            self.result = name
            self.destroy()

    def _on_cancel(self):
        """Close without result."""
        self.destroy()
