import csv
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from watchdog.observers import Observer

from analytics import INSIGHTS_FOLDER, LOG_FILE_NAME, initialize_log_file
from fileHandler import FileHandler

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
        content = ttk.Frame(self.root, padding=24, style="TFrame")
        content.pack(fill="both", expand=True)

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

        insights_card = ttk.Frame(content, style="Card.TFrame", padding=24)
        insights_card.pack(fill="both", expand=True, pady=(24, 0))

        insights_header = ttk.Label(insights_card, text="Download insights", style="Heading.TLabel")
        insights_header.pack(anchor="w")

        insights_subheader = ttk.Label(
            insights_card,
            text="Review captured download events without leaving the application.",
            style="Subheading.TLabel",
        )
        insights_subheader.pack(anchor="w", pady=(4, 12))

        tree_frame = ttk.Frame(insights_card, style="Card.TFrame")
        tree_frame.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(tree_frame, columns=self.tree_columns, show="headings", style="Insights.Treeview")
        self.tree.pack(side="left", fill="both", expand=True)

        y_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        y_scroll.pack(side="right", fill="y")
        x_scroll = ttk.Scrollbar(insights_card, orient="horizontal", command=self.tree.xview)
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

    # ------------------------------------------------------------------
    # Monitoring controls
    # ------------------------------------------------------------------
    def _browse_for_folder(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.path_var.get() or None, title="Select download folder")
        if selected:
            self.path_var.set(selected)
            self._update_csv_path(selected)
            self._queue_message(f"Download folder set to {selected}")

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
            self._show_empty_state("No insights yet. Start monitoring to populate this view.")
            return

        try:
            with open(self.csv_path, newline="", encoding="utf-8") as csv_file:
                reader = csv.reader(csv_file)
                rows = list(reader)
        except OSError as exc:
            self._queue_message(f"Unable to read insights file: {exc}")
            self.csv_mtime = None
            self._show_empty_state("Unable to read insights file.")
            return

        if not rows:
            self.csv_mtime = None
            self._show_empty_state("The insights file is empty.")
            return

        header, *data_rows = rows
        self._setup_tree_columns(header)

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
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    app = DownloadInsightsApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
