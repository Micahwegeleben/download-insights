import os
from watchdog.observers import Observer
from analytics import initialize_log_file
from fileHandler import FileHandler
import time

observer = None
DOWNLOAD_FOLDER = r"F:\Downloads"

def startMonitoring(download_folder, icon=None, item=None):
    global observer
    if not os.path.exists(download_folder):
        print(f"Error: The directory {download_folder} does not exist.")
        return
    event_handler = FileHandler(download_folder)
    observer = Observer()
    observer.schedule(event_handler, download_folder, recursive=False)
    print(f"Monitoring {download_folder} for .tmp files and renames...")
    observer.start()


def main():
    global observer
    observer = None
    initialize_log_file(DOWNLOAD_FOLDER) #have to pass download folder into these function calls
    startMonitoring(DOWNLOAD_FOLDER) 
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
    
if __name__ == "__main__":
    main()