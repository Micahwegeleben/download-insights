import os
import csv
from datetime import datetime

LOG_FILE_NAME = "downloadInsightsAnalytics.csv"
INSIGHTS_FOLDER = "downloadinsights"


def initialize_log_file(download_folder):
    insights_folder_path = os.path.join(download_folder, INSIGHTS_FOLDER)
    os.makedirs(insights_folder_path, exist_ok=True)  # create directory if it doesn't exist
    LOG_FILE = os.path.join(insights_folder_path, LOG_FILE_NAME)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["Timestamp", "Event", "File Path", "Domain", "File Size", "File Type", "Download URL"])


def log_event(event, file_path, domain, download_folder, download_url="N/A"):
    insights_folder_path = os.path.join(download_folder, INSIGHTS_FOLDER)
    LOG_FILE = os.path.join(insights_folder_path, LOG_FILE_NAME)
    file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 'N/A'
    file_type = os.path.splitext(file_path)[1]  # Extract file extension
    with open(LOG_FILE, mode='a', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), event, file_path, domain, file_size, file_type, download_url])