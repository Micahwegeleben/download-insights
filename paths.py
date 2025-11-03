"""Centralized path helpers for Download Insights storage."""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

_APP_DOCUMENTS_SUBDIR = "Download Insights"
_ANALYTICS_SUBDIR = "analytics"
_DOMAIN_DOWNLOADS_SUBDIR = "DownloadInsights"


def _documents_root() -> str:
    """Return the user's Documents directory, creating it if necessary."""
    home = Path.home()
    documents = home / "Documents"
    try:
        documents.mkdir(parents=True, exist_ok=True)
    except OSError:
        # If we fail to create the Documents folder, fall back to the home directory.
        return str(home)
    return str(documents)


def get_app_documents_dir() -> str:
    """Return the application data directory under the user's Documents folder."""
    documents_root = _documents_root()
    app_dir = os.path.join(documents_root, _APP_DOCUMENTS_SUBDIR)
    os.makedirs(app_dir, exist_ok=True)
    return app_dir


def get_config_file_path() -> str:
    """Return the fully qualified path to the configuration file."""
    return os.path.join(get_app_documents_dir(), "config.json")


def _normalized_identifier(folder: str) -> str:
    """Generate a filesystem-safe identifier for a monitored folder."""
    normalized = os.path.abspath(os.path.expanduser(folder))
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:10]
    tail = os.path.basename(normalized.rstrip(os.sep)) or "downloads"
    safe_tail = re.sub(r"[^A-Za-z0-9._-]+", "_", tail)
    return f"{safe_tail}_{digest}"


def get_analytics_dir(download_folder: str) -> str:
    """Return the analytics storage directory for the given download folder."""
    app_dir = get_app_documents_dir()
    analytics_root = os.path.join(app_dir, _ANALYTICS_SUBDIR)
    os.makedirs(analytics_root, exist_ok=True)
    identifier = _normalized_identifier(download_folder)
    target = os.path.join(analytics_root, identifier)
    os.makedirs(target, exist_ok=True)
    return target


def get_domain_root(download_folder: str) -> str:
    """Return the root directory for domain-specific folders within Downloads."""
    normalized = os.path.abspath(os.path.expanduser(download_folder))
    target = os.path.join(normalized, _DOMAIN_DOWNLOADS_SUBDIR)
    os.makedirs(target, exist_ok=True)
    return target

