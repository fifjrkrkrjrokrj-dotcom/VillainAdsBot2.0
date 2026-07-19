import os
import glob
import logging
import asyncio
from typing import Dict, Optional
import database
import config
from userbot import UserBot

logger = logging.getLogger(__name__)

# Dictionary containing active running UserBot instances
_running_bots: Dict[str, UserBot] = {}

def can_start_more_bots() -> bool:
    """
    Returns True if starting another userbot would not exceed the concurrent limit.
    Cleans up stale, dead, or deleted bots from the running registry.
    """
    try:
        sessions = database.get_sessions()
        valid_running_session_ids = {s["session_id"] for s in sessions if s.get("status") == "running"}
        
        to_stop = []
        for session_id, bot in list(_running_bots.items()):
            # If the bot is not in the database or its database status is not 'running',
            # or if the client is disconnected, we schedule it to stop.
            if session_id not in valid_running_session_ids or (bot.client and not bot.client.is_connected()):
                to_stop.append(session_id)
                
        for s_id in to_stop:
            logger.info(f"Self-healing: Stopping and removing stale userbot session: {s_id}")
            bot = _running_bots.pop(s_id, None)
            if bot:
                bot.is_running = False
                asyncio.create_task(bot.stop())
    except Exception as cleanup_err:
        logger.error(f"Error during running registry self-healing: {cleanup_err}")

    max_running = getattr(config, "MAX_RUNNING_USERBOTS", 99999)
    active_count = len([b for b in _running_bots.values() if b.is_running])
    # Always return True to allow unlimited concurrent userbots
    return True

async def start_userbot(session_id: str) -> bool:
    """
    Starts a UserBot instance if not already running.
    """
    if session_id in _running_bots:
        # Already running, verify its status
        if _running_bots[session_id].is_running:
            return True
            
    # Check concurrent limit to prevent OOM
    if not can_start_more_bots():
        logger.warning(f"Limit of active userbots reached ({config.MAX_RUNNING_USERBOTS}). Cannot start userbot {session_id}.")
        return False
            
    bot = UserBot(session_id)
    success = await bot.start()
    if success:
        _running_bots[session_id] = bot
        return True
    return False

async def stop_userbot(session_id: str):
    """
    Stops a running UserBot instance.
    """
    if session_id in _running_bots:
        bot = _running_bots[session_id]
        await bot.stop()
        _running_bots.pop(session_id, None)

def is_bot_running(session_id: str) -> bool:
    """
    Returns True if the UserBot is currently active in memory and connected.
    """
    if session_id in _running_bots:
        bot = _running_bots[session_id]
        if bot.is_running:
            if bot.client and not bot.client.is_connected():
                logger.info(f"Self-healing: Detected disconnected userbot {session_id} in is_bot_running, marking stopped.")
                bot.is_running = False
                _running_bots.pop(session_id, None)
                asyncio.create_task(bot.stop())
                return False
            return True
    return False

async def start_all_running_bots():
    """
    Resumes all UserBots that are marked as 'running' in the database (e.g. after a manager reboot).
    """
    logger.info("Resuming previously active userbots...")
    sessions = database.get_sessions()
    
    running_count = 0
    for s in sessions:
        if s.get("status") == "running":
            session_id = s["session_id"]
            try:
                # Check limit before trying to start
                if not can_start_more_bots():
                    logger.warning(f"Resuming aborted for userbot {session_id} because the limit of {config.MAX_RUNNING_USERBOTS} active bots was reached.")
                    s["status"] = "stopped"
                    database.save_session(s)
                    continue

                # Start userbots sequentially with a small delay to avoid network/loop congestion
                success = await start_userbot(session_id)
                if success:
                    running_count += 1
                await asyncio.sleep(1.5)
            except Exception as e:
                logger.error(f"Error resuming userbot {session_id} on startup: {e}")
                
    logger.info(f"Resumed {running_count} userbot(s).")

async def remove_userbot(session_id: str):
    """
    Stops the userbot, deletes its session file from disk, and removes its database entry.
    """
    # 1. Stop if running
    await stop_userbot(session_id)
    
    # 2. Retrieve session record to locate session file
    sess = database.get_session(session_id)
    if sess:
        session_file = sess["session_file"]
        # Delete DB record
        database.delete_session(session_id)
        
        # Delete file(s) from disk
        if session_file:
            # Delete primary session file and any journals
            for f in glob.glob(session_file + "*"):
                try:
                    if os.path.exists(f):
                        os.remove(f)
                        logger.info(f"Deleted local session file: {f}")
                except Exception as e:
                    logger.warning(f"Could not delete session file {f}: {e}")
                    
    logger.info(f"Userbot session {session_id} completely removed.")

async def stop_all_bots():
    """
    Stops all currently running userbots.
    """
    logger.info("Stopping all active userbots...")
    session_ids = list(_running_bots.keys())
    for s_id in session_ids:
        await stop_userbot(s_id)
    logger.info("All userbots stopped.")

async def clone_profile(session_id: str, target: str, clone_type: str = "complete") -> tuple:
    """
    Clones target profile (first_name, last_name, about/bio, and profile photo) 
    to the userbot instance associated with session_id based on clone_type.
    """
    if session_id not in _running_bots or not _running_bots[session_id].is_running:
        return False, "Userbot is not running. Please start it first."
        
    bot = _running_bots[session_id]
    client = bot.client
    if not client or not client.is_connected():
        return False, "Userbot client is not connected."
        
    try:
        from telethon.tl.functions.users import GetFullUserRequest
        from telethon.tl.functions.account import UpdateProfileRequest
        from telethon.tl.functions.photos import UploadProfilePhotoRequest
        
        # Backup original profile details if not already backed up
        sess_data = database.get_session(session_id)
        if sess_data and "original_first_name" not in sess_data:
            try:
                me = await client.get_me()
                me_full = await client(GetFullUserRequest(me))
                me_bio = me_full.full_user.about or ""
                
                os.makedirs("user_data", exist_ok=True)
                orig_photo_path = f"user_data/original_photo_{session_id}.jpg"
                downloaded_orig = await client.download_profile_photo(me, file=orig_photo_path)
                
                sess_data["original_first_name"] = me.first_name or ""
                sess_data["original_last_name"] = me.last_name or ""
                sess_data["original_about"] = me_bio
                sess_data["has_original_photo"] = bool(downloaded_orig)
                database.save_session(sess_data)
            except Exception as backup_err:
                logger.warning(f"Failed to backup original profile for {session_id}: {backup_err}")
                
        # Resolve entity
        try:
            if target.isdigit() or (target.startswith("-") and target[1:].isdigit()):
                target_peer = int(target)
            elif target.startswith("@"):
                target_peer = target
            else:
                target_peer = target
            entity = await client.get_entity(target_peer)
        except Exception as e:
            return False, f"Could not find target '{target}': {e}"
            
        # Get full user details (including bio)
        full_user = await client(GetFullUserRequest(entity))
        user = full_user.users[0]
        bio = full_user.full_user.about or ""
            
        # Download target's profile photo if cloning complete or photo only
        photo_path = None
        if clone_type in ("photo", "complete"):
            try:
                photo_path = await client.download_profile_photo(entity, file=f"user_data/temp_clone_{session_id}.jpg")
            except Exception as e:
                logger.warning(f"Failed to download profile photo: {e}")
            
        # Update name and bio based on clone_type
        first_name = user.first_name or ""
        last_name = user.last_name or ""
        
        update_args = {}
        if clone_type in ("name", "complete"):
            update_args["first_name"] = first_name
            update_args["last_name"] = last_name
        if clone_type in ("bio", "complete"):
            update_args["about"] = bio
            
        if update_args:
            await client(UpdateProfileRequest(**update_args))
        
        # Update profile photo if downloaded
        if photo_path and os.path.exists(photo_path):
            try:
                uploaded = await client.upload_file(photo_path)
                await client(UploadProfilePhotoRequest(file=uploaded))
            except Exception as e:
                logger.warning(f"Failed to set profile photo: {e}")
            finally:
                try:
                    os.remove(photo_path)
                except Exception:
                    pass
                    
        # Update session info in database if name was changed
        if clone_type in ("name", "complete"):
            sess_data = database.get_session(session_id)
            if sess_data:
                sess_data["name"] = f"{first_name} {last_name}".strip()
                database.save_session(sess_data)
            
        return True, f"Successfully cloned profile ({clone_type}) of {first_name} (@{user.username or 'None'})!"
    except Exception as e:
        logger.error(f"Error cloning profile: {e}")
        return False, f"Error: {e}"

async def restore_original_profile(session_id: str) -> tuple:
    """
    Restores the userbot's original profile (first_name, last_name, about/bio, and photo).
    """
    if session_id not in _running_bots or not _running_bots[session_id].is_running:
        return False, "Userbot is not running. Please start it first."
        
    bot = _running_bots[session_id]
    client = bot.client
    if not client or not client.is_connected():
        return False, "Userbot client is not connected."
        
    sess_data = database.get_session(session_id)
    if not sess_data or "original_first_name" not in sess_data:
        return False, "No original profile backup found. You must clone a profile first."
        
    try:
        from telethon.tl.functions.account import UpdateProfileRequest
        from telethon.tl.functions.photos import UploadProfilePhotoRequest
        
        orig_first = sess_data.get("original_first_name", "")
        orig_last = sess_data.get("original_last_name", "")
        orig_bio = sess_data.get("original_about", "")
        
        # Restore name and bio
        await client(UpdateProfileRequest(
            first_name=orig_first,
            last_name=orig_last,
            about=orig_bio
        ))
        
        # Restore photo if it exists
        orig_photo_path = f"user_data/original_photo_{session_id}.jpg"
        if sess_data.get("has_original_photo") and os.path.exists(orig_photo_path):
            try:
                uploaded = await client.upload_file(orig_photo_path)
                await client(UploadProfilePhotoRequest(file=uploaded))
            except Exception as e:
                logger.warning(f"Failed to restore original profile photo: {e}")
        else:
            # If they didn't have a photo originally, remove current profile photo
            try:
                from telethon.tl.functions.photos import DeletePhotosRequest
                photos = await client.get_profile_photos('me')
                if photos:
                    await client(DeletePhotosRequest(id=[photos[0]]))
            except Exception as e:
                logger.warning(f"Failed to remove cloned profile photo: {e}")
                
        # Update session details
        sess_data["name"] = f"{orig_first} {orig_last}".strip()
        
        # Clean backup fields from DB
        sess_data.pop("original_first_name", None)
        sess_data.pop("original_last_name", None)
        sess_data.pop("original_about", None)
        sess_data.pop("has_original_photo", None)
        database.save_session(sess_data)
        
        # Clean up local backup file
        if os.path.exists(orig_photo_path):
            try:
                os.remove(orig_photo_path)
            except Exception:
                pass
                
        return True, "Successfully restored original profile details!"
    except Exception as e:
        logger.error(f"Error restoring original profile: {e}")
        return False, f"Error: {e}"

def reload_bot_settings(session_id: str):
    """
    Reloads the in-memory settings of a running userbot.
    """
    if session_id in _running_bots:
        _running_bots[session_id].reload_settings()

def get_running_bot(session_id: str) -> Optional[UserBot]:
    """
    Returns the running UserBot instance for a session_id if it exists.
    """
    return _running_bots.get(session_id)
