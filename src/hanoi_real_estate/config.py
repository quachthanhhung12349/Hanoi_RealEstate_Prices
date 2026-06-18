from pathlib import Path
import os
import sys

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
GIS_DATA_DIR = DATA_DIR / "gis"
LOG_DIR = ROOT_DIR / "logs"
SQL_DIR = ROOT_DIR / "sql"
LIVE_DB_PATH = DATA_DIR / "bds_live.sqlite3"
DEMO_DB_PATH = DATA_DIR / "demo.sqlite3"
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
DB_BACKEND = "postgresql" if DATABASE_URL else "sqlite"
DB_PATH = Path(os.environ.get("HANOI_RE_DB_PATH", LIVE_DB_PATH if LIVE_DB_PATH.exists() else DEMO_DB_PATH))
HREFS_PATH = ROOT_DIR / "hrefs.txt"
CSV_PATH = ROOT_DIR / "data_bds.csv"
DEFAULT_SOURCE_SITE = "batdongsan.com.vn"
DEFAULT_SEARCH_CATEGORY = "ban-dat-ha-noi"
DEFAULT_DISCOVER_URL = "https://batdongsan.com.vn/ban-dat-ha-noi?cIds=41"
DAILY_DISCOVER_URL = os.environ.get("DAILY_DISCOVER_URL", DEFAULT_DISCOVER_URL)
FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "").strip()
FIRECRAWL_BASE_URL = os.environ.get("FIRECRAWL_BASE_URL", "https://api.firecrawl.dev").rstrip("/")
FIRECRAWL_DAILY_MAX_NEW = int(os.environ.get("FIRECRAWL_DAILY_MAX_NEW", "20"))
FIRECRAWL_DAILY_MAX_PAGES = int(os.environ.get("FIRECRAWL_DAILY_MAX_PAGES", "2"))


CHROME_VERSION = int(os.environ.get("CHROME_VERSION", "149"))

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
