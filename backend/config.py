import os
from dotenv import load_dotenv

load_dotenv()

COINSPOT_API_KEY = os.getenv("COINSPOT_API_KEY", "")
COINSPOT_API_SECRET = os.getenv("COINSPOT_API_SECRET", "")
TRADING_MODE = os.getenv("TRADING_MODE", "paper")  # "paper" or "real"
PAPER_BALANCE = float(os.getenv("PAPER_BALANCE", "1000"))

# Safety interlock — BOTH flags must be set to enable real-money trading
REAL_TRADING_CONFIRMED = os.getenv("REAL_TRADING_CONFIRMED", "false").lower() == "true"

BOT_INTERVAL_SECONDS = int(os.getenv("BOT_INTERVAL_SECONDS", "60"))
STOP_LOSS_PCT = 0.04    # 4% hard-coded stop loss
TAKE_PROFIT_PCT = 0.08  # 8% hard-coded take profit

DB_PATH = os.getenv("DB_PATH", "trading_bot.db")
BACKUP_PATH = os.getenv("BACKUP_PATH", "memory_backup.json")

COINSPOT_BASE_URL = "https://www.coinspot.com.au"
