import os
from watchdog.observers import Observer
from file_handler import FileHandler, DOWNLOAD_FOLDER
import time

observer = None

def start_monitoring(icon=None, item=None):
    global observer
    if not os.path.exists(DOWNLOAD_FOLDER):
        print(f"Error: The directory {DOWNLOAD_FOLDER} does not exist.")
        return
    event_handler = FileHandler()
    observer = Observer()
    observer.schedule(event_handler, DOWNLOAD_FOLDER, recursive=False)
    print(f"Monitoring {DOWNLOAD_FOLDER} for .tmp files and renames...")
    observer.start()

def main():
    global observer
    observer = None
    start_monitoring()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
    
if __name__ == "__main__":
    main()
