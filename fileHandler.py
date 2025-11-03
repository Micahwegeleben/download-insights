import os
import time
import shutil as su
import sqlite3 as s3
from watchdog.events import FileSystemEventHandler
from urllib.parse import urlparse

from analytics import log_event

EdgeDB = r"C:\Users\micah\AppData\Local\Microsoft\Edge\User Data\Default\History"
TempLoc = r"C:\Users\micah\AppData\Local\Microsoft\Edge\User Data\Default\History_temp"

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
            try:
                temp_db = self.copy_edge_db_to_temp()
                domain = self.query_url_from_db(temp_db, file_path)
                if domain:
                    return domain
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
                if os.path.exists(temp_db):
                    os.remove(temp_db)  #clean up the temporary database file
        self._emit("Failed to get domain from Edge")
        return "unknown_domain"

    def copy_edge_db_to_temp(self):
        edge_downloads_db = os.path.expanduser(EdgeDB)
        temp_db = os.path.expanduser(TempLoc)
        try:
            su.copy2(edge_downloads_db, temp_db)
        except FileNotFoundError:
            self._emit("Edge history database not found. Unable to resolve download domains.")
            raise
        return temp_db

    def query_url_from_db(self, temp_db, file_path):
        conn = s3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("PRAGMA busy_timeout = 3000")
        cursor.execute("""
            SELECT site_url, tab_url, tab_referrer_url 
            FROM downloads 
            WHERE target_path = ?
        """, (file_path,))
        result = cursor.fetchone()
        if result:
            for url in result:
                if url:
                    return url
                    # domain = self.extract_domain_from_url(url)
                    # conn.close()
                    # return domain
        conn.close()
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
