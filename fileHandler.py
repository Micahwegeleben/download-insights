import json
import os
import tempfile
import time
import shutil as su
import sqlite3 as s3
from typing import Iterable

from watchdog.events import FileSystemEventHandler
from urllib.parse import urlparse

from analytics import log_event

_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".download_insights")
_CONFIG_FILE = os.path.join(_CONFIG_DIR, "config.json")
_EDGE_HISTORY_KEY = "edge_history_path"


def _load_settings() -> dict:
    try:
        with open(_CONFIG_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            if isinstance(data, dict):
                return data
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        return {}
    return {}


def _save_settings(settings: dict) -> None:
    os.makedirs(_CONFIG_DIR, exist_ok=True)
    with open(_CONFIG_FILE, "w", encoding="utf-8") as handle:
        json.dump(settings, handle, indent=2)


def get_saved_edge_history_path() -> str | None:
    settings = _load_settings()
    path = settings.get(_EDGE_HISTORY_KEY)
    if not path:
        return None
    expanded = os.path.expanduser(path)
    if os.path.isfile(expanded):
        return expanded
    return None


def set_saved_edge_history_path(path: str | None) -> None:
    settings = _load_settings()
    if path:
        settings[_EDGE_HISTORY_KEY] = os.path.abspath(os.path.expanduser(path))
    else:
        settings.pop(_EDGE_HISTORY_KEY, None)
    _save_settings(settings)


def _profiles_from_local_state(local_state_path: str) -> list[str]:
    profiles: list[str] = []
    try:
        with open(local_state_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return profiles

    profile_settings = data.get("profile")
    if not isinstance(profile_settings, dict):
        return profiles

    for key in ("last_used", "default_profile"):
        value = profile_settings.get(key)
        if isinstance(value, str) and value:
            profiles.append(value)

    info_cache = profile_settings.get("info_cache")
    if isinstance(info_cache, dict):
        profiles.extend(info_cache.keys())

    return profiles


def _candidate_user_data_dirs() -> Iterable[str]:
    candidates: list[str] = []

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(os.path.join(local_app_data, "Microsoft", "Edge", "User Data"))

    program_data = os.environ.get("PROGRAMDATA")
    if program_data:
        candidates.append(os.path.join(program_data, "Microsoft", "Edge", "User Data"))

    home = os.path.expanduser("~")
    candidates.extend(
        [
            os.path.join(home, "AppData", "Local", "Microsoft", "Edge", "User Data"),
            os.path.join(home, ".config", "microsoft-edge"),
            os.path.join(home, "Library", "Application Support", "Microsoft Edge"),
        ]
    )

    seen: set[str] = set()
    for candidate in candidates:
        normalized = os.path.normpath(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        if os.path.isdir(normalized):
            yield normalized


def auto_detect_edge_history_path() -> str | None:
    for user_data_dir in _candidate_user_data_dirs():
        local_state_path = os.path.join(user_data_dir, "Local State")
        profiles = _profiles_from_local_state(local_state_path)

        # Always consider Default and profile directories that follow the Profile X naming convention
        try:
            entries = [entry for entry in os.listdir(user_data_dir) if os.path.isdir(os.path.join(user_data_dir, entry))]
        except OSError:
            entries = []

        for entry in entries:
            lowered = entry.lower()
            if lowered == "default" or lowered.startswith("profile"):
                profiles.append(entry)

        profiles.append("Default")

        seen: set[str] = set()
        for profile in profiles:
            if not profile or profile in seen:
                continue
            seen.add(profile)
            history_path = os.path.join(user_data_dir, profile, "History")
            if os.path.isfile(history_path):
                return history_path
    return None


def get_edge_history_path() -> str:
    saved = get_saved_edge_history_path()
    if saved and os.path.isfile(saved):
        return saved
    if saved and not os.path.isfile(saved):
        set_saved_edge_history_path(None)

    detected = auto_detect_edge_history_path()
    if detected:
        return detected

    raise FileNotFoundError("Unable to locate the Microsoft Edge history database.")

def getWebsiteFolder(domain, download_folder): #i now pass in download folder
    target_folder = os.path.join(download_folder, domain)
    os.makedirs(target_folder, exist_ok=True)
    return target_folder
    
class FileHandler(FileSystemEventHandler):
    def __init__(self, download_folder, message_callback=None):
        super().__init__()
        self.download_folder = download_folder
        self.message_callback = message_callback

    def _emit(self, message):
        if self.message_callback:
            self.message_callback(message)
        else:
            print(message)

    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith(".tmp"):
            self._emit(f"Detected new .tmp file: {event.src_path}")
            # log_event("Created", event.src_path, "N/A", self.download_folder)

    def on_moved(self, event):
        if not event.is_directory:
            self._emit(f"File renamed from {event.src_path} to {event.dest_path}")
            self.handle_renamed_file(event.dest_path)

    def handle_renamed_file(self, file_path):
        try:
            while True:
                if not os.path.exists(file_path):
                    return
                initial_size = os.path.getsize(file_path)
                time.sleep(2)
                current_size = os.path.getsize(file_path)

                if initial_size == current_size:
                    if not file_path.endswith((".tmp", ".crdownload")):
                        website = self.get_file_domain(file_path)
                        domain = self.extract_domain_from_url(website)
                        log_event("Moved", file_path, domain, self.download_folder, website) #pass in download
                        self.move_to_website_folder(file_path, domain)
                    return
        except FileNotFoundError:
            self._emit(f"File {file_path} not found")
        except Exception as e:
            self._emit(f"Error with {file_path}: {e}")
    
    def get_file_domain(self, file_path):
        retries = 5
        delay = 1  #seconds
        for attempt in range(retries):
            temp_db = None
            try:
                temp_db = self.copy_edge_db_to_temp()
                domain = self.query_url_from_db(temp_db, file_path)
                if domain:
                    return domain
            except FileNotFoundError:
                return "unknown_domain"
            except s3.OperationalError as e:
                if "database locked" in str(e):
                    self._emit(f"Database is locked, retrying in {delay} seconds")
                    time.sleep(delay)
                    delay *= 2
                else:
                    self._emit(f"Error getting domain from Edge: {e}")
                    return "unknown_domain"
            except Exception as e:
                self._emit(f"Error getting domain from Edge: {e}")
                return "unknown_domain"
            finally:
                if temp_db and os.path.exists(temp_db):
                    os.remove(temp_db)  #clean up the temporary database file
        self._emit("Failed to get domain from Edge")
        return "unknown_domain"

    def copy_edge_db_to_temp(self):
        try:
            edge_downloads_db = get_edge_history_path()
        except FileNotFoundError:
            self._emit(
                "Edge history database not found. Configure the path from the Download Insights app settings."
            )
            raise

        fd, temp_db = tempfile.mkstemp(prefix="download_insights_edge_", suffix=".db")
        os.close(fd)

        try:
            su.copy2(edge_downloads_db, temp_db)
        except FileNotFoundError:
            if os.path.exists(temp_db):
                os.remove(temp_db)
            self._emit(
                f"Edge history database is missing at {edge_downloads_db}. Update the path in settings to continue."
            )
            raise
        except Exception:
            if os.path.exists(temp_db):
                os.remove(temp_db)
            raise

        return temp_db

    def query_url_from_db(self, temp_db, file_path):
        with s3.connect(temp_db) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA busy_timeout = 3000")
            cursor.execute(
                """
                SELECT site_url, tab_url, tab_referrer_url
                FROM downloads
                WHERE target_path = ?
                """,
                (file_path,),
            )
            result = cursor.fetchone()
            if result:
                for url in result:
                    if url:
                        return url
                        # domain = self.extract_domain_from_url(url)
                        # conn.close()
                        # return domain
        self._emit(f"No entry found for: {file_path}")
        return "unknown_domain"

    def extract_domain_from_url(self, url):
        parsed_url = urlparse(url)
        if not parsed_url.hostname:
            return "unknown_domain"
        return parsed_url.hostname.replace('www.', '').split('.')[0]

    def move_to_website_folder(self, file_path, domain):
        try:
            target_folder = getWebsiteFolder(domain, self.download_folder) #requires download folder
            su.move(file_path, os.path.join(target_folder, os.path.basename(file_path)))
            self._emit(f"Moved {file_path} to {target_folder}")
        except Exception as e:
            self._emit(f"Failed to move {file_path}: {e}")
