import csv
import os
import queue
import threading
import time
import tkinter as tk
from collections import defaultdict
from datetime import date, datetime, timedelta
from tkinter import filedialog, messagebox, scrolledtext, ttk

from watchdog.observers import Observer

from analytics import INSIGHTS_FOLDER, LOG_FILE_NAME, initialize_log_file
from fileHandler import (
    FileHandler,
    auto_detect_edge_history_path,
    get_saved_edge_history_path,
    set_saved_edge_history_path,
)

DEFAULT_DOWNLOAD_FOLDER = os.path.join(os.path.expanduser("~"), "Downloads")
REFRESH_INTERVAL_MS = 4000
LOG_POLL_INTERVAL_MS = 250


class DownloadInsightsApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Download Insights")
        self.root.minsize(960, 640)
        self.root.configure(background="#11121b")

        self.style = ttk.Style()
        self._setup_styles()

        self.path_var = tk.StringVar()
        if os.path.isdir(DEFAULT_DOWNLOAD_FOLDER):
            self.path_var.set(DEFAULT_DOWNLOAD_FOLDER)

        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.monitor_thread: threading.Thread | None = None
        self.observer: Observer | None = None
        self.stop_event = threading.Event()
        self.monitoring = False
        self.csv_path: str | None = None
        self.csv_mtime: float | None = None
        self.tree_columns: list[str] = []
        self.canvas: tk.Canvas | None = None
        self.canvas_window: int | None = None

        self.insights_data: list[dict[str, str]] = []
        self.domain_colors: dict[str, str] = {}
        self.custom_date_range = False
        self._color_palette = [
            "#6366f1",
            "#38bdf8",
            "#f472b6",
            "#22c55e",
            "#f97316",
            "#facc15",
            "#a855f7",
            "#ec4899",
            "#14b8a6",
            "#ef4444",
            "#4ade80",
            "#60a5fa",
        ]
        self._color_index = 0

        self.total_files_var = tk.StringVar(value="0")
        self.total_size_var = tk.StringVar(value="0 B")
        self.total_duplicates_var = tk.StringVar(value="0")
        self.start_date_var = tk.StringVar()
        self.end_date_var = tk.StringVar()
        self.range_error_var = tk.StringVar(value="")

        self.edge_history_var = tk.StringVar()
        saved_edge_history = get_saved_edge_history_path()
        if saved_edge_history:
            self.edge_history_var.set(saved_edge_history)
        else:
            detected_edge_history = auto_detect_edge_history_path()
            if detected_edge_history:
                self.edge_history_var.set(detected_edge_history)

        self._build_layout()
        self._update_csv_path(self.path_var.get())

        self.root.after(LOG_POLL_INTERVAL_MS, self._process_log_queue)
        self.root.after(REFRESH_INTERVAL_MS, self._check_csv_updates)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # UI construction & styling
    # ------------------------------------------------------------------
    def _setup_styles(self) -> None:
        self.style.theme_use("clam")
        background = "#11121b"
        card = "#18192b"
        accent = "#6366f1"
        accent_hover = "#7c7ffb"
        text_primary = "#f4f6fb"
        text_secondary = "#cbd5f5"

        self.style.configure("TFrame", background=background)
        self.style.configure("Card.TFrame", background=card, relief="flat")
        self.style.configure("Heading.TLabel", background=card, foreground=text_primary, font=("Segoe UI", 16, "bold"))
        self.style.configure("Subheading.TLabel", background=card, foreground=text_secondary, font=("Segoe UI", 11))
        self.style.configure("TLabel", background=background, foreground=text_primary, font=("Segoe UI", 11))
        self.style.configure("Status.TLabel", background=card, foreground=text_secondary, font=("Segoe UI", 10))
        self.style.configure("Accent.TButton", font=("Segoe UI", 11, "bold"), padding=8)
        self.style.configure("TButton", background=card, foreground=text_primary, font=("Segoe UI", 11), padding=8)
        self.style.map(
            "Accent.TButton",
            background=[("disabled", "#3b3d70"), ("pressed", accent), ("active", accent_hover)],
            foreground=[("disabled", "#777a9e")],
        )
        self.style.map(
            "TButton",
            background=[("pressed", card), ("active", "#20223a")],
            foreground=[("disabled", "#777a9e")],
        )
        self.style.configure("Modern.TEntry", fieldbackground="#1f2032", background="#1f2032", foreground=text_primary, insertcolor=text_primary, padding=6)
        self.style.map("Modern.TEntry", fieldbackground=[("disabled", "#151627")])
        self.style.configure("Insights.Treeview", background="#1c1d2d", fieldbackground="#1c1d2d", foreground=text_primary, rowheight=30, bordercolor=card, borderwidth=0, font=("Segoe UI", 10))
        self.style.map("Insights.Treeview", background=[("selected", accent)], foreground=[("selected", text_primary)])
        self.style.configure("Insights.Treeview.Heading", background=card, foreground=text_secondary, font=("Segoe UI", 10, "bold"))
        self.style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        self.style.configure("TScrollbar", background=card, troughcolor=background, gripcount=0, bordercolor=background, darkcolor=background, lightcolor=background)

    def _build_layout(self) -> None:
        container = ttk.Frame(self.root, style="TFrame")
        container.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(
            container,
            background="#11121b",
            highlightthickness=0,
            borderwidth=0,
        )
        self.canvas.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(container, orient="vertical", command=self.canvas.yview)
        scrollbar.pack(side="right", fill="y")

        self.canvas.configure(yscrollcommand=scrollbar.set)

        content = ttk.Frame(self.canvas, padding=24, style="TFrame")
        self.canvas_window = self.canvas.create_window((0, 0), window=content, anchor="nw")

        content.bind("<Configure>", self._on_content_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Button-4>", self._on_mousewheel)
        self.canvas.bind_all("<Button-5>", self._on_mousewheel)

        control_card = ttk.Frame(content, style="Card.TFrame", padding=24)
        control_card.pack(fill="x")

        controls = ttk.Frame(control_card, style="Card.TFrame")
        controls.pack(fill="x")

        path_label = ttk.Label(controls, text="Download folder", style="TLabel")
        path_label.grid(row=0, column=0, sticky="w")

        path_entry = ttk.Entry(controls, textvariable=self.path_var, style="Modern.TEntry")
        path_entry.grid(row=1, column=0, sticky="ew", padx=(0, 12), pady=(6, 0))

        browse_button = ttk.Button(controls, text="Browse", command=self._browse_for_folder)
        browse_button.grid(row=1, column=1, sticky="ew", pady=(6, 0))

        edge_label = ttk.Label(controls, text="Edge history database", style="TLabel")
        edge_label.grid(row=2, column=0, sticky="w", pady=(18, 0))

        edge_entry = ttk.Entry(controls, textvariable=self.edge_history_var, style="Modern.TEntry")
        edge_entry.grid(row=3, column=0, sticky="ew", padx=(0, 12), pady=(6, 0))

        edge_browse = ttk.Button(controls, text="Browse", command=self._browse_for_edge_history)
        edge_browse.grid(row=3, column=1, sticky="ew", pady=(6, 0))

        edge_auto = ttk.Button(controls, text="Use auto-detected", command=self._use_auto_edge_history)
        edge_auto.grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))

        controls.columnconfigure(0, weight=1)

        button_row = ttk.Frame(control_card, style="Card.TFrame")
        button_row.pack(fill="x", pady=(18, 0))

        self.start_button = ttk.Button(button_row, text="Start monitoring", style="Accent.TButton", command=self.start_monitoring)
        self.start_button.grid(row=0, column=0, sticky="w")

        self.stop_button = ttk.Button(button_row, text="Stop", command=self.stop_monitoring, state="disabled")
        self.stop_button.grid(row=0, column=1, padx=(12, 0), sticky="w")

        self.status_label = ttk.Label(button_row, text="Idle", style="Status.TLabel")
        self.status_label.grid(row=0, column=2, padx=(24, 0), sticky="e")
        button_row.columnconfigure(2, weight=1)

        tabs_container = ttk.Frame(content, style="Card.TFrame")
        tabs_container.pack(fill="both", expand=True, pady=(24, 0))

        self.notebook = ttk.Notebook(tabs_container)
        self.notebook.pack(fill="both", expand=True)

        insights_tab = ttk.Frame(self.notebook, style="Card.TFrame", padding=24)
        analytics_tab = ttk.Frame(self.notebook, style="Card.TFrame", padding=24)

        self.notebook.add(insights_tab, text="Insights")
        self.notebook.add(analytics_tab, text="Analytics")

        self._build_insights_tab(insights_tab)
        self._build_analytics_tab(analytics_tab)

        log_card = ttk.Frame(content, style="Card.TFrame", padding=24)
        log_card.pack(fill="both", expand=True, pady=(24, 0))

        log_header = ttk.Label(log_card, text="Activity log", style="Heading.TLabel")
        log_header.pack(anchor="w")

        log_subheader = ttk.Label(log_card, text="Live updates from the download monitor.", style="Subheading.TLabel")
        log_subheader.pack(anchor="w", pady=(4, 12))

        self.log_text = scrolledtext.ScrolledText(log_card, height=6, wrap="word", font=("Consolas", 10))
        self.log_text.pack(fill="both", expand=True)
        self.log_text.configure(background="#151624", foreground="#e2e8f0", insertbackground="#f8fafc", borderwidth=0, highlightthickness=0)
        self.log_text.configure(state="disabled")

    def _build_insights_tab(self, parent: ttk.Frame) -> None:
        insights_header = ttk.Label(parent, text="Download insights", style="Heading.TLabel")
        insights_header.pack(anchor="w")

        insights_subheader = ttk.Label(
            parent,
            text="Review captured download events without leaving the application.",
            style="Subheading.TLabel",
        )
        insights_subheader.pack(anchor="w", pady=(4, 12))

        tree_frame = ttk.Frame(parent, style="Card.TFrame")
        tree_frame.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(tree_frame, columns=self.tree_columns, show="headings", style="Insights.Treeview")
        self.tree.pack(side="left", fill="both", expand=True)

        y_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        y_scroll.pack(side="right", fill="y")
        x_scroll = ttk.Scrollbar(parent, orient="horizontal", command=self.tree.xview)
        x_scroll.pack(fill="x", pady=(6, 0))

        self.tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.tree.tag_configure("odd", background="#1e1f31")
        self.tree.tag_configure("even", background="#191a29")

        self.empty_state = ttk.Label(
            tree_frame,
            text="No insights yet. Start monitoring to populate this view.",
            style="Subheading.TLabel",
            anchor="center",
            justify="center",
        )

    def _build_analytics_tab(self, parent: ttk.Frame) -> None:
        analytics_header = ttk.Label(parent, text="Analytics overview", style="Heading.TLabel")
        analytics_header.pack(anchor="w")

        analytics_subheader = ttk.Label(
            parent,
            text="Understand download activity by domain, size, and time.",
            style="Subheading.TLabel",
        )
        analytics_subheader.pack(anchor="w", pady=(4, 18))

        summary_frame = ttk.Frame(parent, style="Card.TFrame")
        summary_frame.pack(fill="x")

        metrics = (
            ("Total files", self.total_files_var),
            ("Total size", self.total_size_var),
            ("Duplicates", self.total_duplicates_var),
        )

        for index, (label, variable) in enumerate(metrics):
            metric_frame = ttk.Frame(summary_frame, style="Card.TFrame", padding=12)
            metric_frame.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 18, 0))
            title = ttk.Label(metric_frame, text=label, style="Subheading.TLabel")
            title.pack(anchor="w")
            value = ttk.Label(metric_frame, textvariable=variable, style="Heading.TLabel")
            value.pack(anchor="w", pady=(6, 0))
            summary_frame.columnconfigure(index, weight=1)

        domain_frame = ttk.Frame(parent, style="Card.TFrame")
        domain_frame.pack(fill="both", expand=True, pady=(24, 0))

        domain_header = ttk.Label(domain_frame, text="Per domain details", style="Subheading.TLabel")
        domain_header.pack(anchor="w")

        domain_tree_container = ttk.Frame(domain_frame, style="Card.TFrame")
        domain_tree_container.pack(fill="both", expand=True, pady=(6, 0))

        self.domain_tree = ttk.Treeview(
            domain_tree_container,
            columns=("Domain", "Files", "Data Size", "Duplicates"),
            show="headings",
            style="Insights.Treeview",
            height=8,
        )
        self.domain_tree.pack(side="left", fill="both", expand=True)

        domain_y_scroll = ttk.Scrollbar(domain_tree_container, orient="vertical", command=self.domain_tree.yview)
        domain_y_scroll.pack(side="right", fill="y")
        self.domain_tree.configure(yscrollcommand=domain_y_scroll.set)

        for column, width in zip(("Domain", "Files", "Data Size", "Duplicates"), (180, 100, 140, 120)):
            anchor = "w" if column == "Domain" else "center"
            self.domain_tree.heading(column, text=column, anchor=anchor)
            self.domain_tree.column(column, width=width, anchor=anchor, stretch=True)

        self.domain_tree.tag_configure("odd", background="#1e1f31")
        self.domain_tree.tag_configure("even", background="#191a29")

        range_frame = ttk.Frame(parent, style="Card.TFrame")
        range_frame.pack(fill="x", pady=(24, 12))

        range_title = ttk.Label(range_frame, text="Date range (YYYY-MM-DD)", style="Subheading.TLabel")
        range_title.grid(row=0, column=0, columnspan=4, sticky="w")

        start_label = ttk.Label(range_frame, text="Start", style="TLabel")
        start_label.grid(row=1, column=0, sticky="w", pady=(6, 0))
        start_entry = ttk.Entry(range_frame, textvariable=self.start_date_var, style="Modern.TEntry")
        start_entry.grid(row=1, column=1, sticky="ew", padx=(6, 18), pady=(6, 0))

        end_label = ttk.Label(range_frame, text="End", style="TLabel")
        end_label.grid(row=1, column=2, sticky="w", pady=(6, 0))
        end_entry = ttk.Entry(range_frame, textvariable=self.end_date_var, style="Modern.TEntry")
        end_entry.grid(row=1, column=3, sticky="ew", padx=(6, 0), pady=(6, 0))

        range_frame.columnconfigure(1, weight=1)
        range_frame.columnconfigure(3, weight=1)

        apply_button = ttk.Button(range_frame, text="Apply", command=self._apply_date_range)
        apply_button.grid(row=2, column=1, sticky="w", pady=(12, 0))

        reset_button = ttk.Button(range_frame, text="Last 10 days", command=self._reset_date_range)
        reset_button.grid(row=2, column=3, sticky="e", pady=(12, 0))

        error_label = ttk.Label(range_frame, textvariable=self.range_error_var, style="Status.TLabel")
        error_label.grid(row=3, column=0, columnspan=4, sticky="w", pady=(8, 0))

        chart_frame = ttk.Frame(parent, style="Card.TFrame")
        chart_frame.pack(fill="both", expand=True)

        self.chart_canvas = tk.Canvas(
            chart_frame,
            height=280,
            background="#11121b",
            highlightthickness=0,
            borderwidth=0,
        )
        self.chart_canvas.pack(fill="both", expand=True)
        self.chart_canvas.bind("<Configure>", self._on_chart_resized)

        self.legend_frame = ttk.Frame(parent, style="Card.TFrame")
        self.legend_frame.pack(fill="x", pady=(12, 0))

    def _on_content_configure(self, event: tk.Event) -> None:
        if self.canvas is not None:
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        if self.canvas is not None and self.canvas_window is not None:
            self.canvas.itemconfigure(self.canvas_window, width=event.width)

    def _on_mousewheel(self, event: tk.Event) -> None:
        if self.canvas is None:
            return
        if event.delta:
            self.canvas.yview_scroll(int(-event.delta / 120), "units")
        elif event.num == 4:
            self.canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self.canvas.yview_scroll(1, "units")

    # ------------------------------------------------------------------
    # Monitoring controls
    # ------------------------------------------------------------------
    def _browse_for_folder(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.path_var.get() or None, title="Select download folder")
        if selected:
            self.path_var.set(selected)
            self._update_csv_path(selected)
            self._queue_message(f"Download folder set to {selected}")

    def _browse_for_edge_history(self) -> None:
        initial = self.edge_history_var.get()
        initial_dir = os.path.dirname(initial) if initial else None
        selected = filedialog.askopenfilename(
            initialdir=initial_dir,
            title="Select Edge history database",
            filetypes=(
                ("Edge history database", "History"),
                ("SQLite databases", "*.sqlite *.db"),
                ("All files", "*.*"),
            ),
        )
        if selected:
            self.edge_history_var.set(selected)
            set_saved_edge_history_path(selected)
            self._queue_message(f"Edge history database set to {selected}")

    def _use_auto_edge_history(self) -> None:
        detected = auto_detect_edge_history_path()
        if detected:
            self.edge_history_var.set(detected)
            set_saved_edge_history_path(None)
            self._queue_message(f"Using auto-detected Edge history database at {detected}")
        else:
            messagebox.showwarning(
                "Download Insights",
                "Unable to locate the Microsoft Edge history database automatically."
                " Please select the file manually.",
            )

    def _update_csv_path(self, folder: str | None) -> None:
        if folder and os.path.isdir(folder):
            self.csv_path = os.path.join(folder, INSIGHTS_FOLDER, LOG_FILE_NAME)
        else:
            self.csv_path = None
        self.csv_mtime = None
        self.load_csv_data()

    def start_monitoring(self) -> None:
        if self.monitoring:
            messagebox.showinfo("Download Insights", "Monitoring is already running.")
            return

        folder = self.path_var.get().strip()
        if not folder:
            messagebox.showerror("Download Insights", "Please select a download folder before starting the monitor.")
            return

        if not os.path.isdir(folder):
            messagebox.showerror("Download Insights", f"The folder '{folder}' does not exist or is not accessible.")
            return

        edge_history_path = self.edge_history_var.get().strip()
        if edge_history_path:
            if os.path.isfile(edge_history_path):
                set_saved_edge_history_path(edge_history_path)
            else:
                messagebox.showwarning(
                    "Download Insights",
                    "The specified Edge history database does not exist."
                    " The application will attempt to detect it automatically.",
                )
                set_saved_edge_history_path(None)
        else:
            set_saved_edge_history_path(None)

        try:
            initialize_log_file(folder)
        except OSError as exc:
            messagebox.showerror("Download Insights", f"Unable to prepare the insights log file.\n{exc}")
            return

        self._update_csv_path(folder)
        self.stop_event = threading.Event()
        self.monitoring = True
        self.status_label.configure(text=f"Monitoring {folder}")
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self._queue_message(f"Started monitoring {folder}")

        self.monitor_thread = threading.Thread(target=self._monitor_downloads, args=(folder,), daemon=True)
        self.monitor_thread.start()

    def _monitor_downloads(self, folder: str) -> None:
        observer = Observer()
        handler = FileHandler(folder, self._queue_message)
        try:
            observer.schedule(handler, folder, recursive=False)
            observer.start()
            self.observer = observer
            while not self.stop_event.is_set():
                time.sleep(0.5)
        except Exception as exc:
            self._queue_message(f"Monitoring stopped unexpectedly: {exc}")
            message = f"Monitoring stopped unexpectedly. {exc}"
            self.root.after(0, lambda: messagebox.showerror("Download Insights", message))
        finally:
            observer.stop()
            observer.join()
            self.observer = None
            self.stop_event.set()
            self._queue_message("Monitoring stopped.")
            self.root.after(0, self._on_monitoring_stopped)

    def stop_monitoring(self) -> None:
        if not self.monitoring:
            return
        self._queue_message("Stopping download monitor...")
        self.stop_event.set()
        if self.observer:
            self.observer.stop()
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
            self.monitor_thread = None

    def _on_monitoring_stopped(self) -> None:
        self.monitoring = False
        self.status_label.configure(text="Idle")
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.load_csv_data()

    # ------------------------------------------------------------------
    # CSV handling & insights table
    # ------------------------------------------------------------------
    def load_csv_data(self) -> None:
        self._hide_empty_state()
        for item in self.tree.get_children():
            self.tree.delete(item)

        if not self.csv_path or not os.path.exists(self.csv_path):
            self.csv_mtime = None
            self.insights_data = []
            self._update_analytics_from_csv()
            self._show_empty_state("No insights yet. Start monitoring to populate this view.")
            return

        try:
            with open(self.csv_path, newline="", encoding="utf-8") as csv_file:
                reader = csv.reader(csv_file)
                rows = list(reader)
        except OSError as exc:
            self._queue_message(f"Unable to read insights file: {exc}")
            self.csv_mtime = None
            self.insights_data = []
            self._update_analytics_from_csv()
            self._show_empty_state("Unable to read insights file.")
            return

        if not rows:
            self.csv_mtime = None
            self.insights_data = []
            self._update_analytics_from_csv()
            self._show_empty_state("The insights file is empty.")
            return

        header, *data_rows = rows
        self._setup_tree_columns(header)

        self.insights_data = self._parse_csv_rows(header, data_rows)
        self._update_analytics_from_csv()

        for index, row in enumerate(data_rows):
            tag = "even" if index % 2 == 0 else "odd"
            self.tree.insert("", "end", values=row, tags=(tag,))

        if not data_rows:
            self._show_empty_state("No insights recorded yet.")

        try:
            self.csv_mtime = os.path.getmtime(self.csv_path)
        except OSError:
            self.csv_mtime = None

    def _setup_tree_columns(self, header: list[str]) -> None:
        if header != self.tree_columns:
            self.tree_columns = header
            self.tree.configure(columns=header)
            for column in header:
                self.tree.heading(column, text=column, anchor="w")
                width = 160
                if column in {"File Path", "Download URL"}:
                    width = 280
                elif column == "Timestamp":
                    width = 180
                elif column == "Event":
                    width = 120
                self.tree.column(column, width=width, anchor="w", stretch=True)

    # ------------------------------------------------------------------
    # Analytics helpers
    # ------------------------------------------------------------------
    def _parse_csv_rows(self, header: list[str], data_rows: list[list[str]]) -> list[dict[str, str]]:
        parsed: list[dict[str, str]] = []
        for row in data_rows:
            record: dict[str, str] = {}
            for index, column in enumerate(header):
                record[column] = row[index] if index < len(row) else ""
            parsed.append(record)
        return parsed

    def _update_analytics_from_csv(self) -> None:
        domain_totals: dict[str, dict[str, int]] = defaultdict(lambda: {"count": 0, "size": 0, "duplicates": 0})
        total_files = 0
        total_size = 0
        total_duplicates = 0

        for record in self.insights_data:
            domain = (record.get("Domain") or "Unknown").strip() or "Unknown"
            size_value = record.get("File Size", "")
            try:
                size = int(size_value)
            except (TypeError, ValueError):
                size = 0
            duplicate_value = (record.get("Is Duplicate") or "No").strip().lower()
            is_duplicate = duplicate_value in {"yes", "true", "1"}

            domain_totals[domain]["count"] += 1
            domain_totals[domain]["size"] += size
            if is_duplicate:
                domain_totals[domain]["duplicates"] += 1

            total_files += 1
            total_size += size
            if is_duplicate:
                total_duplicates += 1

        self._set_total_summary(total_files, total_size, total_duplicates)
        self._populate_domain_tree(domain_totals)

        if self.custom_date_range:
            self._refresh_chart()
        else:
            self._set_default_date_range()

    def _set_total_summary(self, total_files: int, total_size: int, duplicates: int) -> None:
        self.total_files_var.set(str(total_files))
        self.total_size_var.set(self._format_bytes(total_size))
        self.total_duplicates_var.set(str(duplicates))

    def _populate_domain_tree(self, domain_totals: dict[str, dict[str, int]]) -> None:
        for item in self.domain_tree.get_children():
            self.domain_tree.delete(item)

        sorted_items = sorted(domain_totals.items(), key=lambda item: item[1]["count"], reverse=True)

        for index, (domain, totals) in enumerate(sorted_items):
            tag = "even" if index % 2 == 0 else "odd"
            self.domain_tree.insert(
                "",
                "end",
                values=(
                    domain,
                    totals["count"],
                    self._format_bytes(totals["size"]),
                    totals["duplicates"],
                ),
                tags=(tag,),
            )

    def _format_bytes(self, size: int) -> str:
        if size <= 0:
            return "0 B"
        units = ["B", "KB", "MB", "GB", "TB"]
        value = float(size)
        unit_index = 0
        while value >= 1024 and unit_index < len(units) - 1:
            value /= 1024
            unit_index += 1
        if unit_index == 0:
            return f"{int(value)} {units[unit_index]}"
        return f"{value:.2f} {units[unit_index]}"

    def _set_default_date_range(self) -> None:
        if not self.insights_data:
            today = datetime.now().date()
            self.start_date_var.set((today - timedelta(days=9)).isoformat())
            self.end_date_var.set(today.isoformat())
            self.range_error_var.set("")
            self._refresh_chart()
            return

        dates: list[date] = []
        for record in self.insights_data:
            timestamp = record.get("Timestamp", "")
            try:
                parsed = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            dates.append(parsed.date())

        if not dates:
            today = datetime.now().date()
            start_date = today - timedelta(days=9)
            end_date = today
        else:
            end_date = max(dates)
            start_date = max(end_date - timedelta(days=9), min(dates))

        self.start_date_var.set(start_date.isoformat())
        self.end_date_var.set(end_date.isoformat())
        self.range_error_var.set("")
        self._refresh_chart()

    def _apply_date_range(self) -> None:
        start_date = self._parse_date(self.start_date_var.get())
        end_date = self._parse_date(self.end_date_var.get())

        if start_date is None or end_date is None:
            self.range_error_var.set("Enter start and end dates as YYYY-MM-DD.")
            self._refresh_chart()
            return

        if start_date > end_date:
            self.range_error_var.set("Start date must be before end date.")
            self._refresh_chart()
            return

        self.range_error_var.set("")
        self.custom_date_range = True
        self._refresh_chart()

    def _reset_date_range(self) -> None:
        self.custom_date_range = False
        self._set_default_date_range()

    def _parse_date(self, value: str) -> date | None:
        value = (value or "").strip()
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return None

    def _refresh_chart(self) -> None:
        if self.chart_canvas is None:
            return

        self.chart_canvas.delete("all")

        start_date = self._parse_date(self.start_date_var.get())
        end_date = self._parse_date(self.end_date_var.get())

        if start_date is None or end_date is None:
            self._draw_chart_message("Enter start and end dates to view chart data.")
            return

        if start_date > end_date:
            self._draw_chart_message("Invalid date range selected.")
            return

        day_counts: dict[date, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        all_domains: set[str] = set()

        for record in self.insights_data:
            timestamp = record.get("Timestamp", "")
            try:
                parsed = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            day = parsed.date()
            if day < start_date or day > end_date:
                continue
            domain = (record.get("Domain") or "Unknown").strip() or "Unknown"
            day_counts[day][domain] += 1
            all_domains.add(domain)

        days: list[date] = []
        current_day = start_date
        while current_day <= end_date:
            days.append(current_day)
            current_day += timedelta(days=1)

        total_per_day = [sum(day_counts[day].values()) for day in days]
        max_total = max(total_per_day) if total_per_day else 0

        if max_total == 0:
            self._draw_chart_message("No downloads recorded in the selected range.")
            self._update_legend(sorted(all_domains))
            return

        width = max(self.chart_canvas.winfo_width(), 1)
        height = max(self.chart_canvas.winfo_height(), 1)
        margin_left = 60
        margin_right = 24
        margin_top = 24
        margin_bottom = 48

        chart_width = max(width - margin_left - margin_right, 1)
        chart_height = max(height - margin_top - margin_bottom, 1)
        bar_slot = chart_width / len(days)
        bar_width = min(bar_slot * 0.6, 80)
        baseline = height - margin_bottom

        self.chart_canvas.create_line(
            margin_left,
            baseline,
            width - margin_right,
            baseline,
            fill="#2e3148",
        )

        sorted_domains = sorted(all_domains)
        for domain in sorted_domains:
            self._get_color_for_domain(domain)

        for index, day in enumerate(days):
            counts = day_counts.get(day, {})
            total_for_day = total_per_day[index]
            x_center = margin_left + bar_slot * index + bar_slot / 2
            x0 = x_center - bar_width / 2
            x1 = x_center + bar_width / 2
            cumulative_height = 0.0

            for domain in sorted_domains:
                count = counts.get(domain, 0)
                if count <= 0:
                    continue
                height_ratio = count / max_total
                bar_height = height_ratio * chart_height
                y1 = baseline - cumulative_height
                y0 = y1 - bar_height
                color = self._get_color_for_domain(domain)
                self.chart_canvas.create_rectangle(x0, y0, x1, y1, fill=color, outline="")
                cumulative_height += bar_height

            if total_for_day > 0:
                self.chart_canvas.create_text(
                    x_center,
                    baseline - cumulative_height - 12,
                    text=str(total_for_day),
                    fill="#f4f6fb",
                    font=("Segoe UI", 10, "bold"),
                )

            label = day.strftime("%b %d")
            self.chart_canvas.create_text(
                x_center,
                height - margin_bottom / 2,
                text=label,
                fill="#cbd5f5",
                font=("Segoe UI", 9),
            )

        self._update_legend(sorted_domains)

    def _draw_chart_message(self, message: str) -> None:
        if self.chart_canvas is None:
            return
        width = max(self.chart_canvas.winfo_width(), 1)
        height = max(self.chart_canvas.winfo_height(), 1)
        self._update_legend([])
        self.chart_canvas.create_text(
            width / 2,
            height / 2,
            text=message,
            fill="#cbd5f5",
            font=("Segoe UI", 12),
        )

    def _update_legend(self, domains: list[str]) -> None:
        for child in self.legend_frame.winfo_children():
            child.destroy()

        if not domains:
            return

        for domain in domains:
            color = self._get_color_for_domain(domain)
            item = ttk.Frame(self.legend_frame, style="Card.TFrame")
            item.pack(side="left", padx=(0, 18))

            swatch = tk.Label(item, background=color, width=2, height=1)
            swatch.pack(side="left", padx=(0, 6))

            label = ttk.Label(item, text=domain, style="TLabel")
            label.pack(side="left")

    def _get_color_for_domain(self, domain: str) -> str:
        if domain not in self.domain_colors:
            color = self._color_palette[self._color_index % len(self._color_palette)]
            self.domain_colors[domain] = color
            self._color_index += 1
        return self.domain_colors[domain]

    def _on_chart_resized(self, _: tk.Event) -> None:
        self._refresh_chart()

    def _show_empty_state(self, message: str) -> None:
        self.empty_state.configure(text=message)
        self.empty_state.place(relx=0.5, rely=0.5, anchor="center")

    def _hide_empty_state(self) -> None:
        self.empty_state.place_forget()

    def _check_csv_updates(self) -> None:
        if self.csv_path and os.path.exists(self.csv_path):
            try:
                current_mtime = os.path.getmtime(self.csv_path)
            except OSError:
                current_mtime = None
            if current_mtime and current_mtime != self.csv_mtime:
                self.csv_mtime = current_mtime
                self.load_csv_data()
        self.root.after(REFRESH_INTERVAL_MS, self._check_csv_updates)

    # ------------------------------------------------------------------
    # Logging utilities
    # ------------------------------------------------------------------
    def _queue_message(self, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self.log_queue.put(f"[{timestamp}] {message}")

    def _process_log_queue(self) -> None:
        while not self.log_queue.empty():
            message = self.log_queue.get_nowait()
            self.log_text.configure(state="normal")
            self.log_text.insert("end", message + "\n")
            self.log_text.configure(state="disabled")
            self.log_text.yview_moveto(1.0)
        self.root.after(LOG_POLL_INTERVAL_MS, self._process_log_queue)

    # ------------------------------------------------------------------
    # Shutdown handling
    # ------------------------------------------------------------------
    def _on_close(self) -> None:
        if self.monitoring:
            if not messagebox.askyesno("Download Insights", "Monitoring is running. Do you want to stop and exit?"):
                return
            self.stop_monitoring()
        if self.canvas is not None:
            self.canvas.unbind_all("<MouseWheel>")
            self.canvas.unbind_all("<Button-4>")
            self.canvas.unbind_all("<Button-5>")
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    app = DownloadInsightsApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
