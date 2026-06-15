from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
LOG_DIR = ROOT_DIR / "logs"
SQL_DIR = ROOT_DIR / "sql"
DB_PATH = DATA_DIR / "bds_live.sqlite3"
HREFS_PATH = ROOT_DIR / "hrefs.txt"
CSV_PATH = ROOT_DIR / "data_bds.csv"
DEFAULT_SOURCE_SITE = "batdongsan.com.vn"
DEFAULT_SEARCH_CATEGORY = "ban-dat-ha-noi"
DEFAULT_DISCOVER_URL = "https://batdongsan.com.vn/ban-dat-ha-noi?cIds=41"
CHROME_BINARY = "/opt/google/chrome/google-chrome"
