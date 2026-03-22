import os
from dotenv import load_dotenv

load_dotenv()

COINSPOT_API_KEY = os.getenv("COINSPOT_API_KEY", "")
COINSPOT_API_SECRET = os.getenv("COINSPOT_API_SECRET", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
TRADING_MODE = os.getenv("TRADING_MODE", "paper")  # "paper" or "live"
PAPER_BALANCE = float(os.getenv("PAPER_BALANCE", "1000"))

BOT_INTERVAL_SECONDS = int(os.getenv("BOT_INTERVAL_SECONDS", "60"))
STOP_LOSS_PCT = 0.04    # 4% hard-coded stop loss
TAKE_PROFIT_PCT = 0.08  # 8% hard-coded take profit

DB_PATH = os.getenv("DB_PATH", "trading_bot.db")
BACKUP_PATH = os.getenv("BACKUP_PATH", "memory_backup.json")

COINSPOT_BASE_URL = "https://www.coinspot.com.au"
