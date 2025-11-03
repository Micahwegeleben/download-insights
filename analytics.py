import csv
import os
import shutil
import sqlite3
from datetime import datetime

from paths import get_analytics_dir

LEGACY_INSIGHTS_FOLDER = "downloadinsights"
DATABASE_FILE_NAME = "downloadInsightsAnalytics.db"
LEGACY_CSV_FILE_NAME = "downloadInsightsAnalytics.csv"

EXPECTED_HEADER = [
    "Timestamp",
    "Event",
    "File Path",
    "Domain",
    "File Size",
    "File Type",
    "Download URL",
    "Is Duplicate",
]

_CREATE_TABLE_STATEMENT = """
CREATE TABLE IF NOT EXISTS insights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    event TEXT NOT NULL,
    file_path TEXT NOT NULL,
    domain TEXT NOT NULL,
    file_size INTEGER,
    file_type TEXT,
    download_url TEXT,
    is_duplicate INTEGER NOT NULL DEFAULT 0
)
"""


def _database_path(download_folder: str) -> str:
    return os.path.join(get_analytics_dir(download_folder), DATABASE_FILE_NAME)


def _ensure_directory(download_folder: str) -> str:
    insights_folder_path = get_analytics_dir(download_folder)
    _migrate_legacy_storage(download_folder, insights_folder_path)
    return insights_folder_path


def _legacy_insights_dir(download_folder: str) -> str:
    return os.path.join(os.path.abspath(os.path.expanduser(download_folder)), LEGACY_INSIGHTS_FOLDER)


def _migrate_legacy_storage(download_folder: str, destination: str) -> None:
    legacy_dir = _legacy_insights_dir(download_folder)
    if not os.path.isdir(legacy_dir):
        return

    os.makedirs(destination, exist_ok=True)

    legacy_db = os.path.join(legacy_dir, DATABASE_FILE_NAME)
    new_db = os.path.join(destination, DATABASE_FILE_NAME)
    if os.path.isfile(legacy_db) and not os.path.exists(new_db):
        try:
            shutil.copy2(legacy_db, new_db)
        except OSError:
            pass

    legacy_csv = os.path.join(legacy_dir, LEGACY_CSV_FILE_NAME)
    new_csv = os.path.join(destination, LEGACY_CSV_FILE_NAME)
    if os.path.isfile(legacy_csv) and not os.path.exists(new_csv):
        try:
            shutil.copy2(legacy_csv, new_csv)
        except OSError:
            pass


def initialize_log_file(download_folder: str) -> None:
    insights_folder_path = _ensure_directory(download_folder)
    database_path = _database_path(download_folder)

    with sqlite3.connect(database_path, timeout=5) as connection:
        connection.execute(_CREATE_TABLE_STATEMENT)
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_insights_timestamp ON insights(timestamp)"
        )
        connection.commit()

    _migrate_legacy_csv(insights_folder_path, database_path)


def _migrate_legacy_csv(insights_folder_path: str, database_path: str) -> None:
    legacy_csv = os.path.join(insights_folder_path, LEGACY_CSV_FILE_NAME)
    if not os.path.exists(legacy_csv):
        return

    rows: list[list[str]] = []
    try:
        with sqlite3.connect(database_path, timeout=5) as connection:
            cursor = connection.execute("SELECT COUNT(*) FROM insights")
            existing = cursor.fetchone()[0]
            if existing:
                return

            with open(legacy_csv, newline="", encoding="utf-8") as csv_file:
                reader = csv.reader(csv_file)
                rows = list(reader)
    except (OSError, sqlite3.DatabaseError):
        return

    if not rows:
        return

    header, *data_rows = rows
    header_map = {name: index for index, name in enumerate(header)}

    with sqlite3.connect(database_path, timeout=5) as connection:
        for row in data_rows:
            record = {
                column: row[header_map[column]] if column in header_map and header_map[column] < len(row) else ""
                for column in EXPECTED_HEADER
            }
            _insert_record(connection, record)
        connection.commit()


def log_event(
    event: str,
    file_path: str,
    domain: str,
    download_folder: str,
    download_url: str = "N/A",
    is_duplicate: bool = False,
) -> None:
    _ensure_directory(download_folder)
    database_path = _database_path(download_folder)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    file_size = os.path.getsize(file_path) if os.path.exists(file_path) else None
    file_type = os.path.splitext(file_path)[1]

    with sqlite3.connect(database_path, timeout=5) as connection:
        _insert_record(
            connection,
            {
                "Timestamp": timestamp,
                "Event": event,
                "File Path": file_path,
                "Domain": domain,
                "File Size": file_size if file_size is not None else "",
                "File Type": file_type,
                "Download URL": download_url,
                "Is Duplicate": "Yes" if is_duplicate else "No",
            },
        )
        connection.commit()


def _insert_record(connection: sqlite3.Connection, record: dict) -> None:
    connection.execute(
        """
        INSERT INTO insights (
            timestamp,
            event,
            file_path,
            domain,
            file_size,
            file_type,
            download_url,
            is_duplicate
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.get("Timestamp", ""),
            record.get("Event", ""),
            record.get("File Path", ""),
            record.get("Domain", ""),
            _to_int_or_none(record.get("File Size")),
            record.get("File Type", ""),
            record.get("Download URL", ""),
            1 if str(record.get("Is Duplicate", "No")).lower() in {"yes", "true", "1"} else 0,
        ),
    )


def _to_int_or_none(value: object) -> int | None:
    try:
        if value in ("", None):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def fetch_insights(download_folder: str) -> list[dict[str, str]]:
    _ensure_directory(download_folder)
    database_path = _database_path(download_folder)
    if not os.path.exists(database_path):
        return []

    with sqlite3.connect(database_path, timeout=5) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT timestamp, event, file_path, domain, file_size, file_type, download_url, is_duplicate
            FROM insights
            ORDER BY datetime(timestamp) ASC, id ASC
            """
        ).fetchall()

    insights: list[dict[str, str]] = []
    for row in rows:
        file_size = row["file_size"]
        insights.append(
            {
                "Timestamp": row["timestamp"],
                "Event": row["event"],
                "File Path": row["file_path"],
                "Domain": row["domain"],
                "File Size": str(file_size) if file_size is not None else "",
                "File Type": row["file_type"] or "",
                "Download URL": row["download_url"] or "",
                "Is Duplicate": "Yes" if row["is_duplicate"] else "No",
            }
        )
    return insights


def get_latest_entry_id(download_folder: str) -> int:
    _ensure_directory(download_folder)
    database_path = _database_path(download_folder)
    if not os.path.exists(database_path):
        return 0

    with sqlite3.connect(database_path, timeout=5) as connection:
        cursor = connection.execute("SELECT IFNULL(MAX(id), 0) FROM insights")
        result = cursor.fetchone()
        return int(result[0]) if result and result[0] is not None else 0


def export_insights_to_csv(download_folder: str, destination_path: str) -> None:
    insights = fetch_insights(download_folder)
    with open(destination_path, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(EXPECTED_HEADER)
        for record in insights:
            writer.writerow([record.get(column, "") for column in EXPECTED_HEADER])


def get_database_path(download_folder: str) -> str:
    _ensure_directory(download_folder)
    return _database_path(download_folder)
