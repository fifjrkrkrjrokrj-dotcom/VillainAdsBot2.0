import os
from dotenv import load_dotenv

load_dotenv()

# Bot Name Configuration
BOT_NAME = os.getenv("BOT_NAME", "𝗫𝗧𝗥 𝗔𝗗 𝗕𝗢𝗧")
DEFAULT_DB_NAME = "xtr_ad_bot"

# Telegram API credentials for userbots
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")

# Bot token for the main manager bot
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# MongoDB connection URI
MONGODB_URI = os.getenv("MONGODB_URI", "")

# Parse original admin IDs (which cannot be removed)
original_admin_ids_str = os.getenv("ORIGINAL_ADMIN_IDS", "")
ORIGINAL_ADMIN_IDS = set()
if original_admin_ids_str:
    for x in original_admin_ids_str.split(","):
        x = x.strip()
        if x.isdigit():
            ORIGINAL_ADMIN_IDS.add(int(x))

# Directory for local session files
USER_DATA_DIR = "user_data"

# Gmail credentials for auto-approval
GMAIL_USER = os.getenv("GMAIL_USER", "ashishchoudharyrj21@gmail.com")
GMAIL_APP_PASS = os.getenv("GMAIL_APP_PASS", "nsbh dkqi jqil wwuw")
FAMAPP_EMAILS = [x.strip() for x in os.getenv("FAMAPP_EMAILS", "no-reply@famapp.in").split(",") if x.strip()]

# Default values for global settings
DEFAULT_GLOBAL_SETTINGS = {
    "price_per_id": 10.0,            # Global price per extra ID
    "force_join_links": [],           # List of usernames/links to force join
    "log_group_id": -1004354441869,   # Log group/channel ID
    "branding_username": None,        # Bot username to append (e.g. via @MyBot)
    "branding_duration": 30,          # Duration of branding in days
    "branding_name_enabled": True,    # Enable name branding
    "branding_bio_enabled": True,     # Enable bio branding
    "branding_name_text": None,       # Custom name branding suffix text
    "branding_bio_text": None,        # Custom bio branding suffix text
    "start_image": "https://files.catbox.moe/jnlroe.jpg",              # File ID of the start image
    "ping_image": "https://files.catbox.moe/7qgokb.jpg",               # File ID of the ping image
    "help_image": "https://files.catbox.moe/xxpn14.jpg",               # File ID of the help image
    "admins": list(ORIGINAL_ADMIN_IDS), # List of admins
    "gpt_api_key": None,               # Global OpenAI API Key for GPT mode (optional)
    "maintenance_mode": False,         # Maintenance guard
    "upi_id": "raunitkumar01@fam",          # Admin UPI ID for payments
    "usdt_bep20_address": "0x0000000000000000000000000000000000000000", # USDT BEP20 Address
    "ton_address": "UQ000000000000000000000000000000000000000000000000", # TON Address
    "support_channel": "https://t.me/+Qzy2vnoy3g00OTE1",                 # Support channel invite link
    "support_group": "https://t.me/+DlgFzulC_JY5OWI1",                   # Support group invite link
    "userbot_auto_join_links": [],                                       # Auto-join links for new userbots
    "referral_commission": 0.10,        # 10% commission on slot upgrades
    "subscription_plans": [             # Dynamic slot subscription plans
        {"id": "std30", "days": 30, "price": 10.0, "button_name": "Standard 30 Days"}
    ]
}
