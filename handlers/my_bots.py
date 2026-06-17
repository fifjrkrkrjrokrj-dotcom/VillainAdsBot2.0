import logging
import asyncio
from typing import Optional, Set
from telethon import events
import database
import models
import utils
import config
import userbot_manager

logger = logging.getLogger(__name__)

# In-memory dictionary containing active prompt states for user interaction
# Structure: { user_id: { "phone": str, "action": str } }
_bot_action_states = {}

async def show_bots_list(event, user_id: int, flash_message: Optional[str] = None):
    """
    Renders the list of added accounts (UserBots) for the user.
    """
    user = database.get_user(user_id)
    lang = user.get("language", "en") if user else "en"
    
    sessions = database.get_sessions(user_id)
    if not sessions:
        # No bots added yet
        buttons = [[utils.styled_button(utils.get_text("btn_add_bot", lang), "menu_add_bot", style="primary")]]
        buttons.append([utils.styled_button(utils.get_text("back_to_menu", lang), "menu_start", style="primary")])
        text = "📱 **You have not added any UserBots yet.**"
        if flash_message:
            text = f"{flash_message}\n\n" + text
            
        try:
            await event.edit(text, buttons=buttons)
        except Exception:
            await event.respond(text, buttons=buttons)
        return
        
    text = ""
    if flash_message:
        text += f"{flash_message}\n\n"
        
    text += "📱 **Your Connected UserBots**:\n\n"
    buttons = []
    
    for s in sessions:
        phone = s.get("phone")
        # Sync status dynamically
        is_running = userbot_manager.is_bot_running(phone)
        status = "running" if is_running else "stopped"
        if s.get("status") != status:
            s["status"] = status
            database.save_session(s)
            
        status_emoji = "🟢" if status == "running" else "🔴"
        name = s.get("name") or "UserBot"
        username = s.get("username")
        user_display = f"@{username}" if username else phone
        
        text += f"{status_emoji} **{name}** ({user_display})\n"
        
        # Add a selection button for this bot
        buttons.append([
            utils.styled_button(
                f"{status_emoji} {name} ({user_display})", 
                f"select_bot_{phone}", 
                style="primary"
            )
        ])
        
    buttons.append([utils.styled_button(utils.get_text("back_to_menu", lang), "menu_start", style="primary")])
    
    try:
        await event.edit(text, buttons=buttons)
    except Exception:
        await event.respond(text, buttons=buttons)

async def show_bot_dashboard(event, phone: str, user_id: int, flash_message: Optional[str] = None):
    """
    Displays the detailed control dashboard for a single UserBot.
    """
    user = database.get_user(user_id)
    lang = user.get("language", "en") if user else "en"
    
    sess = database.get_session(phone)
    if not sess or sess.get("user_id") != user_id:
        text = "❌ Session not found."
        if flash_message:
            text = f"{flash_message}\n\n" + text
        try:
            await event.edit(text)
        except Exception:
            await event.respond(text)
        return
        
    # Sync status dynamically with manager memory running state
    is_running = userbot_manager.is_bot_running(phone)
    status = "running" if is_running else "stopped"
    
    if sess.get("status") != status:
        sess["status"] = status
        database.save_session(sess)
        
    status_emoji = "🟢" if status == "running" else "🔴"
    status_text = "Running" if status == "running" else "Stopped"
    
    name = sess.get("name") or "UserBot"
    username = sess.get("username") or "None"
    
    settings = sess.get("settings", {})
    auto_spam = "✅ ON" if settings.get("auto_spam") else "❌ OFF"
    auto_welcome = "✅ ON" if settings.get("auto_welcome") else "❌ OFF"
    vc_join = "✅ ON" if settings.get("vc_join") else "❌ OFF"
    tag_reply = "✅ ON" if settings.get("tag_reply") else "❌ OFF"
    gpt_enabled = "✅ ON" if settings.get("gpt_enabled") else "❌ OFF"
    
    text = ""
    if flash_message:
        text += f"{flash_message}\n\n"
        
    text += utils.get_text(
        "bot_dashboard", 
        lang, 
        name=name, 
        username=username, 
        status_emoji=status_emoji, 
        status=status_text
    )
    
    # Configure dashboard buttons
    buttons = []
    
    # Start/Stop Button
    if status == "running":
        buttons.append([utils.styled_button(utils.get_text("btn_stop_bot", lang), f"stop_bot_{phone}", style="danger")])
    else:
        buttons.append([utils.styled_button(utils.get_text("btn_start_bot", lang), f"start_bot_{phone}", style="success")])
        
    buttons.extend([
        [
            utils.styled_button(utils.get_text("btn_set_broadcast", lang), f"set_broadcast_{phone}", style="primary"),
            utils.styled_button(utils.get_text("btn_set_welcome", lang), f"set_welcome_{phone}", style="primary")
        ],
        [
            utils.styled_button(utils.get_text("btn_toggle_spam", lang, state=auto_spam), f"toggle_spam_{phone}", style="primary"),
            utils.styled_button(utils.get_text("btn_toggle_welcome", lang, state=auto_welcome), f"toggle_welcome_{phone}", style="primary")
        ],
        [
            utils.styled_button(utils.get_text("btn_toggle_vc", lang, state=vc_join), f"toggle_vc_{phone}", style="primary"),
            utils.styled_button(utils.get_text("btn_toggle_tag", lang, state=tag_reply), f"toggle_tag_{phone}", style="primary")
        ],
        [
            utils.styled_button(utils.get_text("btn_set_tag_msg", lang), f"set_tag_msg_{phone}", style="primary"),
            utils.styled_button(utils.get_text("btn_change_name", lang), f"change_name_{phone}", style="primary")
        ],
        [
            utils.styled_button(utils.get_text("btn_set_interval", lang), f"set_interval_{phone}", style="primary"),
            utils.styled_button(utils.get_text("btn_toggle_gpt", lang, state=gpt_enabled), f"toggle_gpt_{phone}", style="primary")
        ],
        [
            utils.styled_button(utils.get_text("btn_refresh_stats", lang), f"refresh_stats_{phone}", style="primary"),
            utils.styled_button(utils.get_text("btn_delete_bot", lang), f"delete_bot_{phone}", style="danger")
        ],
        [utils.styled_button(utils.get_text("btn_back_to_bots", lang), "menu_my_bots", style="primary")]
    ])
    
    try:
        await event.edit(text, buttons=buttons)
    except Exception:
        await event.respond(text, buttons=buttons)

def register_handlers(client):
    
    # ------------------ Navigation ------------------
    @client.on(events.CallbackQuery(pattern="^menu_my_bots$"))
    async def bots_list_callback(event):
        await show_bots_list(event, event.sender_id)

    @client.on(events.CallbackQuery(pattern=r"^select_bot_(.+)$"))
    async def select_bot_callback(event):
        phone = event.pattern_match.group(1)
        await show_bot_dashboard(event, phone, event.sender_id)

    # ------------------ Core Controls ------------------
    @client.on(events.CallbackQuery(pattern=r"^start_bot_(.+)$"))
    async def start_bot_callback(event):
        phone = event.pattern_match.group(1)
        user_id = event.sender_id
        
        # Start bot in background
        success = await userbot_manager.start_userbot(phone)
        if success:
            flash = "🟢 **Userbot successfully started!**"
        else:
            flash = "❌ **Failed to start Userbot. Check Telegram session/auth.**"
            
        await show_bot_dashboard(event, phone, user_id, flash_message=flash)

    @client.on(events.CallbackQuery(pattern=r"^stop_bot_(.+)$"))
    async def stop_bot_callback(event):
        phone = event.pattern_match.group(1)
        user_id = event.sender_id
        
        # Stop bot
        await userbot_manager.stop_userbot(phone)
        await show_bot_dashboard(event, phone, user_id, flash_message="🔴 **Userbot stopped.**")

    @client.on(events.CallbackQuery(pattern=r"^delete_bot_(.+)$"))
    async def delete_bot_callback(event):
        phone = event.pattern_match.group(1)
        user_id = event.sender_id
        
        await userbot_manager.remove_userbot(phone)
        await show_bots_list(event, user_id, flash_message="🗑️ **Userbot session successfully deleted.**")

    # ------------------ Toggles ------------------
    @client.on(events.CallbackQuery(pattern=r"^toggle_(spam|welcome|vc|tag|gpt)_(.+)$"))
    async def toggles_callback(event):
        feature = event.pattern_match.group(1)
        phone = event.pattern_match.group(2)
        user_id = event.sender_id
        
        sess = database.get_session(phone)
        flash = None
        if sess and sess.get("user_id") == user_id:
            settings = sess.setdefault("settings", {})
            
            key_map = {
                "spam": "auto_spam",
                "welcome": "auto_welcome",
                "vc": "vc_join",
                "tag": "tag_reply",
                "gpt": "gpt_enabled"
            }
            db_key = key_map[feature]
            settings[db_key] = not settings.get(db_key, False)
            database.save_session(sess)
            
            state_word = "ON" if settings[db_key] else "OFF"
            feature_name = feature.upper()
            flash = f"⚙️ **{feature_name} is now {state_word}**"
            
        await show_bot_dashboard(event, phone, user_id, flash_message=flash)

    # ------------------ Stats Refresh ------------------
    @client.on(events.CallbackQuery(pattern=r"^refresh_stats_(.+)$"))
    async def refresh_stats_callback(event):
        phone = event.pattern_match.group(1)
        user_id = event.sender_id
        
        sess = database.get_session(phone)
        flash = None
        if sess and sess.get("user_id") == user_id:
            if userbot_manager.is_bot_running(phone):
                bot_obj = userbot_manager._running_bots[phone]
                try:
                    dialogs = await bot_obj.client.get_dialogs()
                    groups = [d for d in dialogs if d.is_group]
                    users = sum(1 for d in dialogs if d.is_user)
                    
                    sess["stats"]["group_count"] = len(groups)
                    sess["stats"]["user_count"] = users
                    database.save_session(sess)
                    
                    flash = f"🔄 **Stats refreshed! Groups: {len(groups)} | Contacts: {users}**"
                except Exception as e:
                    logger.error(f"Error refreshing stats: {e}")
                    flash = f"❌ **Error during refresh: {e}**"
            else:
                flash = "⚠️ **Bot must be running to refresh statistics.**"
                
        await show_bot_dashboard(event, phone, user_id, flash_message=flash)

    # ------------------ Text Prompts ------------------
    @client.on(events.CallbackQuery(pattern=r"^set_(broadcast|welcome|tag_msg|name)_(.+)$"))
    async def set_text_callback(event):
        action = event.pattern_match.group(1)
        phone = event.pattern_match.group(2)
        user_id = event.sender_id
        
        user = database.get_user(user_id)
        lang = user.get("language", "en") if user else "en"
        
        _bot_action_states[user_id] = {
            "phone": phone,
            "action": f"WAITING_FOR_{action.upper()}"
        }
        
        prompt_map = {
            "broadcast": "prompt_broadcast",
            "welcome": "prompt_welcome",
            "tag_msg": "prompt_tag",
            "name": "prompt_name"
        }
        
        prompt_text = utils.get_text(prompt_map[action], lang)
        try:
            buttons = [[utils.styled_button("🔙 Cancel", f"select_bot_{phone}", style="primary")]]
            await event.edit(prompt_text, buttons=buttons)
        except Exception:
            await event.respond(prompt_text)

    # ------------------ Interval settings ------------------
    @client.on(events.CallbackQuery(pattern=r"^set_interval_(.+)$"))
    async def set_interval_callback(event):
        phone = event.pattern_match.group(1)
        user_id = event.sender_id
        user = database.get_user(user_id)
        lang = user.get("language", "en") if user else "en"
        
        text = utils.get_text("interval_title", lang)
        
        buttons = [
            [
                utils.styled_button(utils.get_text("btn_int_val", lang, val=300), f"int_val_300_{phone}", style="primary"),
                utils.styled_button(utils.get_text("btn_int_val", lang, val=500), f"int_val_500_{phone}", style="primary"),
                utils.styled_button(utils.get_text("btn_int_val", lang, val=600), f"int_val_600_{phone}", style="primary")
            ],
            [
                utils.styled_button(utils.get_text("btn_int_custom", lang), f"int_custom_{phone}", style="primary"),
                utils.styled_button(utils.get_text("btn_back_to_bots", lang), f"select_bot_{phone}", style="primary")
            ]
        ]
        
        try:
            await event.edit(text, buttons=buttons)
        except Exception:
            await event.respond(text, buttons=buttons)

    @client.on(events.CallbackQuery(pattern=r"^int_val_(\d+)_(.+)$"))
    async def int_val_callback(event):
        val = int(event.pattern_match.group(1))
        phone = event.pattern_match.group(2)
        user_id = event.sender_id
        
        sess = database.get_session(phone)
        flash = None
        if sess and sess.get("user_id") == user_id:
            sess["settings"]["broadcast_interval"] = val
            database.save_session(sess)
            flash = f"⏱️ **Interval updated to {val}s**"
            
        await show_bot_dashboard(event, phone, user_id, flash_message=flash)

    @client.on(events.CallbackQuery(pattern=r"^int_custom_(.+)$"))
    async def int_custom_callback(event):
        phone = event.pattern_match.group(1)
        user_id = event.sender_id
        user = database.get_user(user_id)
        lang = user.get("language", "en") if user else "en"
        
        _bot_action_states[user_id] = {
            "phone": phone,
            "action": "WAITING_FOR_CUSTOM_INTERVAL"
        }
        
        prompt_text = utils.get_text("prompt_custom_interval", lang)
        try:
            buttons = [[utils.styled_button("🔙 Cancel", f"select_bot_{phone}", style="primary")]]
            await event.edit(prompt_text, buttons=buttons)
        except Exception:
            await event.respond(prompt_text)

    # ------------------ Message Input Listeners ------------------
    @client.on(events.NewMessage)
    async def text_input_handler(event):
        if not event.is_private:
            return
            
        user_id = event.sender_id
        if user_id not in _bot_action_states:
            return
            
        if event.text.startswith("/start"):
            _bot_action_states.pop(user_id, None)
            return
            
        state = _bot_action_states.pop(user_id)
        phone = state["phone"]
        action = state["action"]
        
        user = database.get_user(user_id)
        lang = user.get("language", "en") if user else "en"
        
        sess = database.get_session(phone)
        if not sess or sess.get("user_id") != user_id:
            await event.reply("❌ Session error.")
            return
            
        flash = None
        
        # 1. Broadcast Message
        if action == "WAITING_FOR_BROADCAST":
            sess["settings"]["broadcast_msg"] = event.text
            database.save_session(sess)
            flash = "✉️ **Broadcast message updated successfully!**"
            
        # 2. Welcome Message
        elif action == "WAITING_FOR_WELCOME":
            sess["settings"]["welcome_msg"] = event.text
            database.save_session(sess)
            flash = "👋 **Welcome message updated successfully!**"
            
        # 3. Custom Tag Messages
        elif action == "WAITING_FOR_TAG_MSG":
            lines = [l.strip() for l in event.text.split("\n") if l.strip()]
            if lines:
                sess["settings"]["tag_messages"] = lines
                database.save_session(sess)
                flash = "💬 **Tag reply messages updated successfully!**"
            else:
                await event.reply("❌ Input cannot be empty.")
                return
                
        # 4. Change Name
        elif action == "WAITING_FOR_NAME":
            new_name = event.text.strip()
            if new_name:
                sess["name"] = new_name
                database.save_session(sess)
                
                # If running, update profile name
                if userbot_manager.is_bot_running(phone):
                    try:
                        from telethon.tl.functions.account import UpdateProfileRequest
                        bot_obj = userbot_manager._running_bots[phone]
                        await bot_obj.client(UpdateProfileRequest(first_name=new_name))
                    except Exception as e:
                        logger.warning(f"Could not change userbot profile name: {e}")
                        
                flash = f"✏️ **Name updated to: {new_name}**"
            else:
                await event.reply("❌ Name cannot be empty.")
                return
                
        # 5. Custom Interval
        elif action == "WAITING_FOR_CUSTOM_INTERVAL":
            val_str = event.text.strip()
            if val_str.isdigit() and int(val_str) >= 60:
                val = int(val_str)
                sess["settings"]["broadcast_interval"] = val
                database.save_session(sess)
                flash = f"⏱️ **Interval updated to {val}s**"
            else:
                await event.reply(utils.get_text("interval_invalid", lang))
                return
                
        # Return to dashboard showing updated stats and flash notification
        await show_bot_dashboard(event, phone, user_id, flash_message=flash)
