from pathlib import Path
import sys
import os

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
GIS_DATA_DIR = DATA_DIR / "gis"
LOG_DIR = ROOT_DIR / "logs"
SQL_DIR = ROOT_DIR / "sql"
LIVE_DB_PATH = DATA_DIR / "bds_live.sqlite3"
DEMO_DB_PATH = DATA_DIR / "demo.sqlite3"
DB_PATH = Path(os.environ.get("HANOI_RE_DB_PATH", LIVE_DB_PATH if LIVE_DB_PATH.exists() else DEMO_DB_PATH))
HREFS_PATH = ROOT_DIR / "hrefs.txt"
CSV_PATH = ROOT_DIR / "data_bds.csv"
DEFAULT_SOURCE_SITE = "batdongsan.com.vn"
DEFAULT_SEARCH_CATEGORY = "ban-dat-ha-noi"
DEFAULT_DISCOVER_URL = "https://batdongsan.com.vn/ban-dat-ha-noi?cIds=41"


# Define paths based on the operating system
if sys.platform.startswith('win'):
    # Common Windows paths for Chrome
    CHROME_BINARY = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
elif sys.platform == 'darwin':
    # macOS standard path
    CHROME_BINARY = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
else:
    # Default to Linux path (or your specific /opt/ location)
    CHROME_BINARY = "/opt/google/chrome/google-chrome"

# Optional: Add a check to ensure the file actually exists
if not os.path.exists(CHROME_BINARY):
    print(f"Warning: Chrome binary not found at {CHROME_BINARY}. Please verify the installation path.")
