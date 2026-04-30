from __future__ import annotations

import argparse
import os
import queue
import threading
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

try:
    from .build_html_from_markdowns import build_site
    from .convert_pdfs_to_markdown import (
        DEFAULT_ENV_FILE,
        DEFAULT_PROFILE_FILE,
        DEFAULT_TAXONOMY_MODE,
        ConversionSummary,
        convert_folder,
        derive_default_output_dir,
        list_available_profile_files,
        load_env_file,
        load_profile,
    )
    from .pdf_availability_scanner import AvailabilityReportWindow, scan_pdf_directory_report
    from .rename_pdfs import batch_generate_rules, batch_process
except ImportError:
    from build_html_from_markdowns import build_site
    from convert_pdfs_to_markdown import (
        DEFAULT_ENV_FILE,
        DEFAULT_PROFILE_FILE,
        DEFAULT_TAXONOMY_MODE,
        ConversionSummary,
        convert_folder,
        derive_default_output_dir,
        list_available_profile_files,
        load_env_file,
        load_profile,
    )
    from pdf_availability_scanner import AvailabilityReportWindow, scan_pdf_directory_report
    from rename_pdfs import batch_generate_rules, batch_process


class ScrollFrame(ttk.Frame):
    def __init__(self, parent, **kwargs):
        ttk.Frame.__init__(self, parent, **kwargs)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(self, borderwidth=0, background="#f5f5f7", highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = tk.Frame(self.canvas, background="#f5f5f7")

        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")

        self.canvas_window = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw", tags="scrollable")

        self.scrollable_frame.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig("scrollable", width=event.width)

    def _on_frame_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


class QNAGuiApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("QNA Generator")
        self.root.geometry("1100x750")
        self.root.minsize(900, 650)

        self.message_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self._cancel_requested = False
        self.output_is_auto = True
        self.latest_site_index_path: Path | None = None
        self.current_view = tk.StringVar(value="convert")

        self.profile_options, self.profile_has_taxonomy = self._load_profile_options()
        self.input_dir_var = tk.StringVar()
        self.output_dir_var = tk.StringVar()
        self.profile_var = tk.StringVar(value=self._default_profile_label())
        self.taxonomy_mode_var = tk.StringVar(value=DEFAULT_TAXONOMY_MODE)
        self.env_file_var = tk.StringVar(value=str(DEFAULT_ENV_FILE))
        self.llm_mode_var = tk.StringVar(value="cleanup-and-tag")
        self.ocr_mode_var = tk.StringVar(value="rapidocr")
        self.page_ocr_fallback_var = tk.BooleanVar(value=True)
        self.embedding_mode_var = tk.StringVar(value="clip")
        self.html_theme_var = tk.StringVar(value="modern")
        self.paper_filter_var = tk.StringVar()
        self.limit_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Ready")
        self.status_color = tk.StringVar(value="#4CAF50")

        self._setup_styles()
        self._build_ui()
        self._bind_events()
        self._on_profile_changed()
        self.root.after(150, self._process_messages)

    def _setup_styles(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")

        base_bg = "#0c1a2e"
        sidebar_bg = "#0f2035"
        content_bg = "#f8fafc"
        section_bg = "#ffffff"
        accent = "#0891b2"
        accent_hover = "#0e7490"
        accent_light = "#22d3ee"
        success = "#059669"
        warning = "#d97706"
        error = "#dc2626"
        text_dark = "#0f172a"
        text_muted = "#64748b"
        border = "#e2e8f0"
        text_light = "#94a3b8"

        self.root.configure(bg=base_bg)

        style.configure("Main.TFrame", background=base_bg)
        style.configure("Sidebar.TFrame", background=sidebar_bg)
        style.configure("Content.TFrame", background=content_bg)
        style.configure("Section.TFrame", background=section_bg, relief="solid", borderwidth=1)

        style.configure("Title.TLabel",
            font=("Segoe UI", 20, "bold"),
            foreground="#ffffff",
            background=sidebar_bg)

        style.configure("Nav.TButton",
            font=("Segoe UI", 10),
            foreground=text_light,
            background=sidebar_bg,
            padding=(16, 12),
            borderwidth=0)
        style.map("Nav.TButton",
            background=[("active", "#1e3a5f"), ("pressed", "#1e3a5f"), ("hover", "#1e3a5f")],
            foreground=[("active", "#ffffff"), ("pressed", "#ffffff"), ("hover", "#ffffff")])

        style.configure("NavActive.TButton",
            font=("Segoe UI", 10, "bold"),
            foreground="#ffffff",
            background="#0891b2",
            padding=(16, 12),
            borderwidth=0)

        style.configure("SectionHeader.TLabel",
            font=("Segoe UI", 11, "bold"),
            foreground=text_dark,
            background=section_bg)

        style.configure("FieldLabel.TLabel",
            font=("Segoe UI", 9),
            foreground=text_muted,
            background=section_bg)

        style.configure("FieldValue.TLabel",
            font=("Segoe UI", 10),
            foreground=text_dark,
            background=section_bg)

        style.configure("Modern.TEntry",
            fieldbackground="#ffffff",
            borderwidth=1,
            padding=(10, 8))
        style.configure("Modern.TCombobox",
            fieldbackground="#ffffff",
            borderwidth=1,
            padding=(10, 8))

        style.configure("Primary.TButton",
            font=("Segoe UI", 10, "bold"),
            foreground="#ffffff",
            background=accent,
            padding=(20, 12),
            borderwidth=0)
        style.map("Primary.TButton",
            background=[("active", accent_hover), ("pressed", accent_hover), ("hover", accent_hover)])

        style.configure("Secondary.TButton",
            font=("Segoe UI", 10),
            foreground=accent,
            background="#ffffff",
            borderwidth=1,
            padding=(20, 12))
        style.map("Secondary.TButton",
            background=[("active", "#f0fdfa"), ("pressed", border)])

        style.configure("Action.TButton",
            font=("Segoe UI", 9),
            foreground=text_dark,
            background="#ffffff",
            borderwidth=1,
            padding=(14, 8))
        style.map("Action.TButton",
            background=[("active", "#f8fafc"), ("pressed", border)])

        style.configure("Modern.Horizontal.TProgressbar",
            thickness=6,
            borderwidth=0,
            background=accent)

        style.configure("Status.TLabel",
            font=("Segoe UI", 9),
            foreground=text_light,
            background=sidebar_bg)

        style.configure("Log.TFrame",
            background="#0f172a")

        style.configure("Card.TFrame",
            background=section_bg,
            relief="solid",
            borderwidth=1)

        style.configure("CardHeader.TLabel",
            font=("Segoe UI", 11, "bold"),
            foreground=text_dark,
            background=section_bg)

    def _build_ui(self) -> None:
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        self.sidebar = ttk.Frame(self.root, style="Sidebar.TFrame", width=220)
        self.sidebar.grid(row=0, column=0, sticky="nse")
        self.sidebar.pack_propagate(False)

        self.content_placeholder = ttk.Frame(self.root, style="Content.TFrame")
        self.content_placeholder.grid(row=0, column=1, sticky="nsew")
        self.content_placeholder.columnconfigure(0, weight=1)
        self.content_placeholder.rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_content()

    def _build_sidebar(self) -> None:
        sidebar = self.sidebar
        for widget in sidebar.winfo_children():
            widget.destroy()

        logo_frame = tk.Frame(sidebar, bg="#0891b2", height=80)
        logo_frame.pack(fill="x")
        logo_frame.pack_propagate(False)

        logo_label = tk.Label(
            logo_frame,
            text="QNA",
            font=("Segoe UI", 22, "bold"),
            fg="white",
            bg="#0891b2"
        )
        logo_label.pack(pady=(16, 0))

        subtitle_label = tk.Label(
            logo_frame,
            text="Generator",
            font=("Segoe UI", 10),
            fg="#22d3ee",
            bg="#0891b2"
        )
        subtitle_label.pack()

        nav_frame = tk.Frame(sidebar, bg="#0f2035")
        nav_frame.pack(fill="both", expand=True, pady=(16, 0))

        nav_items = [
            ("convert", "Convert PDFs", "convert"),
            ("rename", "Rename PDFs", "rename"),
            ("availability", "Availability", "availability"),
            ("settings", "Settings", "settings"),
        ]

        self.nav_buttons = {}
        for i, (view_id, label, icon) in enumerate(nav_items):
            btn = tk.Button(
                nav_frame,
                text=f"  {label}",
                font=("Segoe UI", 10),
                fg="#94a3b8",
                bg="#0f2035",
                activeforeground="#ffffff",
                activebackground="#1e3a5f",
                relief="flat",
                anchor="w",
                padx=16,
                pady=14,
                cursor="hand2",
                command=lambda v=view_id: self._switch_view(v)
            )
            btn.pack(fill="x", pady=2)
            self.nav_buttons[view_id] = btn

        self.nav_buttons[self.current_view.get()].configure(
            fg="#ffffff",
            bg="#1e3a5f"
        )

        status_frame = tk.Frame(sidebar, bg="#0f2035")
        status_frame.pack(side="bottom", fill="x", pady=16)

        divider = tk.Frame(status_frame, bg="#1e3a5f", height=1)
        divider.pack(fill="x", padx=16, pady=(0, 12))

        status_inner = tk.Frame(status_frame, bg="#0f2035")
        status_inner.pack(fill="x", padx=16)

        self.status_indicator = tk.Canvas(status_inner, width=8, height=8, bg="#059669", highlightthickness=0)
        self.status_indicator.pack(side="left", padx=(0, 8))
        self.status_indicator.create_oval(0, 0, 8, 8, fill="#059669", outline="")

        ttk.Label(status_inner, textvariable=self.status_var, style="Status.TLabel").pack(side="left")

    def _switch_view(self, view_id: str) -> None:
        self.current_view.set(view_id)
        for vid, btn in self.nav_buttons.items():
            if vid == view_id:
                btn.configure(fg="#ffffff", bg="#1e3a5f")
            else:
                btn.configure(fg="#94a3b8", bg="#0f2035")

        for widget in self.content_placeholder.winfo_children():
            widget.destroy()

        self.run_button = None
        self.full_pipeline_button = None
        self.build_site_button = None
        self.rename_button = None
        self.open_site_button = None
        self.cancel_button = None
        self.progress_bar = None
        self.log_text = None

        self._build_content()

    def _build_content(self) -> None:
        view = self.current_view.get()

        self.content_area = ttk.Frame(self.content_placeholder, style="Content.TFrame", padding=20)
        self.content_area.pack(fill="both", expand=True)

        if view == "convert":
            self._build_convert_view()
        elif view == "rename":
            self._build_rename_view()
        elif view == "availability":
            self._build_availability_view()
        elif view == "settings":
            self._build_settings_view()

        self.log_frame = tk.Frame(self.content_area, bg="#0f172a", relief="solid", borderwidth=1)
        self.log_frame.pack(fill="both", expand=True, pady=(16, 0))

        log_header = tk.Frame(self.log_frame, bg="#1e293b")
        log_header.pack(fill="x", padx=12, pady=8)

        tk.Label(
            log_header,
            text="Output Log",
            font=("Segoe UI", 9, "bold"),
            fg="#94a3b8",
            bg="#1e293b"
        ).pack(side="left")

        self.log_text = tk.Text(
            self.log_frame,
            wrap="word",
            height=8,
            font=("Consolas", 9),
            bg="#0f172a",
            fg="#22d3ee",
            insertbackground="#ffffff",
            relief="flat",
            borderwidth=0,
            padx=12,
            pady=8
        )
        self.log_text.pack(fill="both", expand=True, padx=0, pady=0)
        self.log_text.configure(state="disabled")

        scrollbar = tk.Scrollbar(self.log_frame, orient="vertical", command=self.log_text.yview, bg="#1e293b")
        scrollbar.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=scrollbar.set)

    def _build_convert_view(self) -> None:
        content = self.content_area

        header = tk.Frame(content, bg="#f8fafc")
        header.pack(fill="x", pady=(0, 20))

        title_frame = tk.Frame(header, bg="#f8fafc")
        title_frame.pack(fill="x")

        accent_line = tk.Frame(title_frame, bg="#0891b2", height=4, width=60)
        accent_line.pack(side="left", pady=(0, 10))

        tk.Label(
            title_frame,
            text="Convert PDFs to Markdown",
            font=("Segoe UI", 18, "bold"),
            fg="#0f172a",
            bg="#f8fafc"
        ).pack(side="left", padx=(12, 0))

        tk.Label(
            header,
            text="Select your PDF folder and configure options to generate markdown files",
            font=("Segoe UI", 10),
            fg="#64748b",
            bg="#f8fafc"
        ).pack(anchor="w", pady=(4, 0))

        scroll = ScrollFrame(content)
        scroll.pack(fill="both", expand=True)

        self._add_section(scroll.scrollable_frame, "Folders", [
            ("PDF Folder", "input_dir_var", "Browse", self._browse_input_folder),
            ("Output Folder", "output_dir_var", "Browse", self._browse_output_folder),
        ])

        self._add_section(scroll.scrollable_frame, "Processing", [
            ("Profile", "profile_var", None, None, tuple(self.profile_options.keys())),
            ("Taxonomy", "taxonomy_mode_var", None, None, ("auto", "static", "auto-draft")),
            ("LLM Mode", "llm_mode_var", None, None, ("off", "cleanup", "cleanup-and-tag")),
            ("OCR Mode", "ocr_mode_var", None, None, ("off", "rapidocr")),
            ("Embeddings", "embedding_mode_var", None, None, ("off", "clip")),
        ])

        self._add_section(scroll.scrollable_frame, "HTML Output", [
            ("HTML Theme", "html_theme_var", None, None, ("modern", "pdf")),
            ("Paper Filter", "paper_filter_var", None, None),
            ("Limit", "limit_var", None, None),
        ])

        self._add_section(scroll.scrollable_frame, "Advanced", [
            ("Page OCR Fallback", "page_ocr_fallback_var", None, "checkbox"),
            ("Env File", "env_file_var", "Browse", self._browse_env_file),
        ])

        self._build_action_buttons(content)

    def _build_rename_view(self) -> None:
        content = self.content_area

        header = tk.Frame(content, bg="#f8fafc")
        header.pack(fill="x", pady=(0, 20))

        title_frame = tk.Frame(header, bg="#f8fafc")
        title_frame.pack(fill="x")

        accent_line = tk.Frame(title_frame, bg="#0891b2", height=4, width=60)
        accent_line.pack(side="left", pady=(0, 10))

        tk.Label(
            title_frame,
            text="Rename PDFs",
            font=("Segoe UI", 18, "bold"),
            fg="#0f172a",
            bg="#f8fafc"
        ).pack(side="left", padx=(12, 0))

        tk.Label(
            header,
            text="Auto-rename messy exam PDFs to standardized names using LLM-generated rules",
            font=("Segoe UI", 10),
            fg="#64748b",
            bg="#f8fafc"
        ).pack(anchor="w", pady=(4, 0))

        scroll = ScrollFrame(content)
        scroll.pack(fill="both", expand=True)

        self._add_section(scroll.scrollable_frame, "Folder", [
            ("PDF Folder", "input_dir_var", "Browse", self._browse_input_folder),
        ])

        info_frame = tk.Frame(scroll.scrollable_frame, bg="#ffffff", relief="solid", borderwidth=1)
        info_frame.pack(fill="x", pady=(0, 16), padx=20)

        info_text = """The renamer uses a standardized naming convention:

{year}-{session}-{level}-{subject}-{board}-{code}-{paper}-{variant}-{type}.pdf

Examples:
  2024-s-igcse-biology-edexcel-4bi1-1-n-qp.pdf
  2018-jun-alevel-french-aqa-7652-p2-n-ms.pdf

Flow:
1. Generates rules from first 5 PDFs per subject
2. Renames remaining PDFs using stored rules
3. Low confidence (<0.7) files are logged for review"""

        tk.Label(
            info_frame,
            text=info_text,
            font=("Consolas", 9),
            foreground="#374151",
            background="#ffffff",
            justify="left",
            wraplength=500,
            anchor="w"
        ).pack(anchor="w")

        rename_frame = tk.Frame(scroll.scrollable_frame, bg="#ffffff", relief="solid", borderwidth=1)
        rename_frame.pack(fill="x", pady=(0, 16), padx=20)

        tk.Label(
            rename_frame,
            text="ACTIONS",
            font=("Segoe UI", 10, "bold"),
            fg="#0f172a",
            bg="#ffffff"
        ).pack(anchor="w", pady=(0, 12))

        btn_row = tk.Frame(rename_frame, bg="#ffffff")
        btn_row.pack(fill="x")

        self.rename_button = tk.Button(
            btn_row,
            text="Generate Rules & Rename All",
            font=("Segoe UI", 10, "bold"),
            fg="#ffffff",
            bg="#0891b2",
            activebackground="#0e7490",
            activeforeground="#ffffff",
            relief="flat",
            padx=20,
            pady=10,
            cursor="hand2",
            command=self._start_pdf_rename
        )
        self.rename_button.pack(side="left", padx=(0, 12))

        tk.Button(
            btn_row,
            text="Open Rules File",
            font=("Segoe UI", 9),
            fg="#0891b2",
            bg="#ffffff",
            activebackground="#f0fdfa",
            activeforeground="#0e7490",
            relief="solid",
            borderwidth=1,
            padx=16,
            pady=8,
            cursor="hand2",
            command=self._open_rules_file
        ).pack(side="left")

        if hasattr(self, "cancel_button") and self.cancel_button is not None:
            try:
                if self.cancel_button.winfo_exists():
                    self.cancel_button.pack(side="left", padx=(20, 0))
                    self.cancel_button.configure(state="disabled")
                    return
            except Exception:
                pass

        self.cancel_button = tk.Button(
            btn_row,
            text="Cancel",
            font=("Segoe UI", 9),
            fg="#64748b",
            bg="#ffffff",
            activebackground="#f1f5f9",
            activeforeground="#475569",
            relief="solid",
            borderwidth=1,
            padx=16,
            pady=8,
            cursor="hand2",
            command=self._cancel_worker
        )
        self.cancel_button.configure(state="disabled")
        self.cancel_button.pack(side="left", padx=(20, 0))

    def _build_availability_view(self) -> None:
        content = self.content_area

        header = tk.Frame(content, bg="#f8fafc")
        header.pack(fill="x", pady=(0, 20))

        title_frame = tk.Frame(header, bg="#f8fafc")
        title_frame.pack(fill="x")

        accent_line = tk.Frame(title_frame, bg="#0891b2", height=4, width=60)
        accent_line.pack(side="left", pady=(0, 10))

        tk.Label(
            title_frame,
            text="PDF Availability",
            font=("Segoe UI", 18, "bold"),
            fg="#0f172a",
            bg="#f8fafc"
        ).pack(side="left", padx=(12, 0))

        tk.Label(
            header,
            text="View and manage your exam paper collection",
            font=("Segoe UI", 10),
            fg="#64748b",
            bg="#f8fafc"
        ).pack(anchor="w", pady=(4, 0))

        scroll = ScrollFrame(content)
        scroll.pack(fill="both", expand=True)

        self._add_section(scroll.scrollable_frame, "Folder", [
            ("PDF Folder", "input_dir_var", "Browse", self._browse_input_folder),
        ])

        btn_frame = tk.Frame(scroll.scrollable_frame, bg="#ffffff", relief="solid", borderwidth=1)
        btn_frame.pack(fill="x", pady=(0, 16), padx=20)

        tk.Button(
            btn_frame,
            text="Scan Availability",
            font=("Segoe UI", 10, "bold"),
            fg="#ffffff",
            bg="#0891b2",
            activebackground="#0e7490",
            activeforeground="#ffffff",
            relief="flat",
            padx=20,
            pady=10,
            cursor="hand2",
            command=self._scan_availability
        ).pack(side="left")

    def _build_settings_view(self) -> None:
        content = self.content_area

        header = tk.Frame(content, bg="#f8fafc")
        header.pack(fill="x", pady=(0, 20))

        title_frame = tk.Frame(header, bg="#f8fafc")
        title_frame.pack(fill="x")

        accent_line = tk.Frame(title_frame, bg="#0891b2", height=4, width=60)
        accent_line.pack(side="left", pady=(0, 10))

        tk.Label(
            title_frame,
            text="Settings",
            font=("Segoe UI", 18, "bold"),
            fg="#0f172a",
            bg="#f8fafc"
        ).pack(side="left", padx=(12, 0))

        scroll = ScrollFrame(content)
        scroll.pack(fill="both", expand=True)

        self._add_section(scroll.scrollable_frame, "Environment", [
            ("Env File", "env_file_var", "Browse", self._browse_env_file),
        ])

    def _add_section(self, parent: ttk.Frame, title: str, fields: list) -> None:
        card = tk.Frame(parent, bg="#ffffff", relief="solid", borderwidth=1)
        card.pack(fill="x", pady=(0, 12), padx=20)

        header_frame = tk.Frame(card, bg="#ffffff")
        header_frame.pack(fill="x", pady=(0, 16))

        accent_bar = tk.Frame(header_frame, bg="#0891b2", width=4, height=20)
        accent_bar.pack(side="left", padx=(0, 10))

        tk.Label(
            header_frame,
            text=title.upper,
            font=("Segoe UI", 10, "bold"),
            fg="#0f172a",
            bg="#ffffff"
        ).pack(side="left")

        for field in fields:
            row = tk.Frame(card, bg="#ffffff")
            row.pack(fill="x", pady=(0, 12))

            field_label = field[0]
            var_name = field[1]
            button_text = field[2] if len(field) > 2 else None
            button_cmd = field[3] if len(field) > 3 else None
            values = field[4] if len(field) > 4 else None
            widget_type = field[5] if len(field) > 5 else None

            tk.Label(
                row,
                text=field_label,
                font=("Segoe UI", 9),
                fg="#64748b",
                bg="#ffffff",
                width=20,
                anchor="w"
            ).pack(side="left", padx=(0, 12))

            if widget_type == "checkbox":
                var = getattr(self, var_name)
                tk.Checkbutton(row, variable=var, text="", bg="#ffffff", activebackground="#ffffff").pack(side="left")
            elif values:
                var = getattr(self, var_name)
                combo = ttk.Combobox(row, textvariable=var, values=values, state="readonly", width=30, style="Modern.TCombobox")
                combo.pack(side="left", fill="x", expand=True)
            else:
                var = getattr(self, var_name)
                entry = ttk.Entry(row, textvariable=var, width=40, style="Modern.TEntry")
                entry.pack(side="left", fill="x", expand=True, padx=(0, 12))

            if button_text and button_cmd:
                btn = tk.Button(
                    row,
                    text=button_text,
                    font=("Segoe UI", 9),
                    fg="#0891b2",
                    bg="#ffffff",
                    activeforeground="#0e7490",
                    activebackground="#f0fdfa",
                    relief="solid",
                    borderwidth=1,
                    padx=12,
                    pady=4,
                    cursor="hand2",
                    command=button_cmd
                )
                btn.pack(side="left")

    def _build_action_buttons(self, parent: ttk.Frame) -> None:
        actions = tk.Frame(parent, bg="#f8fafc")
        actions.pack(fill="x", side="bottom", pady=(16, 0))

        progress_frame = tk.Frame(actions, bg="#f8fafc")
        progress_frame.pack(fill="x", pady=(0, 12))

        self.progress_bar = ttk.Progressbar(progress_frame, style="Modern.Horizontal.TProgressbar", mode="indeterminate")
        self.progress_bar.pack(fill="x")

        btn_row = tk.Frame(actions, bg="#f8fafc")
        btn_row.pack(fill="x")

        self.run_button = tk.Button(
            btn_row,
            text="Generate Markdown",
            font=("Segoe UI", 10, "bold"),
            fg="#ffffff",
            bg="#0891b2",
            activebackground="#0e7490",
            activeforeground="#ffffff",
            relief="flat",
            padx=20,
            pady=10,
            cursor="hand2",
            command=self._start_conversion
        )
        self.run_button.pack(side="left", padx=(0, 12))

        self.full_pipeline_button = tk.Button(
            btn_row,
            text="Run Full Pipeline",
            font=("Segoe UI", 10),
            fg="#0891b2",
            bg="#ffffff",
            activebackground="#f0fdfa",
            activeforeground="#0e7490",
            relief="solid",
            borderwidth=1,
            padx=20,
            pady=10,
            cursor="hand2",
            command=self._start_full_pipeline
        )
        self.full_pipeline_button.pack(side="left", padx=(0, 12))

        self.build_site_button = tk.Button(
            btn_row,
            text="Build HTML",
            font=("Segoe UI", 10),
            fg="#0891b2",
            bg="#ffffff",
            activebackground="#f0fdfa",
            activeforeground="#0e7490",
            relief="solid",
            borderwidth=1,
            padx=20,
            pady=10,
            cursor="hand2",
            command=self._start_html_build
        )
        self.build_site_button.pack(side="left", padx=(0, 12))

        tk.Button(
            btn_row,
            text="Open Output",
            font=("Segoe UI", 9),
            fg="#64748b",
            bg="#ffffff",
            activebackground="#f8fafc",
            activeforeground="#475569",
            relief="solid",
            borderwidth=1,
            padx=14,
            pady=8,
            cursor="hand2",
            command=self._open_output_folder
        ).pack(side="left", padx=(0, 12))

        self.open_site_button = tk.Button(
            btn_row,
            text="Open HTML Site",
            font=("Segoe UI", 9),
            fg="#64748b",
            bg="#ffffff",
            activebackground="#f8fafc",
            activeforeground="#475569",
            relief="solid",
            borderwidth=1,
            padx=14,
            pady=8,
            cursor="hand2",
            command=self._open_html_site
        )
        self.open_site_button.pack(side="left")

        self.cancel_button = tk.Button(
            btn_row,
            text="Cancel",
            font=("Segoe UI", 9),
            fg="#64748b",
            bg="#ffffff",
            activebackground="#f1f5f9",
            activeforeground="#475569",
            relief="solid",
            borderwidth=1,
            padx=14,
            pady=8,
            cursor="hand2",
            command=self._cancel_worker
        )
        self.cancel_button.configure(state="disabled")
        self.cancel_button.pack(side="left", padx=(20, 0))

    def _load_profile_options(self) -> tuple[dict[str, Path], dict[str, bool]]:
        options: dict[str, Path] = {}
        taxonomy_flags: dict[str, bool] = {}
        for path in list_available_profile_files():
            profile = load_profile(path)
            label = profile.name
            if label in options:
                label = f"{profile.name} ({path.name})"
            options[label] = path
            taxonomy_flags[label] = profile.taxonomy_file is not None

        if not options:
            fallback_path = (Path.cwd() / DEFAULT_PROFILE_FILE).resolve()
            options[str(fallback_path)] = fallback_path
            taxonomy_flags[str(fallback_path)] = False

        return options, taxonomy_flags

    def _default_profile_label(self) -> str:
        default_path = (Path.cwd() / DEFAULT_PROFILE_FILE).resolve()
        for label, path in self.profile_options.items():
            if path.resolve() == default_path:
                return label
        return next(iter(self.profile_options))

    def _selected_profile_path(self) -> Path:
        label = self.profile_var.get().strip()
        return self.profile_options.get(label, (Path.cwd() / DEFAULT_PROFILE_FILE).resolve())

    def _bind_events(self) -> None:
        self.input_dir_var.trace_add("write", self._on_input_changed)

    def _browse_input_folder(self) -> None:
        selected = filedialog.askdirectory(title="Select PDF Folder")
        if selected:
            self.input_dir_var.set(selected)

    def _browse_output_folder(self) -> None:
        initial = self.output_dir_var.get() or self.input_dir_var.get() or os.getcwd()
        selected = filedialog.askdirectory(title="Select Output Folder", initialdir=initial)
        if selected:
            self.output_is_auto = False
            self.output_dir_var.set(selected)

    def _browse_env_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select Env File",
            filetypes=(("Env files", "*.env"), ("All files", "*.*")),
            initialdir=os.getcwd(),
        )
        if selected:
            self.env_file_var.set(selected)

    def _on_input_changed(self, *_args: object) -> None:
        input_text = self.input_dir_var.get().strip()
        if not input_text:
            self.output_dir_var.set("")
            return
        self.output_dir_var.set(str(derive_default_output_dir(Path(input_text))))
        self.output_is_auto = True

    def _on_profile_changed(self) -> None:
        self._enforce_llm_mode_constraints()

    def _enforce_llm_mode_constraints(self) -> None:
        has_taxonomy = self.profile_has_taxonomy.get(self.profile_var.get().strip(), False)
        taxonomy_mode = self.taxonomy_mode_var.get().strip() or DEFAULT_TAXONOMY_MODE
        if not has_taxonomy and taxonomy_mode == "static" and self.llm_mode_var.get() == "cleanup-and-tag":
            self.llm_mode_var.set("cleanup")

    def _reset_output_to_default(self) -> None:
        input_text = self.input_dir_var.get().strip()
        if not input_text:
            messagebox.showinfo("Output Folder", "Select a PDF folder first.")
            return
        self.output_dir_var.set(str(derive_default_output_dir(Path(input_text))))
        self.output_is_auto = True

    def _open_output_folder(self) -> None:
        output_text = self.output_dir_var.get().strip()
        if not output_text:
            messagebox.showinfo("Open Output", "No output folder is set yet.")
            return
        path = Path(output_text)
        if not path.exists():
            messagebox.showinfo("Open Output", f"Output folder does not exist yet:\n{path}")
            return
        os.startfile(path)  # type: ignore[attr-defined]

    def _resolve_markdown_dir(self) -> Path:
        output_text = self.output_dir_var.get().strip()
        if output_text:
            markdown_dir = Path(output_text)
        else:
            input_text = self.input_dir_var.get().strip()
            if not input_text:
                raise ValueError("Select a markdown folder or set the PDF folder so the markdown folder can be derived.")
            markdown_dir = derive_default_output_dir(Path(input_text))
            self.output_dir_var.set(str(markdown_dir))
            self.output_is_auto = True

        if not markdown_dir.exists() or not markdown_dir.is_dir():
            raise ValueError(f"Markdown folder does not exist:\n{markdown_dir}")
        return markdown_dir

    def _expected_site_index_path(self) -> Path | None:
        output_text = self.output_dir_var.get().strip()
        if not output_text:
            return None
        output_dir = Path(output_text)
        site_dir = output_dir.parent / f"{output_dir.name}_site"
        return site_dir / "index.html"

    def _open_html_site(self) -> None:
        path = self.latest_site_index_path or self._expected_site_index_path()
        if path is None:
            messagebox.showinfo("Open HTML Site", "No HTML site path is available yet.")
            return
        if not path.exists():
            messagebox.showinfo("Open HTML Site", f"HTML site does not exist yet:\n{path}")
            return
        os.startfile(path)  # type: ignore[attr-defined]

    def _scan_availability(self) -> None:
        input_text = self.input_dir_var.get().strip()
        if not input_text:
            messagebox.showwarning("Scan Availability", "Please select a PDF folder first.")
            return
        input_dir = Path(input_text)
        if not input_dir.exists() or not input_dir.is_dir():
            messagebox.showerror("Scan Availability", f"PDF folder does not exist:\n{input_dir}")
            return

        self._append_log(f"Scanning: {input_dir}")
        report = scan_pdf_directory_report(input_dir)
        self._append_log(f"Found {len(report.papers)} papers")
        if report.review_items:
            self._append_log(f"Filename review entries: {len(report.review_items)} PDFs")

        AvailabilityReportWindow(self.root, report, input_dir)

    def _set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for btn_attr in ["run_button", "full_pipeline_button", "build_site_button", "rename_button", "open_site_button"]:
            if not hasattr(self, btn_attr):
                continue
            btn = getattr(self, btn_attr)
            try:
                if btn.winfo_exists():
                    btn.configure(state=state)
            except Exception:
                pass
        if hasattr(self, "progress_bar"):
            try:
                pb = self.progress_bar
                if pb.winfo_exists():
                    if enabled:
                        pb.stop()
                    else:
                        pb.start(10)
            except Exception:
                pass
        if hasattr(self, "cancel_button"):
            try:
                btn = self.cancel_button
                if btn.winfo_exists():
                    if enabled:
                        btn.configure(state="disabled")
                    else:
                        btn.configure(state="normal")
            except Exception:
                pass

    def _show_cancel_button(self) -> None:
        if not hasattr(self, "cancel_button"):
            return
        try:
            btn = self.cancel_button
            if btn.winfo_exists():
                btn.configure(state="normal")
        except Exception:
            pass

    def _hide_cancel_button(self) -> None:
        if not hasattr(self, "cancel_button"):
            return
        try:
            btn = self.cancel_button
            if btn.winfo_exists():
                btn.configure(state="disabled")
        except Exception:
            pass

    def _cancel_worker(self) -> None:
        self._cancel_requested = True
        self._append_log("Cancellation requested...")
        if self.worker and self.worker.is_alive():
            self.status_var.set("Cancelling...")

    def _open_rules_file(self) -> None:
        rules_file = Path(__file__).resolve().parent.parent / "config" / "subject_rules.json"
        if rules_file.exists():
            os.startfile(rules_file)
        else:
            messagebox.showinfo("Rules File", f"Rules file not found:\n{rules_file}")

    def _append_log(self, message: str) -> None:
        if not hasattr(self, "log_text"):
            return
        try:
            self.log_text.configure(state="normal")
            self.log_text.insert("end", message.rstrip() + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        except Exception:
            pass

    def _clear_log(self) -> None:
        if not hasattr(self, "log_text"):
            return
        try:
            self.log_text.configure(state="normal")
            self.log_text.delete("1.0", "end")
            self.log_text.configure(state="disabled")
        except Exception:
            pass

    def _build_args(self) -> tuple[argparse.Namespace, Path, Path]:
        input_text = self.input_dir_var.get().strip()
        output_text = self.output_dir_var.get().strip()
        env_text = self.env_file_var.get().strip() or str(DEFAULT_ENV_FILE)

        if not input_text:
            raise ValueError("Select a PDF folder.")
        input_dir = Path(input_text)
        if not input_dir.exists() or not input_dir.is_dir():
            raise ValueError(f"PDF folder does not exist:\n{input_dir}")

        output_dir = Path(output_text) if output_text else derive_default_output_dir(input_dir)

        limit_text = self.limit_var.get().strip()
        if limit_text:
            try:
                limit = int(limit_text)
            except ValueError as exc:
                raise ValueError("Limit must be a whole number.") from exc
        else:
            limit = None

        args = argparse.Namespace(
            input_dir=input_dir,
            output_dir=output_dir,
            limit=limit,
            paper_filter=self.paper_filter_var.get().strip() or None,
            profile_file=self._selected_profile_path(),
            taxonomy_mode=self.taxonomy_mode_var.get().strip() or DEFAULT_TAXONOMY_MODE,
            llm_mode=self.llm_mode_var.get(),
            llm_provider="minimax",
            ocr_mode=self.ocr_mode_var.get(),
            ocr_page_fallback=bool(self.page_ocr_fallback_var.get()),
            embedding_mode=self.embedding_mode_var.get(),
            embedding_model="clip-ViT-B-32",
            taxonomy_file=None,
            minimax_api_key=None,
            minimax_base_url=None,
            minimax_model=None,
            api_timeout_ms=None,
            env_file=Path(env_text),
            interactive=False,
            menu=False,
        )
        return args, input_dir, output_dir

    def _start_conversion(self) -> None:
        if self.worker and self.worker.is_alive():
            return

        try:
            args, input_dir, output_dir = self._build_args()
        except ValueError as exc:
            messagebox.showerror("Invalid Input", str(exc))
            return

        self._clear_log()
        self.latest_site_index_path = None

        self._cancel_requested = False
        self._set_controls_enabled(False)
        self._show_cancel_button()
        self.status_var.set("Running...")
        self._append_log(f"Input folder : {input_dir}")
        self._append_log(f"Output folder: {output_dir}")
        self._append_log(f"Profile file : {args.profile_file}")
        self._append_log(f"Taxonomy mode: {args.taxonomy_mode}")
        self._append_log(f"LLM mode     : {args.llm_mode}")
        self._append_log(f"OCR mode     : {args.ocr_mode}")
        self._append_log(f"Embeddings   : {args.embedding_mode}")
        self._append_log(f"Page OCR fb  : {args.ocr_page_fallback}")
        self._append_log("")

        self.worker = threading.Thread(
            target=self._run_conversion_worker,
            args=(args, input_dir, output_dir),
            daemon=True,
        )
        self.worker.start()

    def _start_full_pipeline(self) -> None:
        if self.worker and self.worker.is_alive():
            return

        try:
            args, input_dir, output_dir = self._build_args()
        except ValueError as exc:
            messagebox.showerror("Invalid Input", str(exc))
            return

        self._clear_log()
        self.latest_site_index_path = None

        site_output_dir = output_dir.parent / f"{output_dir.name}_site"
        self._set_controls_enabled(False)
        self.status_var.set("Running Full Pipeline...")
        self._append_log(f"Input folder : {input_dir}")
        self._append_log(f"Output folder: {output_dir}")
        self._append_log(f"HTML folder  : {site_output_dir}")
        self._append_log(f"Profile file : {args.profile_file}")
        self._append_log(f"Taxonomy mode: {args.taxonomy_mode}")
        self._append_log(f"LLM mode     : {args.llm_mode}")
        self._append_log(f"OCR mode     : {args.ocr_mode}")
        self._append_log(f"Embeddings   : {args.embedding_mode}")
        self._append_log(f"Page OCR fb  : {args.ocr_page_fallback}")
        self._append_log("")

        self.worker = threading.Thread(
            target=self._run_full_pipeline_worker,
            args=(args, input_dir, output_dir, site_output_dir),
            daemon=True,
        )
        self.worker.start()

    def _start_html_build(self) -> None:
        if self.worker and self.worker.is_alive():
            return

        try:
            markdown_dir = self._resolve_markdown_dir()
        except ValueError as exc:
            messagebox.showerror("Invalid Input", str(exc))
            return

        self._clear_log()
        self.latest_site_index_path = None

        site_output_dir = markdown_dir.parent / f"{markdown_dir.name}_site"
        self._set_controls_enabled(False)
        self.status_var.set("Building HTML...")
        self._append_log(f"Markdown folder: {markdown_dir}")
        self._append_log(f"HTML folder    : {site_output_dir}")
        self._append_log("")

        self.worker = threading.Thread(
            target=self._run_html_build_worker,
            args=(markdown_dir, site_output_dir),
            daemon=True,
        )
        self.worker.start()

    def _start_pdf_rename(self) -> None:
        if self.worker and self.worker.is_alive():
            return

        input_text = self.input_dir_var.get().strip()
        if not input_text:
            messagebox.showwarning("Rename PDFs", "Please select a PDF folder first.")
            return

        input_dir = Path(input_text)
        if not input_dir.exists() or not input_dir.is_dir():
            messagebox.showerror("Rename PDFs", f"PDF folder does not exist:\n{input_dir}")
            return

        self._clear_log()
        self._set_controls_enabled(False)
        self.status_var.set("Renaming PDFs...")
        self._append_log(f"PDF folder: {input_dir}")
        self._append_log("")

        self.worker = threading.Thread(
            target=self._run_pdf_rename_worker,
            args=(input_dir,),
            daemon=True,
        )
        self.worker.start()

    def _run_pdf_rename_worker(self, input_dir: Path) -> None:
        import asyncio
        try:
            from .minimax_client import MiniMaxClient, MiniMaxConfig
            from .rule_manager import RuleManager
            from .convert_pdfs_to_markdown import load_env_file
        except ImportError:
            from minimax_client import MiniMaxClient, MiniMaxConfig
            from rule_manager import RuleManager
            from convert_pdfs_to_markdown import load_env_file

        try:
            load_env_file(Path(__file__).resolve().parent.parent / ".env", overwrite=True)
            config = MiniMaxConfig.from_sources()
            client = MiniMaxClient(config)
            rule_manager = RuleManager()

            async def run_batch():
                rules_results = await batch_generate_rules(input_dir, client, rule_manager, self._emit_worker_log)
                rename_results = await batch_process(input_dir, client, rule_manager, self._emit_worker_log)
                return rules_results, rename_results

            rules_results, rename_results = asyncio.run(run_batch())

            total_renamed = sum(r.renamed for r in rename_results)
            total_low = sum(r.low_confidence for r in rename_results)
            total_errors = sum(len(r.errors) for r in rename_results)

            summary = []
            summary.append("Rules generated:")
            for k, v in sorted(rules_results.items()):
                summary.append(f"  {k}: {v} rules")
            summary.append("")
            summary.append(f"Renamed: {total_renamed}")
            summary.append(f"Low confidence (skipped): {total_low}")
            summary.append(f"Errors: {total_errors}")

            self.message_queue.put(
                (
                    "success",
                    {
                        "summary": "\n".join(summary),
                        "site_index_path": None,
                        "html_error": None,
                        "mode": "rename",
                    },
                )
            )
        except Exception as exc:  # noqa: BLE001
            details = "".join(traceback.format_exception(exc))
            self.message_queue.put(("error", details))

    def _run_conversion_worker(self, args: argparse.Namespace, input_dir: Path, output_dir: Path) -> None:
        try:
            load_env_file(Path(args.env_file), overwrite=True)
            self.message_queue.put(("log", f"[run] env loaded from {args.env_file}"))
            summary = convert_folder(args, input_dir, output_dir, logger=self._emit_worker_log)
            self.message_queue.put(
                (
                    "success",
                    {
                        "summary": self._format_conversion_summary(summary),
                        "site_index_path": None,
                        "html_error": None,
                        "mode": "conversion",
                    },
                )
            )
        except Exception as exc:  # noqa: BLE001
            details = "".join(traceback.format_exception(exc))
            self.message_queue.put(("error", details))

    def _run_full_pipeline_worker(
        self,
        args: argparse.Namespace,
        input_dir: Path,
        output_dir: Path,
        site_output_dir: Path,
    ) -> None:
        try:
            load_env_file(Path(args.env_file), overwrite=True)
            self.message_queue.put(("log", f"[run] env loaded from {args.env_file}"))
            summary = convert_folder(args, input_dir, output_dir, logger=self._emit_worker_log)
            self.message_queue.put(("log", f"[site] building html at {site_output_dir}"))
            html_theme = self.html_theme_var.get() or "modern"
            question_count, topic_count, site_index_path = build_site(output_dir, site_output_dir, image_mode="linked", theme=html_theme)
            self.message_queue.put(
                (
                    "success",
                    {
                        "summary": "\n".join(
                            [
                                self._format_conversion_summary(summary),
                                "",
                                f"Built HTML site: {site_output_dir}",
                                f"Question pages: {question_count}",
                                f"Topic pages: {topic_count}",
                                f"Home page: {site_index_path}",
                            ]
                        ),
                        "site_index_path": str(site_index_path),
                        "html_error": None,
                        "mode": "full_pipeline",
                    },
                )
            )
        except Exception as exc:  # noqa: BLE001
            details = "".join(traceback.format_exception(exc))
            self.message_queue.put(("error", details))

    def _run_html_build_worker(self, markdown_dir: Path, site_output_dir: Path) -> None:
        try:
            html_theme = self.html_theme_var.get() or "modern"
            question_count, topic_count, site_index_path = build_site(markdown_dir, site_output_dir, image_mode="linked", theme=html_theme)
            summary_text = "\n".join(
                [
                    f"Built HTML site: {site_output_dir}",
                    f"Question pages: {question_count}",
                    f"Topic pages: {topic_count}",
                    f"Home page: {site_index_path}",
                ]
            )
            self.message_queue.put(
                (
                    "success",
                    {
                        "summary": summary_text,
                        "site_index_path": str(site_index_path),
                        "html_error": None,
                        "mode": "html",
                    },
                )
            )
        except Exception as exc:  # noqa: BLE001
            details = "".join(traceback.format_exception(exc))
            self.message_queue.put(("error", details))

    def _emit_worker_log(self, message: str) -> None:
        self.message_queue.put(("log", message))

    def _format_conversion_summary(
        self,
        summary: ConversionSummary,
    ) -> str:
        lines = [
            f"Processed paired papers: {summary.processed_count}",
            f"Generated markdown files: {summary.generated_files}",
            f"Manifest: {summary.manifest_path}",
            f"Topic index: {summary.topic_index_path}",
            f"Asset manifest: {summary.asset_manifest_path}",
            f"Validation report: {summary.validation_report_path}",
        ]
        if summary.embedding_manifest_path is not None:
            lines.append(f"Embedding manifest: {summary.embedding_manifest_path}")
        if summary.skipped_messages:
            lines.append("Notes:")
            lines.extend(f"- {message}" for message in summary.skipped_messages)
        return "\n".join(lines)

    def _process_messages(self) -> None:
        try:
            if not self.root.winfo_exists():
                return
            while True:
                kind, payload = self.message_queue.get_nowait()
                if kind == "success":
                    payload_dict = dict(payload)
                    self._append_log(str(payload_dict.get("summary", "")))
                    site_index = payload_dict.get("site_index_path")
                    self.latest_site_index_path = Path(site_index) if site_index else None
                    self.status_var.set("Completed")
                    self._hide_cancel_button()
                    self._set_controls_enabled(True)
                    mode = payload_dict.get("mode")
                    try:
                        if mode == "html":
                            messagebox.showinfo("HTML Build Complete", "HTML site build finished successfully.")
                        elif mode == "full_pipeline":
                            messagebox.showinfo("Pipeline Complete", "Markdown generation and HTML build finished successfully.")
                        elif mode == "rename":
                            messagebox.showinfo("Rename Complete", "PDF renaming finished. Check the log for details.")
                        elif self.latest_site_index_path is not None:
                            messagebox.showinfo("Conversion Complete", "Conversion finished successfully.")
                        else:
                            messagebox.showinfo("Conversion Complete", "Conversion finished successfully.")
                    except Exception:
                        pass
                elif kind == "log":
                    self._append_log(str(payload))
                elif kind == "error":
                    self._append_log("Error:")
                    self._append_log(str(payload))
                    self.status_var.set("Failed")
                    self._hide_cancel_button()
                    self._set_controls_enabled(True)
                    try:
                        messagebox.showerror("Operation Failed", "Operation failed. Check the log for details.")
                    except Exception:
                        pass
        except queue.Empty:
            pass
        except Exception:
            pass
        finally:
            if self.root.winfo_exists():
                self.root.after(150, self._process_messages)


def main() -> int:
    root = tk.Tk()
    app = QNAGuiApp(root)
    load_env_file(DEFAULT_ENV_FILE)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
