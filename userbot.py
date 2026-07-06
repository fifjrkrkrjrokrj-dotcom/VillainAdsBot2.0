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

# --- Pytgcalls Telethon Update AttributeError Monkey-Patch ---
try:
    from pytgcalls.mtproto.telethon_client import TelethonClient
    from telethon.events import Raw
    
    original_init = TelethonClient.__init__
    
    def patched_init(self, cache_duration, client):
        original_add = client.add_event_handler
        
        def patched_add(callback, event=None):
            if isinstance(event, Raw) or (event and event.__class__.__name__ == 'Raw'):
                original_callback = callback
                async def wrapped_callback(evt):
                    try:
                        await original_callback(evt)
                    except (AttributeError, ValueError) as err:
                        err_str = str(err)
                        if "UpdateGroupCall" in err_str or "chat_id" in err_str:
                            pass
                        else:
                            raise err
                    except Exception as e:
                        err_str = str(e)
                        if "UpdateGroupCall" in err_str or "chat_id" in err_str:
                            pass
                        else:
                            raise e
                callback = wrapped_callback
            return original_add(callback, event)
            
        client.add_event_handler = patched_add
        try:
            original_init(self, cache_duration, client)
        finally:
            client.add_event_handler = original_add
            
    TelethonClient.__init__ = patched_init
    logger.info("Successfully applied PyTgCalls TelethonClient monkey-patch.")
except Exception as patch_err:
    logger.error(f"Failed to apply PyTgCalls monkey-patch: {patch_err}")

import aiohttp
from pytgcalls import PyTgCalls
from pytgcalls.types import AudioPiped
from py_yt import VideosSearch

API_URL = "https://api.shrutibots.site"
API_KEY = "ShrutiBotsGMiLr8wF1tPbxVV6fRgH"
DOWNLOAD_DIR = "downloads"

async def download_media(query: str, download_type: str = "audio") -> tuple:
    """
    Downloads audio/video for voice call using YouTube API search.
    Returns (file_path: str, title: str, duration: int, thumbnail: str)
    """
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    try:
        if not query.startswith("http"):
            search = VideosSearch(query, limit=1)
            res = await search.next()
            if not res or not res.get("result"):
                return None, None, None, None
            result = res["result"][0]
        else:
            search = VideosSearch(query, limit=1)
            res = await search.next()
            if not res or not res.get("result"):
                return None, None, None, None
            result = res["result"][0]

        title = result["title"]
        duration = result.get("duration", "0:00")
        thumb = result["thumbnails"][0]["url"].split("?")[0]
        vidid = result["id"]
        youtube_url = f"https://www.youtube.com/watch?v={vidid}"

        # duration convert
        duration_sec = sum(
            int(x) * 60 ** i
            for i, x in enumerate(reversed(duration.split(":")))
        )

        ext = "mp3" if download_type == "audio" else "mp4"
        file_path = os.path.join(DOWNLOAD_DIR, f"{vidid}.{ext}")
        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
            return file_path, title, duration_sec, thumb

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{API_URL}/download",
                params={
                    "url": youtube_url,
                    "type": download_type,
                    "api_key": API_KEY
                },
                timeout=aiohttp.ClientTimeout(total=600)
            ) as resp:
                if resp.status != 200:
                    raise Exception("API Download Failed")
                with open(file_path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(1024 * 128):
                        f.write(chunk)

        return file_path, title, duration_sec, thumb
    except Exception as e:
        logger.error(f"Download media error: {e}")
        return None, None, None, None

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


async def get_peer_from_link(client: TelegramClient, link: str):
    """
    Resolves a group/channel link or username to a chat entity,
    joining the channel/group if the userbot is not already a member.
    """
    link = link.strip()
    if not link:
        return None
        
    from telethon.tl.functions.messages import CheckChatInviteRequest, ImportChatInviteRequest
    from telethon.tl.functions.channels import JoinChannelRequest
    from telethon.tl.types import ChatInviteAlready, ChatInvite
    
    # Check if link is a numeric ID
    try:
        val = link
        if val.startswith("-100"):
            return await client.get_entity(int(val))
        elif val.startswith("-") and val[1:].isdigit():
            return await client.get_entity(int(val))
        elif val.isdigit():
            return await client.get_entity(int(val))
    except Exception:
        pass
        
    # Check if it is a private invite link
    if "t.me/+" in link or "t.me/joinchat/" in link:
        # Extract join hash
        if "t.me/+" in link:
            hash_val = link.split('+')[-1].split('/')[0].strip()
        else:
            hash_val = link.split('joinchat/')[-1].split('/')[0].strip()
            
        try:
            invite = await client(CheckChatInviteRequest(hash_val))
            if isinstance(invite, ChatInviteAlready):
                return invite.chat
            else:
                # Need to join
                updates = await client(ImportChatInviteRequest(hash_val))
                if updates and hasattr(updates, 'chats') and updates.chats:
                    return updates.chats[0]
        except Exception as e:
            logger.warning(f"Error checking/joining invite link {link}: {e}")
            # Try to get entity directly as a fallback
            try:
                return await client.get_entity(link)
            except Exception:
                pass
    else:
        # It's a username or public link
        username = link.split('/')[-1].strip()
        if username.startswith("@"):
            username = username[1:]
            
        try:
            # Join channel first
            await client(JoinChannelRequest(username))
        except Exception as e:
            logger.warning(f"Error joining public channel {username}: {e}")
            
        try:
            return await client.get_entity(username)
        except Exception as e:
            logger.warning(f"Error getting entity for {username}: {e}")
            
    return None

async def join_vc_by_link(client: TelegramClient, link: str) -> tuple:
    """
    Joins a channel/group from a link and joins its active voice chat.
    Returns (success: bool, message: str)
    """
    try:
        entity = await get_peer_from_link(client, link)
        if not entity:
            return False, "Could not resolve or join the group/channel."
            
        # Try to join VC
        from telethon.tl.functions.channels import GetFullChannelRequest
        from telethon.tl.functions.messages import GetFullChatRequest
        from telethon.tl.functions.phone import JoinGroupCallRequest
        from telethon.tl.types import InputGroupCall, DataJSON, Channel, GroupCallDiscarded
        
        if isinstance(entity, Channel):
            full = await client(GetFullChannelRequest(entity))
        else:
            full = await client(GetFullChatRequest(entity.id))
            
        group_call = full.full_chat.call
        if group_call and not isinstance(group_call, GroupCallDiscarded):
            import random
            max_retries = 5
            last_err = None
            for attempt in range(max_retries):
                random_ssrc = random.randint(100000, 999999999)
                try:
                    params_json = f'{{"transport":{{"webrtc":true}},"muted":true,"video_stopped":true,"ssrc":{random_ssrc}}}'
                    await client(JoinGroupCallRequest(
                        call=InputGroupCall(
                            id=group_call.id,
                            access_hash=group_call.access_hash
                        ),
                        join_as=await client.get_input_entity('me'),
                        params=DataJSON(data=params_json),
                        muted=True
                    ))
                    logger.info(f"Successfully joined VC for peer {entity.id} with SSRC {random_ssrc}")
                    chat_title = getattr(entity, 'title', 'Group')
                    return True, f"Successfully joined VC of {chat_title}!", {"group_call": group_call, "ssrc": random_ssrc, "chat_id": entity.id}
                except Exception as join_err:
                    err_str = str(join_err).lower()
                    last_err = join_err
                    if "ssrc" in err_str or "duplicate" in err_str:
                        logger.warning(f"SSRC collision on attempt {attempt + 1}, retrying with new SSRC... Error: {join_err}")
                        await asyncio.sleep(0.5)
                        continue
                    else:
                        break
            raise last_err if last_err else Exception("Failed to join call")
        else:
            chat_title = getattr(entity, 'title', 'Group')
            return False, f"No active voice chat (VC) found in {chat_title}.", None
    except Exception as e:
        logger.warning(f"Error joining VC by link {link}: {e}")
        return False, f"Error: {e}", None


async def join_channel_single(client: TelegramClient, ch: str) -> bool:
    """
    Attempts to join a single channel or group by invite link or username.
    Returns True if successfully joined or already in it, False otherwise.
    """
    from telethon.tl.functions.channels import JoinChannelRequest
    from telethon.tl.functions.messages import ImportChatInviteRequest
    
    ch = ch.strip()
    if not ch:
        return False
    try:
        if "t.me/+" in ch or "t.me/joinchat/" in ch:
            hash_val = ch.split('/')[-1].replace('+', '')
            await client(ImportChatInviteRequest(hash_val))
        else:
            username = ch.split('/')[-1]
            await client(JoinChannelRequest(username))
        logger.info(f"Successfully joined channel/group: {ch}")
        return True
    except Exception as e:
        err_msg = str(e).lower()
        if "already" in err_msg or "already participant" in err_msg or "user_already_participant" in err_msg:
            logger.debug(f"Already participant of: {ch}")
            return True
        logger.warning(f"Failed to join channel {ch}: {e}")
        return False

async def force_join_channels(client: TelegramClient, channels: list, session_id: str = None):
    """
    Forcibly joins the userbot to a list of channels or invite links.
    """
    joined_now = []
    
    # Load already joined list if session_id is provided
    sess_data = None
    already_joined = []
    if session_id:
        sess_data = database.get_session(session_id)
        if sess_data:
            already_joined = sess_data.get("joined_channels", [])
            
    for ch in channels:
        ch_clean = ch.strip()
        if not ch_clean:
            continue
            
        # Check if already joined and saved to avoid invite link flood waits
        if ch_clean in already_joined:
            logger.info(f"Skipping auto-join for already joined channel: {ch_clean}")
            continue
            
        success = await join_channel_single(client, ch_clean)
        if success:
            joined_now.append(ch_clean)
            
    # Save newly joined channels to MongoDB
    if sess_data and joined_now:
        # Fetch fresh database record to avoid potential race conditions
        sess_data = database.get_session(session_id)
        if sess_data:
            current_joined = sess_data.setdefault("joined_channels", [])
            for c in joined_now:
                if c not in current_joined:
                    current_joined.append(c)
            database.save_session(sess_data)

async def apply_branding(client: TelegramClient, branding_username: str, session_data: dict):
    """
    Appends the branding bot username suffix to the userbot profile's name and bio based on global settings.
    Stores original details in session data for restoration.
    """
    from telethon.tl.functions.users import GetFullUserRequest
    from telethon.tl.functions.account import UpdateProfileRequest
    
    try:
        global_settings = database.get_global_settings()
        brand_name_enabled = global_settings.get("branding_name_enabled", True)
        brand_bio_enabled = global_settings.get("branding_bio_enabled", True)
        
        brand_name_text = global_settings.get("branding_name_text")
        brand_bio_text = global_settings.get("branding_bio_text")
        
        full_user = await client(GetFullUserRequest('me'))
        user_me = full_user.users[0]
        full_profile = full_user.full_user
        
        orig_first_name = user_me.first_name or ""
        orig_bio = full_profile.about or ""
        
        if not session_data.get("original_name"):
            session_data["original_name"] = orig_first_name
        if not session_data.get("original_bio"):
            session_data["original_bio"] = orig_bio
            
        name_suffix = brand_name_text if brand_name_text else (f" via @{branding_username}" if branding_username else "")
        bio_suffix = brand_bio_text if brand_bio_text else (f" via @{branding_username}" if branding_username else "")
        
        new_first_name = orig_first_name
        if brand_name_enabled and name_suffix:
            if name_suffix not in orig_first_name:
                new_first_name = (orig_first_name + name_suffix)[:64]
                
        new_bio = orig_bio
        if brand_bio_enabled and bio_suffix:
            if bio_suffix not in orig_bio:
                new_bio = (orig_bio + bio_suffix)[:70]
                
        await client(UpdateProfileRequest(
            first_name=new_first_name,
            about=new_bio
        ))
        
        database.save_session(session_data)
        logger.info(f"Branding applied successfully for userbot: {user_me.id} (Name: {brand_name_enabled}, Bio: {brand_bio_enabled})")
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
        self.vc_keepalive_task: Optional[asyncio.Task] = None
        self.current_vc_chat_id: Optional[int] = None
        self.current_vc_link: Optional[str] = None
        self.pytgcalls_client: Optional[PyTgCalls] = None
        self.bg_tasks: Set[asyncio.Task] = set()
        
        # Caching attributes to resolve performance bottlenecks
        self.settings = {}
        self.groups_cache = None
        self.groups_cache_time = 0.0

    def reload_settings(self):
        """
        Reloads userbot settings from MongoDB into memory and restarts the broadcast task.
        """
        sess_data = database.get_session(self.session_id)
        if sess_data:
            self.settings = sess_data.get("settings", {})
            logger.info(f"Reloaded in-memory settings for userbot {self.session_id}")
            
            # Restart the broadcast task if the bot is currently running to apply changes immediately
            if self.is_running:
                if self.broadcast_task:
                    self.broadcast_task.cancel()
                self.broadcast_task = asyncio.create_task(self.broadcast_loop())
                logger.info(f"Restarted broadcast loop for userbot {self.session_id} to apply new settings/interval immediately.")

    async def vc_keepalive_loop(self, group_call, ssrc):
        from telethon.tl.functions.phone import CheckGroupCallRequest
        from telethon.tl.types import InputGroupCall
        try:
            while True:
                await asyncio.sleep(8)
                if not self.client or not self.is_running:
                    break
                try:
                    await self.client(CheckGroupCallRequest(
                        call=InputGroupCall(
                            id=group_call.id,
                            access_hash=group_call.access_hash
                        ),
                        sources=[ssrc]
                    ))
                    logger.debug(f"Sent VC keepalive for userbot {self.session_id} (SSRC: {ssrc})")
                except Exception as e:
                    logger.warning(f"VC keepalive ping failed for userbot {self.session_id}: {e}")
                    if "call_already_discarded" in str(e).lower() or "groupcall_already_discarded" in str(e).lower():
                        break
        except asyncio.CancelledError:
            pass

    async def join_voice_chat(self, link: str) -> tuple:
        """
        Attempts to join the active voice call of a group/channel by link.
        """
        if not self.is_running or not self.client:
            return False, "Userbot is not running."
            
        if self.vc_keepalive_task:
            self.vc_keepalive_task.cancel()
            self.vc_keepalive_task = None
            
        success, msg, call_info = await join_vc_by_link(self.client, link)
        if success and call_info:
            self.current_vc_chat_id = call_info["chat_id"]
            self.current_vc_link = link
            self.vc_keepalive_task = asyncio.create_task(
                self.vc_keepalive_loop(call_info["group_call"], call_info["ssrc"])
            )
        return success, msg

    async def leave_voice_chat(self) -> tuple:
        """
        Leaves any active group call/VC the userbot is in.
        """
        if not self.is_running or not self.client:
            return False, "Userbot is not running."
            
        if self.vc_keepalive_task:
            self.vc_keepalive_task.cancel()
            self.vc_keepalive_task = None
            
        from telethon.tl.functions.phone import LeaveGroupCallRequest
        from telethon.tl.functions.channels import GetFullChannelRequest
        from telethon.tl.functions.messages import GetFullChatRequest
        from telethon.tl.types import InputGroupCall, GroupCallDiscarded
        
        try:
            dialogs = await self.client.get_dialogs(limit=100)
            left_count = 0
            for d in dialogs:
                if d.is_group or d.is_channel:
                    try:
                        from telethon.tl.types import Channel
                        if isinstance(d.entity, Channel):
                            full = await self.client(GetFullChannelRequest(d.entity))
                        else:
                            full = await self.client(GetFullChatRequest(d.entity.id))
                            
                        group_call = full.full_chat.call
                        if group_call and not isinstance(group_call, GroupCallDiscarded):
                            await self.client(LeaveGroupCallRequest(
                                call=InputGroupCall(
                                    id=group_call.id,
                                    access_hash=group_call.access_hash
                                ),
                                source=0
                            ))
                            left_count += 1
                    except Exception:
                        pass
            if self.pytgcalls_client:
                try:
                    if self.current_vc_chat_id:
                        await self.pytgcalls_client.leave_group_call(self.current_vc_chat_id)
                except Exception:
                    pass
                try:
                    await self.pytgcalls_client.stop()
                except Exception:
                    pass
                self.pytgcalls_client = None
                
            self.current_vc_chat_id = None
            self.current_vc_link = None
            return True, f"Successfully left {left_count} voice chat(s)."
        except Exception as e:
            logger.warning(f"Error leaving VC for userbot {self.session_id}: {e}")
            return False, f"Error leaving VC: {e}"

    async def get_pytgcalls(self) -> PyTgCalls:
        if not self.pytgcalls_client:
            self.pytgcalls_client = PyTgCalls(self.client)
            await self.pytgcalls_client.start()
        return self.pytgcalls_client

    async def play_song(self, query: str, play_type: str = "audio") -> tuple:
        """
        Plays a song (audio or video) in the current active Voice Chat of this userbot.
        Returns (success: bool, message: str, song_info: dict)
        """
        if not self.is_running or not self.client:
            return False, "Userbot is not running.", None
            
        if not getattr(self, "current_vc_chat_id", None):
            return False, "Userbot is not currently in any Voice Chat (VC). Please make it join a VC first.", None
            
        # Download the media
        logger.info(f"Userbot {self.session_id} downloading {play_type} query: {query}")
        file_path, title, duration, thumb = await download_media(query, download_type=play_type)
        if not file_path:
            return False, "Failed to download/search the media.", None
            
        try:
            pytg = await self.get_pytgcalls()
            
            if play_type == "video":
                from pytgcalls.types import AudioVideoPiped
                stream_obj = AudioVideoPiped(file_path)
            else:
                stream_obj = AudioPiped(file_path)
                
            try:
                await pytg.join_group_call(
                    self.current_vc_chat_id,
                    stream_obj
                )
            except Exception as join_err:
                try:
                    await pytg.change_stream(
                        self.current_vc_chat_id,
                        stream_obj
                    )
                except Exception as change_err:
                    logger.error(f"PyTgCalls play failed on join/change: {join_err} | {change_err}")
                    return False, f"Could not stream media: {change_err}", None
                    
            song_info = {
                "title": title,
                "duration": duration,
                "thumb": thumb,
                "file_path": file_path
            }
            return True, f"Now playing {title}", song_info
        except Exception as e:
            logger.error(f"Error playing media: {e}")
            return False, f"Error playing media: {e}", None

    async def get_groups(self, force_refresh: bool = False) -> list:
        """
        Returns group dialogs, utilizing a 1-hour cache to avoid heavy Telegram API calls.
        """
        current_time = time.time()
        # Cache dialogs for 1 hour (3600 seconds) unless force-refreshed
        if force_refresh or not self.groups_cache or (current_time - self.groups_cache_time > 3600):
            try:
                logger.info(f"Fetching dialogs for userbot {self.session_id} to refresh groups cache...")
                dialogs = await self.client.get_dialogs()
                self.groups_cache = [d for d in dialogs if d.is_group]
                self.groups_cache_time = current_time
                
                # Update DB stats concurrently
                sess_data = database.get_session(self.session_id)
                if sess_data:
                    sess_data["stats"]["group_count"] = len(self.groups_cache)
                    sess_data["stats"]["user_count"] = sum(1 for d in dialogs if d.is_user)
                    database.save_session(sess_data)
            except Exception as e:
                logger.error(f"Error fetching dialogs for userbot {self.session_id}: {e}")
                if not self.groups_cache:
                    self.groups_cache = []
        return self.groups_cache

    async def start(self) -> bool:
        if self.is_running:
            return True
            
        sess_data = database.get_session(self.session_id)
        if not sess_data:
            logger.error(f"Session data not found in DB for {self.session_id}")
            return False
            
        # Initialize in-memory settings
        self.settings = sess_data.get("settings", {})
        session_file = sess_data["session_file"]
        
        # Restore session file from MongoDB if it was saved
        session_bytes = sess_data.get("session_bytes")
        if session_bytes:
            try:
                os.makedirs(os.path.dirname(session_file), exist_ok=True)
                with open(session_file, "wb") as f:
                    f.write(session_bytes)
                logger.info(f"Restored session file from MongoDB to {session_file}")
            except Exception as e:
                logger.error(f"Failed to restore session file from MongoDB: {e}")

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
            
            # Auto-join support links and custom auto-join links
            support_links = []
            support_channel = global_settings.get("support_channel") or "https://t.me/+Qzy2vnoy3g00OTE1"
            support_group = global_settings.get("support_group") or "https://t.me/+DlgFzulC_JY5OWI1"
            if support_channel:
                support_links.append(support_channel)
            if support_group:
                support_links.append(support_group)
                
            ub_joins = global_settings.get("userbot_auto_join_links", [])
            if ub_joins:
                support_links.extend(ub_joins)
            if support_links:
                t_join1 = asyncio.create_task(force_join_channels(self.client, support_links, session_id=self.session_id))
                self.bg_tasks.add(t_join1)
                t_join1.add_done_callback(self.bg_tasks.discard)
 
            # Auto-join force subscribe channels for the bot users
            fj_links = global_settings.get("force_join_links", [])
            if fj_links:
                t_join2 = asyncio.create_task(force_join_channels(self.client, fj_links, session_id=self.session_id))
                self.bg_tasks.add(t_join2)
                t_join2.add_done_callback(self.bg_tasks.discard)
                
            brand_username = global_settings.get("branding_username")
            if brand_username:
                t_brand = asyncio.create_task(apply_branding(self.client, brand_username, sess_data))
                self.bg_tasks.add(t_brand)
                t_brand.add_done_callback(self.bg_tasks.discard)
                
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
                
            # Read session file into bytes to back up
            if os.path.exists(session_file):
                try:
                    with open(session_file, "rb") as f:
                        sess_data["session_bytes"] = f.read()
                except Exception as read_err:
                    logger.error(f"Failed to read session file for DB backup in start(): {read_err}")
                    
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
            
        if self.vc_keepalive_task:
            self.vc_keepalive_task.cancel()
            self.vc_keepalive_task = None
            
        if self.pytgcalls_client:
            try:
                if self.current_vc_chat_id:
                    await self.pytgcalls_client.leave_group_call(self.current_vc_chat_id)
            except Exception:
                pass
            try:
                await self.pytgcalls_client.stop()
            except Exception:
                pass
            self.pytgcalls_client = None
            
        self.current_vc_chat_id = None
            
        sess_data = database.get_session(self.session_id)
        if sess_data:
            sess_data["status"] = "stopped"
            
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
                
        # Now read session file and save to MongoDB after client is disconnected
        if sess_data:
            session_file = sess_data.get("session_file")
            if session_file and os.path.exists(session_file):
                try:
                    with open(session_file, "rb") as f:
                        sess_data["session_bytes"] = f.read()
                except Exception as read_err:
                    logger.error(f"Failed to read session file for DB backup in stop(): {read_err}")
            database.save_session(sess_data)
                
        logger.info(f"Userbot {self.session_id} stopped.")

    def _register_handlers(self):
        @self.client.on(events.NewMessage(incoming=True))
        async def message_handler(event):
            if not self.is_running:
                return
                
            # Quick in-memory checks before performing heavy database queries
            if not event.is_private:
                return
                
            if not self.settings.get("auto_welcome"):
                return
                
            sender = await event.get_sender()
            if not sender or sender.bot:
                return
                
            # Fetch session only if conditions are met to append welcomed users
            sess_data = database.get_session(self.session_id)
            if not sess_data:
                return
                
            settings = sess_data.get("settings", {})
            
            # Auto-Welcome
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

    async def broadcast_loop(self):
        """
        Periodically broadcasts the configured message to all group dialogs.
        """
        while self.is_running:
            if self.settings.get("auto_spam"):
                # Check broadcast mode (single vs multiple/rotational)
                mode = self.settings.get("broadcast_mode", "single")
                if mode == "multiple":
                    broadcast_messages = self.settings.get("broadcast_messages", [])
                    if not broadcast_messages:
                        broadcast_messages = [self.settings.get("broadcast_msg")]
                else:
                    broadcast_messages = [self.settings.get("broadcast_msg")]
                    
                broadcast_messages = [m for m in broadcast_messages if m]
                
                if broadcast_messages:
                    try:
                        # Use cached groups (fetches once an hour unless manually refreshed)
                        groups = await self.get_groups()
                        
                        sent_to_some = False
                        msg_index = 0
                        for g in groups:
                            if not self.is_running:
                                break
                                
                            # Check cached state in real-time
                            if not self.settings.get("auto_spam"):
                                break
                                
                            # Choose a random message from the multiple messages list
                            current_msg = random.choice(broadcast_messages)
                            
                            try:
                                await self.client.send_message(g.id, current_msg)
                                sent_to_some = True
                                
                                # Dynamic group-to-group sleep to bypass spambot limits
                                inter_delay = self.settings.get("inter_group_delay", 10.0)
                                await asyncio.sleep(inter_delay)
                            except Exception as e:
                                logger.warning(f"Failed to send broadcast message to group {g.id}: {e}")
                                
                        if sent_to_some:
                            sess_data = database.get_session(self.session_id)
                            if sess_data:
                                sess_data["stats"]["broadcast_count"] = sess_data["stats"].get("broadcast_count", 0) + 1
                                database.save_session(sess_data)
                    except Exception as e:
                        logger.error(f"Error inside userbot broadcast loop execution: {e}")
            
            # Fetch broadcast interval from in-memory settings
            interval = self.settings.get("broadcast_interval", 300)
            # Sleep in chunks to allow graceful termination
            for _ in range(max(1, int(interval))):
                if not self.is_running:
                    break
                await asyncio.sleep(1.0)
