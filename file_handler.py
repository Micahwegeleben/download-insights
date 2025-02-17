import os
import time
import shutil as su
import sqlite3 as s3
from watchdog.events import FileSystemEventHandler
from urllib.parse import urlparse

EdgeDB = r"C:\Users\micah\AppData\Local\Microsoft\Edge\User Data\Default\History"
TempLoc = r"C:\Users\micah\AppData\Local\Microsoft\Edge\User Data\Default\History_temp"
DOWNLOAD_FOLDER = r"F:\Downloads"

def get_website_folder(domain):
        target_folder = os.path.join(DOWNLOAD_FOLDER, domain)
        os.makedirs(target_folder, exist_ok=True)
        return target_folder
    
class FileHandler(FileSystemEventHandler):
    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith(".tmp"):
            print(f"Detected new .tmp file: {event.src_path}")

    def on_moved(self, event):
        if not event.is_directory:
            print(f"File renamed from {event.src_path} to {event.dest_path}")
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
                        domain = self.get_file_domain(file_path)
                        self.move_to_website_folder(file_path, domain)
                    return
        except FileNotFoundError:
            print(f"File {file_path} was not found.")
        except Exception as e:
            print(f"Error processing {file_path}: {e}")
            
    def get_file_domain(self, file_path):
        retries = 5
        delay = 1  # in sec
        for attempt in range(retries):
            try:
                temp_db = self.copy_edge_db_to_temp()
                domain = self.query_domain_from_db(temp_db, file_path)
                if domain:
                    return domain
            except s3.OperationalError as e:
                if "database is locked" in str(e):
                    print(f"Database is locked, retrying in {delay} seconds...")
                    time.sleep(delay)
                    delay *= 2  # Exponential backoff
                else:
                    print(f"Error fetching domain from Edge: {e}")
                    return "unknown_domain"
            except Exception as e:
                print(f"Error fetching domain from Edge: {e}")
                return "unknown_domain"
            finally:
                if os.path.exists(temp_db):
                    os.remove(temp_db)  # Clean up the temporary database file
        print("Failed to fetch domain after multiple attempts.")
        return "unknown_domain"

    def copy_edge_db_to_temp(self):
        edge_downloads_db = os.path.expanduser(EdgeDB)
        temp_db = os.path.expanduser(TempLoc)
        su.copy2(edge_downloads_db, temp_db)
        return temp_db

    def query_domain_from_db(self, temp_db, file_path):
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
                    domain = self.extract_domain_from_url(url)
                    conn.close()
                    return domain
        conn.close()
        print(f"No matching entry found for file path: {file_path}")
        return "unknown_domain"

    def extract_domain_from_url(self, url):
        parsed_url = urlparse(url)
        return parsed_url.hostname.replace('www.', '').split('.')[0]

    def move_to_website_folder(self, file_path, domain):
        try:
            target_folder = get_website_folder(domain)
            su.move(file_path, os.path.join(target_folder, os.path.basename(file_path)))
            print(f"Moved {file_path} to {target_folder}")
        except Exception as e:
            print(f"Failed to move {file_path}: {e}")
            
    
