import os
import time
import uuid
import warnings
from pathlib import Path
from dotenv import load_dotenv
from rich.console import Console

warnings.filterwarnings("ignore")

# Get the project root directory (parent of src/)
PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / "data" / ".env")

console = Console()

# Z.ai X-Signature constants
ZAI_SALT_KEY = "key-@@@@)))()((9))-xxxx&&&%%%%%"
ZAI_BUCKET_WINDOW = 300000  # 5 minutes in ms

# Browser paths (search order)
BROWSER_PATHS = [
    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
]


def find_browser():
    """Find a valid browser executable (Brave first, then Chrome)."""
    import os

    for path in BROWSER_PATHS:
        expanded = os.path.expandvars(path)
        if os.path.isfile(expanded):
            return expanded
    return None


class Config:
    ZAI_EMAIL = os.getenv("ZAI_EMAIL")
    ZAI_PASSWORD = os.getenv("ZAI_PASSWORD")

    HEADLESS = False
    AUTH_WAIT_TIME = 10

    COOKIES_FILE = str(PROJECT_ROOT / "data" / "zai_cookies.json")
    TOKEN_FILE = str(PROJECT_ROOT / "data" / "auth_token.txt")
    LAST_LOGIN_FILE = str(PROJECT_ROOT / "data" / "last_login.txt")

    SESSION_TIMEOUT = 3600

    BASE_URL = "https://chat.z.ai"
    API_V1 = f"{BASE_URL}/api/v1"
    API_V2 = f"{BASE_URL}/api/v2"

    BASE_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": BASE_URL,
    }

    MODEL = "glm-4.7"
    FE_VERSION = "prod-fe-1.1.7"

    @staticmethod
    def print_status(message, style="white"):
        console.print(f"[{style}][GLM][/{style}] {message}")

    @staticmethod
    def generate_request_id():
        return uuid.uuid4().hex

    @staticmethod
    def needs_reauth():
        try:
            with open(Config.LAST_LOGIN_FILE, "r") as f:
                last_login = float(f.read().strip())
            return (time.time() - last_login) > Config.SESSION_TIMEOUT
        except (FileNotFoundError, ValueError):
            return True

    @staticmethod
    def update_login_time():
        with open(Config.LAST_LOGIN_FILE, "w") as f:
            f.write(str(time.time()))
