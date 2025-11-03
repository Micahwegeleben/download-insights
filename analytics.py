import os
import csv
from datetime import datetime

LOG_FILE_NAME = "downloadInsightsAnalytics.csv"
INSIGHTS_FOLDER = "downloadinsights"

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


def initialize_log_file(download_folder):
    insights_folder_path = os.path.join(download_folder, INSIGHTS_FOLDER)
    os.makedirs(insights_folder_path, exist_ok=True)  # create directory if it doesn't exist
    LOG_FILE = os.path.join(insights_folder_path, LOG_FILE_NAME)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, mode="w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(EXPECTED_HEADER)
        return

    with open(LOG_FILE, newline="", encoding="utf-8") as file:
        reader = csv.reader(file)
        rows = list(reader)

    if not rows:
        with open(LOG_FILE, mode="w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(EXPECTED_HEADER)
        return

    header = rows[0]
    if header == EXPECTED_HEADER:
        return

    header_map = {column: index for index, column in enumerate(header)}
    rewritten_rows = [EXPECTED_HEADER]
    for row in rows[1:]:
        new_row = []
        for column in EXPECTED_HEADER:
            if column == "Is Duplicate" and column not in header_map:
                new_row.append("No")
            else:
                index = header_map.get(column)
                value = row[index] if index is not None and index < len(row) else ""
                new_row.append(value)
        rewritten_rows.append(new_row)

    with open(LOG_FILE, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerows(rewritten_rows)


def log_event(event, file_path, domain, download_folder, download_url="N/A", is_duplicate=False):
    insights_folder_path = os.path.join(download_folder, INSIGHTS_FOLDER)
    LOG_FILE = os.path.join(insights_folder_path, LOG_FILE_NAME)
    file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 'N/A'
    file_type = os.path.splitext(file_path)[1]  # Extract file extension
    with open(LOG_FILE, mode='a', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            event,
            file_path,
            domain,
            file_size,
            file_type,
            download_url,
            "Yes" if is_duplicate else "No",
        ])
