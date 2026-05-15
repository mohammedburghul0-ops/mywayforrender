# config.py
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    
    ADMIN_IDS_STR = os.getenv("ADMIN_IDS", "")
    ADMIN_IDS = [int(i.strip()) for i in ADMIN_IDS_STR.split(",") if i.strip().isdigit()]
    
    ACCOUNTING_GROUP_ID = os.getenv("ACCOUNTING_GROUP_ID")
    
    FB_PAGE = os.getenv("FB_PAGE_URL")
    FB_GROUP = os.getenv("FB_GROUP_URL")
    INSTA = os.getenv("INSTA_URL")
    TELEGRAM = os.getenv("TELEGRAM_URL")

    ALHARAM_REF = os.getenv("ALHARAM_REF")
    SYRIATEL_CASH = os.getenv("SYRIATEL_CASH")
    MTN_CASH = os.getenv("MTN_CASH")
    CHAM_CASH = os.getenv("CHAM_CASH")
    EAST_WA = os.getenv("EAST_WA")
    
    SIIB_PHONE = os.getenv("SIIB_PHONE")
    SIIB_ACCOUNT = os.getenv("SIIB_ACCOUNT")
    CHAM_NAME = os.getenv("CHAM_NAME")
    CHAM_FILE = os.getenv("CHAM_FILE")
    CHAM_CASH_QR_FILE_ID = os.getenv("CHAM_CASH_QR_FILE_ID")

    DB_NAME = "tariqi_platform.db"