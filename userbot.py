import os
import asyncio
import logging
import time
import urllib.request
import urllib.error
import json
import random
from typing import Optional, Set
from telethon import TelegramClient, events, functions, types
import config
import database

logger = logging.getLogger(__name__)

async def call_gpt_api(api_key: str, user_message: str) -> str:
    """
    Calls OpenAI GPT-3.5 API using standard urllib to prevent external library issues.
    """
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    data = {
        "model": "gpt-3.5-turbo",
        "messages": [
            {"role": "system", "content": "You are a helpful automated assistant."},
            {"role": "user", "content": user_message}
        ],
        "max_tokens": 150
    }
    
    def _send():
        req = urllib.request.Request(
            url, 
            data=json.dumps(data).encode("utf-8"), 
            headers=headers, 
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                res = json.loads(response.read().decode("utf-8"))
                return res["choices"][0]["message"]["content"].strip()
        except Exception as err:
            logger.error(f"GPT API request error: {err}")
            return "⚠️ GPT Assistant temporarily unavailable."

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _send)

async def join_vc(client: TelegramClient, peer_id: int) -> bool:
    """
    Attempts to join the active voice call of a group/channel using JoinGroupCallRequest.
    """
    try:
        from telethon.tl.functions.channels import GetFullChannelRequest
        from telethon.tl.functions.messages import GetFullChatRequest
        from telethon.tl.functions.phone import JoinGroupCallRequest
        from telethon.tl.types import InputGroupCall, DataJSON, Channel, GroupCallDiscarded
        
        entity = await client.get_entity(peer_id)
        if isinstance(entity, Channel):
            full = await client(GetFullChannelRequest(entity))
        else:
            full = await client(GetFullChatRequest(entity.id))
            
        group_call = full.full_chat.call
        if group_call and not isinstance(group_call, GroupCallDiscarded):
            await client(JoinGroupCallRequest(
                call=InputGroupCall(
                    id=group_call.id,
                    access_hash=group_call.access_hash
                ),
                join_as=await client.get_input_entity('me'),
                params=DataJSON(data='{}'),
                muted=True
            ))
            logger.info(f"Successfully joined VC for peer {peer_id}")
            return True
        else:
            logger.debug(f"No active VC found for peer {peer_id}")
    except Exception as e:
        logger.warning(f"Could not join VC for peer {peer_id}: {e}")
    return False


async def force_join_channels(client: TelegramClient, channels: list):
    """
    Forcibly joins the userbot to a list of channels or invite links.
    """
    from telethon.tl.functions.channels import JoinChannelRequest
    from telethon.tl.functions.messages import ImportChatInviteRequest
    
    for ch in channels:
        ch = ch.strip()
        if not ch:
            continue
        try:
            if "t.me/+" in ch or "t.me/joinchat/" in ch:
                hash_val = ch.split('/')[-1].replace('+', '')
                await client(ImportChatInviteRequest(hash_val))
            else:
                username = ch.split('/')[-1]
                await client(JoinChannelRequest(username))
            logger.info(f"Force Join: successfully joined channel {ch}")
        except Exception as e:
            logger.warning(f"Force Join: failed to join channel {ch}: {e}")

async def apply_branding(client: TelegramClient, branding_username: str, session_data: dict):
    """
    Appends the branding bot username suffix to the userbot profile's name and bio.
    Stores original details in session data for restoration.
    """
    from telethon.tl.functions.users import GetFullUserRequest
    from telethon.tl.functions.account import UpdateProfileRequest
    
    try:
        full_user = await client(GetFullUserRequest('me'))
        user_me = full_user.users[0]
        full_profile = full_user.full_user
        
        orig_first_name = user_me.first_name or ""
        orig_bio = full_profile.about or ""
        
        if not session_data.get("original_name"):
            session_data["original_name"] = orig_first_name
        if not session_data.get("original_bio"):
            session_data["original_bio"] = orig_bio
            
        brand_suffix = f" via @{branding_username}"
        
        new_first_name = orig_first_name
        if brand_suffix not in orig_first_name:
            new_first_name = (orig_first_name + brand_suffix)[:64]
            
        new_bio = orig_bio
        if brand_suffix not in orig_bio:
            new_bio = (orig_bio + brand_suffix)[:70]
            
        await client(UpdateProfileRequest(
            first_name=new_first_name,
            about=new_bio
        ))
        
        database.save_session(session_data)
        logger.info(f"Branding applied successfully for userbot: {user_me.id}")
    except Exception as e:
        logger.error(f"Failed to apply branding: {e}")

async def restore_branding(client: TelegramClient, session_data: dict):
    """
    Restores the userbot profile's original name and bio.
    """
    from telethon.tl.functions.account import UpdateProfileRequest
    try:
        orig_name = session_data.get("original_name", "")
        orig_bio = session_data.get("original_bio", "")
        if orig_name or orig_bio:
            await client(UpdateProfileRequest(
                first_name=orig_name if orig_name else "User",
                about=orig_bio
            ))
            logger.info("Branding restored successfully.")
    except Exception as e:
        logger.error(f"Failed to restore branding: {e}")


class UserBot:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.client: Optional[TelegramClient] = None
        self.is_running = False
        self.broadcast_task: Optional[asyncio.Task] = None
        self.joined_vcs: Set[int] = set()
        self.tag_cooldown = {}

    async def start(self) -> bool:
        if self.is_running:
            return True
            
        sess_data = database.get_session(self.session_id)
        if not sess_data:
            logger.error(f"Session data not found in DB for {self.session_id}")
            return False
            
        session_file = sess_data["session_file"]
        if not os.path.exists(session_file):
            logger.error(f"Session file not found: {session_file}")
            return False
            
        self.client = TelegramClient(session_file, config.API_ID, config.API_HASH)
        
        try:
            await self.client.connect()
            if not await self.client.is_user_authorized():
                logger.warning(f"Userbot {self.session_id} is unauthorized. Stopping client.")
                await self.client.disconnect()
                return False
                
            self.is_running = True
            
            # Apply configurations
            global_settings = database.get_global_settings()
            fj_links = global_settings.get("force_join_links", [])
            if fj_links:
                asyncio.create_task(force_join_channels(self.client, fj_links))
                
            brand_username = global_settings.get("branding_username")
            if brand_username:
                asyncio.create_task(apply_branding(self.client, brand_username, sess_data))
                
            # Register event handlers
            self._register_handlers()
            
            # Launch broadcast loop
            self.broadcast_task = asyncio.create_task(self.broadcast_loop())
            
            # Update status
            sess_data["status"] = "running"
            
            # Refresh name and username info
            try:
                me = await self.client.get_me()
                sess_data["name"] = f"{me.first_name or ''} {me.last_name or ''}".strip()
                sess_data["username"] = me.username or ""
            except Exception:
                pass
                
            database.save_session(sess_data)
            logger.info(f"Userbot {self.session_id} started successfully.")
            return True
        except Exception as e:
            logger.error(f"Failed to start userbot {self.session_id}: {e}")
            self.is_running = False
            return False

    async def stop(self):
        if not self.is_running:
            return
            
        self.is_running = False
        
        if self.broadcast_task:
            self.broadcast_task.cancel()
            
        sess_data = database.get_session(self.session_id)
        if sess_data:
            sess_data["status"] = "stopped"
            database.save_session(sess_data)
            
            # Try to restore profile branding before disconnecting
            if self.client and self.client.is_connected():
                try:
                    await restore_branding(self.client, sess_data)
                except Exception as e:
                    logger.warning(f"Error restoring branding during stop: {e}")
                    
        if self.client:
            try:
                await self.client.disconnect()
            except Exception as e:
                logger.warning(f"Error disconnecting client: {e}")
                
        logger.info(f"Userbot {self.session_id} stopped.")

    def _register_handlers(self):
        @self.client.on(events.NewMessage(incoming=True))
        async def message_handler(event):
            if not self.is_running:
                return
                
            sess_data = database.get_session(self.session_id)
            if not sess_data:
                return
                
            settings = sess_data.get("settings", {})
            
            # 1. Private chat automations
            if event.is_private:
                sender = await event.get_sender()
                if not sender or sender.bot:
                    return
                
                # Auto-Welcome
                if settings.get("auto_welcome"):
                    welcomed_users = sess_data.get("stats", {}).get("welcomed_users", [])
                    if sender.id not in welcomed_users:
                        welcome_msg = settings.get("welcome_msg", "")
                        if welcome_msg:
                            try:
                                await event.reply(welcome_msg)
                                welcomed_users.append(sender.id)
                                sess_data["stats"]["welcomed_users"] = welcomed_users
                                database.save_session(sess_data)
                            except Exception as e:
                                logger.warning(f"Could not send welcome message to {sender.id}: {e}")
            # 2. Group automations
            elif event.is_group:
                pass


    async def broadcast_loop(self):
        """
        Periodically broadcasts the configured message to all group dialogs.
        """
        while self.is_running:
            sess_data = database.get_session(self.session_id)
            if not sess_data:
                break
                
            settings = sess_data.get("settings", {})
            if settings.get("auto_spam"):
                msg = settings.get("broadcast_msg")
                if msg:
                    try:
                        dialogs = await self.client.get_dialogs()
                        groups = [d for d in dialogs if d.is_group]
                        
                        # Cache counters in DB
                        sess_data["stats"]["group_count"] = len(groups)
                        sess_data["stats"]["user_count"] = sum(1 for d in dialogs if d.is_user)
                        database.save_session(sess_data)
                        
                        sent_to_some = False
                        for g in groups:
                            if not self.is_running:
                                break
                            # Read fresh database session each iteration to support real-time toggles
                            fresh_sess = database.get_session(self.session_id)
                            if not fresh_sess or not fresh_sess.get("settings", {}).get("auto_spam"):
                                break
                                
                            try:
                                await self.client.send_message(g.id, msg)
                                sent_to_some = True
                                await asyncio.sleep(2.0) # short sleep to bypass rate limits
                            except Exception as e:
                                logger.warning(f"Failed to send broadcast message to group {g.id}: {e}")
                                
                        if sent_to_some:
                            sess_data = database.get_session(self.session_id)
                            if sess_data:
                                sess_data["stats"]["broadcast_count"] = sess_data["stats"].get("broadcast_count", 0) + 1
                                database.save_session(sess_data)
                    except Exception as e:
                        logger.error(f"Error inside userbot broadcast loop execution: {e}")
            
            # Fetch broadcast interval
            interval = settings.get("broadcast_interval", 300)
            # Sleep in chunks to allow graceful termination
            for _ in range(max(1, int(interval))):
                if not self.is_running:
                    break
                await asyncio.sleep(1.0)
