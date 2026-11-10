
import os
from datetime import timedelta
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()


class Config:
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
    }

    SECRET_KEY = os.getenv("SECRET_KEY")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")

    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=30)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=7)

    JSON_SORT_KEYS = False
    JWT_ALGORITHM = "HS256"

    BASE_DIR = Path(__file__).resolve().parent.parent

    UPLOAD_FOLDER = str(BASE_DIR / "uploads")
    MAX_CONTENT_LENGTH = 6 * 1024 * 1024

    PAYWAY_SANDBOX_ENABLED = os.getenv("PAYWAY_SANDBOX_ENABLED", "false").lower() == "true"
    PAYWAY_BASE_URL = os.getenv("PAYWAY_BASE_URL", "https://checkout-sandbox.payway.com.kh")
    PAYWAY_MERCHANT_ID = os.getenv("PAYWAY_MERCHANT_ID")
    PAYWAY_API_KEY = os.getenv("PAYWAY_API_KEY")
    PAYWAY_CALLBACK_URL = os.getenv("PAYWAY_CALLBACK_URL")
    PAYWAY_CALLBACK_SECRET = os.getenv("PAYWAY_CALLBACK_SECRET")
    PAYWAY_CONNECT_TIMEOUT = float(os.getenv("PAYWAY_CONNECT_TIMEOUT", "5"))
    PAYWAY_READ_TIMEOUT = float(os.getenv("PAYWAY_READ_TIMEOUT", "15"))
    PAYWAY_QR_LIFETIME_MINUTES = int(os.getenv("PAYWAY_QR_LIFETIME_MINUTES", "15"))
    PAYWAY_LEASE_SECONDS = int(os.getenv("PAYWAY_LEASE_SECONDS", "90"))
    PAYWAY_PUBLIC_API_ENABLED = os.getenv("PAYWAY_PUBLIC_API_ENABLED", "false").lower() == "true"
    PAYWAY_CALLBACK_APPROVED = os.getenv("PAYWAY_CALLBACK_APPROVED", "false").lower() == "true"
    PAYWAY_SANDBOX_VERIFIED = os.getenv("PAYWAY_SANDBOX_VERIFIED", "false").lower() == "true"

    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
    PAYMENT_WORKER_INTERVAL_SECONDS = int(os.getenv("PAYMENT_WORKER_INTERVAL_SECONDS", "15"))
    PAYMENT_WORKER_BATCH_SIZE = int(os.getenv("PAYMENT_WORKER_BATCH_SIZE", "20"))
    PAYWAY_WORKER_VERIFIED = os.getenv("PAYWAY_WORKER_VERIFIED", "false").lower() == "true"
