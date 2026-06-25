import os
import logging
import time
from typing import Dict, Any, List, Optional
from pymongo import MongoClient
import config

logger = logging.getLogger(__name__)

# Global database variables
_mongo_client: Optional[MongoClient] = None
_db = None

def db_init():
    """
    Initializes the MongoDB connection.
    Raises an exception if the connection fails or if MONGODB_URI is not set.
    """
    global _mongo_client, _db
    if not config.MONGODB_URI:
        raise ValueError("MONGODB_URI is not set in the environment variables.")
        
    try:
        logger.info("Connecting to MongoDB...")
        _mongo_client = MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=5000)
        # Force a connection check
        _mongo_client.server_info()
        try:
            _db = _mongo_client.get_database()
        except Exception:
            _db = _mongo_client.get_database(config.DEFAULT_DB_NAME)
        logger.info("Successfully connected to MongoDB.")
        
        # Create indexes to prevent slow collection scans as database grows
        try:
            _db.users.create_index("user_id", unique=True)
        except Exception as idx_err:
            logger.warning(f"Could not create unique index on users.user_id: {idx_err}")
            _db.users.create_index("user_id")
            
        _db.users.create_index("username")
        
        try:
            _db.sessions.create_index("session_id", unique=True)
        except Exception as idx_err:
            logger.warning(f"Could not create unique index on sessions.session_id: {idx_err}")
            _db.sessions.create_index("session_id")
            
        _db.sessions.create_index("user_id")
        
        try:
            _db.payments.create_index("payment_id", unique=True)
        except Exception as idx_err:
            logger.warning(f"Could not create unique index on payments.payment_id: {idx_err}")
            _db.payments.create_index("payment_id")
            
        _db.payments.create_index("user_id")
        _db.payments.create_index("utr_code")
        
        try:
            _db.coupons.create_index("code", unique=True)
        except Exception as idx_err:
            logger.warning(f"Could not create unique index on coupons.code: {idx_err}")
            _db.coupons.create_index("code")
            
        _db.coupon_usage.create_index([("code", 1), ("user_id", 1)])
        
        try:
            _db.force_channels.create_index("channel_id", unique=True)
        except Exception as idx_err:
            logger.warning(f"Could not create unique index on force_channels.channel_id: {idx_err}")
            _db.force_channels.create_index("channel_id")
            
        logger.info("Database indexes checked/created successfully.")
        
        # Initialize default settings if not exists
        settings = _db.settings.find_one({"id": "global"})
        if not settings:
            settings = dict(config.DEFAULT_GLOBAL_SETTINGS)
            settings["id"] = "global"
            _db.settings.insert_one(settings)
            logger.info("Initialized default global settings in MongoDB.")
            
    except Exception as e:
        logger.critical(f"Failed to connect to MongoDB: {e}")
        raise e

# ==================== User CRUD Operations ====================
def get_user(user_id: int) -> Optional[Dict[str, Any]]:
    return _db.users.find_one({"user_id": user_id})

def save_user(user_data: Dict[str, Any]):
    _db.users.replace_one({"user_id": user_data["user_id"]}, user_data, upsert=True)

def get_all_users() -> List[Dict[str, Any]]:
    return list(_db.users.find({}))

# ==================== Session CRUD Operations ====================
def get_sessions(user_id: Optional[int] = None) -> List[Dict[str, Any]]:
    query = {"user_id": user_id} if user_id is not None else {}
    return list(_db.sessions.find(query))

def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    return _db.sessions.find_one({"session_id": session_id})

def save_session(session_data: Dict[str, Any]):
    _db.sessions.replace_one({"session_id": session_data["session_id"]}, session_data, upsert=True)

def delete_session(session_id: str):
    _db.sessions.delete_one({"session_id": session_id})

# ==================== Payment CRUD Operations ====================
def get_payment_requests(user_id: Optional[int] = None) -> List[Dict[str, Any]]:
    query = {"user_id": user_id} if user_id is not None else {}
    return list(_db.payments.find(query))

def get_payment_request(payment_id: str) -> Optional[Dict[str, Any]]:
    return _db.payments.find_one({"payment_id": payment_id})

def save_payment_request(payment_data: Dict[str, Any]):
    _db.payments.replace_one({"payment_id": payment_data["payment_id"]}, payment_data, upsert=True)

# ==================== Settings CRUD Operations ====================
def get_global_settings() -> Dict[str, Any]:
    settings = _db.settings.find_one({"id": "global"})
    if not settings:
        settings = dict(config.DEFAULT_GLOBAL_SETTINGS)
        settings["id"] = "global"
        _db.settings.insert_one(settings)
    else:
        # Merge defaults to ensure new settings keys are backfilled
        updated = False
        for k, v in config.DEFAULT_GLOBAL_SETTINGS.items():
            if k not in settings:
                settings[k] = v
                updated = True
        
        # Self-healing: if start_image in DB is the old default, update it to the new one
        if settings.get("start_image") == "https://files.catbox.moe/syoba0.jpg":
            settings["start_image"] = config.DEFAULT_GLOBAL_SETTINGS["start_image"]
            updated = True

        # Self-healing: if help_image in DB is the old default, update it to the new one
        if settings.get("help_image") == "https://files.catbox.moe/f9b2f1.jpg":
            settings["help_image"] = config.DEFAULT_GLOBAL_SETTINGS["help_image"]
            updated = True
            
        if updated:
            _db.settings.replace_one({"id": "global"}, settings)
    return settings

def save_global_settings(settings_data: Dict[str, Any]):
    settings_data["id"] = "global"
    _db.settings.replace_one({"id": "global"}, settings_data, upsert=True)

# ==================== Force Channels CRUD ====================
def get_force_channels() -> List[Dict[str, Any]]:
    return list(_db.force_channels.find({}))

def add_force_channel(channel_id: str, invite_link: str, channel_name: str):
    data = {
        "channel_id": channel_id,
        "channel_link": invite_link,
        "channel_name": channel_name
    }
    _db.force_channels.replace_one({"channel_id": channel_id}, data, upsert=True)

def delete_force_channel(channel_id: str):
    _db.force_channels.delete_one({"channel_id": channel_id})

# ==================== Coupons CRUD ====================
def get_coupons() -> List[Dict[str, Any]]:
    return list(_db.coupons.find({}))

def get_coupon(code: str) -> Optional[Dict[str, Any]]:
    return _db.coupons.find_one({"code": code})

def save_coupon(coupon_data: Dict[str, Any]):
    _db.coupons.replace_one({"code": coupon_data["code"]}, coupon_data, upsert=True)

def delete_coupon(code: str):
    _db.coupons.delete_one({"code": code})

# ==================== Coupon Usage CRUD ====================
def has_used_coupon(code: str, user_id: int) -> bool:
    return _db.coupon_usage.find_one({"code": code, "user_id": user_id}) is not None

def save_coupon_usage(code: str, user_id: int):
    data = {
        "code": code,
        "user_id": user_id,
        "timestamp": time.time()
    }
    _db.coupon_usage.insert_one(data)

# ==================== User Referral & Lookup Helpers ====================
def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    """
    Looks up a user by username in a case-insensitive manner.
    """
    username = username.strip().replace("@", "")
    import re
    return _db.users.find_one({"username": re.compile(f"^{username}$", re.IGNORECASE)})

def count_referred_users(user_id: int) -> int:
    """
    Counts the number of users referred by the given user_id.
    """
    return _db.users.count_documents({"referred_by": user_id})

def get_payment_request_by_utr_and_status(utr: str, status: str = "pending") -> Optional[Dict[str, Any]]:
    """
    Looks up a payment request by UTR and status directly using index.
    """
    return _db.payments.find_one({"utr_code": utr, "status": status})
