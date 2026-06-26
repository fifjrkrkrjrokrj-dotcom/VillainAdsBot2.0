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

async def show_mock_dashboard(event, user_id: int, flash_message: Optional[str] = None):
    """
    Renders a mock UserBot control dashboard for unlogged users.
    """
    user = database.get_user(user_id)
    lang = user.get("language", "en") if user else "en"
    
    text = ""
    if flash_message:
        text += f"{flash_message}\n\n"
        
    text += f"🤖 **UserBot Dashboard** (Demo Mode)\nStatus: 🔴 **Stopped / Not Logged In**\n\n__Choose an option below to manage this bot's services:__\n\n⚠️ **{utils.get_text('account_login_first', lang)}**"
    
    buttons = [
        [
            utils.styled_button("➕ Add / Login Bot", "menu_add_bot", style="success")
        ],
        [
            utils.styled_button(utils.get_text("btn_start_bot", lang), "no_login_start", style="success"),
            utils.styled_button(utils.get_text("btn_stop_bot", lang), "no_login_stop", style="danger")
        ],
        [
            utils.styled_button(utils.get_text("btn_set_broadcast", lang), "no_login_broadcast", style="primary"),
            utils.styled_button(utils.get_text("btn_set_welcome", lang), "no_login_welcome", style="primary")
        ],
        [
            utils.styled_button(utils.get_text("btn_toggle_spam", lang, state="❌ OFF"), "no_login_spam", style="primary"),
            utils.styled_button(utils.get_text("btn_toggle_welcome", lang, state="❌ OFF"), "no_login_welcome_toggle", style="primary")
        ],
        [
            utils.styled_button(utils.get_text("btn_clone_profile", lang), "no_login_clone", style="primary")
        ],
        [
            utils.styled_button(utils.get_text("btn_help", lang), "help_bot_no_login", style="primary"),
            utils.styled_button(utils.get_text("btn_how_to_use", lang), "how_to_use_no_login", style="primary")
        ],
        [
            utils.styled_button(utils.get_text("btn_change_name", lang), "no_login_name", style="primary"),
            utils.styled_button(utils.get_text("btn_set_interval", lang), "no_login_interval", style="primary")
        ],
        [
            utils.styled_button(utils.get_text("btn_refresh_stats", lang), "no_login_stats", style="primary"),
            utils.styled_button(utils.get_text("btn_delete_bot", lang), "no_login_delete", style="danger")
        ],
        [
            utils.styled_button(utils.get_text("back_to_menu", lang), "menu_start", style="primary")
        ]
    ]
    
    try:
        if hasattr(event, "edit"):
            await event.edit(text, buttons=buttons)
        else:
            await event.respond(text, buttons=buttons)
    except Exception:
        await event.respond(text, buttons=buttons)

async def show_bots_list(event, user_id: int, flash_message: Optional[str] = None):
    """
    Renders the list of added accounts (UserBots) for the user.
    """
    user = database.get_user(user_id)
    lang = user.get("language", "en") if user else "en"
    
    sessions = database.get_sessions(user_id)
    if not sessions:
        await show_mock_dashboard(event, user_id, flash_message)
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
    try:
        user = database.get_user(user_id)
        lang = user.get("language", "en") if user else "en"
        
        sess = database.get_session(phone)
        if not sess or str(sess.get("user_id")) != str(user_id):
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
        rows = []
        
        # Row 0: Start, Stop and Restart side-by-side
        rows.append([
            ("btn_start_bot", f"start_bot_{phone}"),
            ("btn_stop_bot", f"stop_bot_{phone}"),
            ("btn_restart_bot", f"restart_bot_{phone}")
        ])
            
        # Row 1: Set Broadcast, Set Welcome
        rows.append([
            ("btn_set_broadcast", f"set_broadcast_{phone}"),
            ("btn_set_welcome", f"set_welcome_{phone}")
        ])
        
        # Row 2: Auto-Spam, Auto-Welcome
        rows.append([
            ("btn_toggle_spam", f"toggle_spam_{phone}", auto_spam),
            ("btn_toggle_welcome", f"toggle_welcome_{phone}", auto_welcome)
        ])
        
        # Row 3: Clone Profile (New!)
        rows.append([
            ("btn_clone_profile", f"clone_profile_{phone}")
        ])
        
        # Row 4: Help, How to Use & Settings Info
        rows.append([
            ("btn_help", f"help_bot_{phone}"),
            ("btn_how_to_use", f"how_to_use_{phone}"),
            ("btn_settings_info", f"view_settings_info_{phone}")
        ])

        # Row 5: Change Name, Set Interval
        rows.append([
            ("btn_change_name", f"change_name_{phone}"),
            ("btn_set_interval", f"set_interval_{phone}")
        ])
        
        # Row 6: Refresh Stats, Delete Bot
        rows.append([
            ("btn_refresh_stats", f"refresh_stats_{phone}"),
            ("btn_delete_bot", f"delete_bot_{phone}", None, "danger")
        ])
        
        # Row 7: Back to Bots
        rows.append([
            ("btn_back_to_bots", "menu_my_bots", None, "primary")
        ])


        styles = ["success", "danger", "primary"]
        for i, row in enumerate(rows):
            row_style = styles[i % len(styles)]
            row_buttons = []
            for item in row:
                key = item[0]
                callback = item[1]
                state = item[2] if len(item) > 2 else None
                override_style = item[3] if len(item) > 3 else None
                
                if key == "btn_start_bot":
                    style = "success"
                elif key in ("btn_stop_bot", "btn_delete_bot"):
                    style = "danger"
                elif key == "btn_restart_bot":
                    style = "warning"
                elif override_style:
                    style = override_style
                else:
                    style = row_style
                    
                if state is not None:
                    label = utils.get_text(key, lang, state=state)
                else:
                    label = utils.get_text(key, lang)
                    
                row_buttons.append(utils.styled_button(label, callback, style=style))
            buttons.append(row_buttons)
        
        try:
            await event.edit(text, buttons=buttons)
        except Exception:
            await event.respond(text, buttons=buttons)
            
    except Exception as e:
        logger.exception("Error rendering bot dashboard")
        err_msg = f"❌ **Error rendering dashboard:** {e}"
        try:
            await event.edit(err_msg)
        except Exception:
            await event.respond(err_msg)

def register_handlers(client):
    
    # ------------------ New Features / Handlers ------------------
    @client.on(events.CallbackQuery(pattern="^no_login_"))
    async def no_login_callback(event):
        user_id = event.sender_id
        user = database.get_user(user_id)
        lang = user.get("language", "en") if user else "en"
        alert_text = utils.get_text("account_login_first", lang)
        await event.answer(alert_text, alert=True)

    @client.on(events.CallbackQuery(pattern=r"^help_bot_(.+)$"))
    async def help_bot_callback(event):
        phone = event.pattern_match.group(1)
        user_id = event.sender_id
        user = database.get_user(user_id)
        lang = user.get("language", "en") if user else "en"
        text = utils.get_text("help_dashboard_text", lang)
        buttons = [[utils.styled_button("🔙 Back", f"select_bot_{phone}", style="primary")]]
        
        global_settings = database.get_global_settings()
        help_image = global_settings.get("help_image")
        try:
            if help_image:
                await event.respond(text, file=help_image, buttons=buttons)
            else:
                await event.edit(text, buttons=buttons)
        except Exception:
            await event.respond(text, buttons=buttons)

    @client.on(events.CallbackQuery(pattern=r"^how_to_use_(.+)$"))
    async def how_to_use_callback(event):
        phone = event.pattern_match.group(1)
        user_id = event.sender_id
        user = database.get_user(user_id)
        lang = user.get("language", "en") if user else "en"
        text = utils.get_text("how_to_use_text", lang)
        buttons = [[utils.styled_button("🔙 Back", f"select_bot_{phone}", style="primary")]]
        try:
            await event.edit(text, buttons=buttons)
        except Exception:
            await event.respond(text, buttons=buttons)

    @client.on(events.CallbackQuery(pattern="^help_bot_no_login$"))
    async def help_bot_no_login_callback(event):
        user_id = event.sender_id
        user = database.get_user(user_id)
        lang = user.get("language", "en") if user else "en"
        text = utils.get_text("help_dashboard_text", lang)
        buttons = [[utils.styled_button("🔙 Back", "menu_my_bots", style="primary")]]
        
        global_settings = database.get_global_settings()
        help_image = global_settings.get("help_image")
        try:
            if help_image:
                await event.respond(text, file=help_image, buttons=buttons)
            else:
                await event.edit(text, buttons=buttons)
        except Exception:
            await event.respond(text, buttons=buttons)

    @client.on(events.CallbackQuery(pattern="^how_to_use_no_login$"))
    async def how_to_use_no_login_callback(event):
        user_id = event.sender_id
        user = database.get_user(user_id)
        lang = user.get("language", "en") if user else "en"
        text = utils.get_text("how_to_use_text", lang)
        buttons = [[utils.styled_button("🔙 Back", "menu_my_bots", style="primary")]]
        try:
            await event.edit(text, buttons=buttons)
        except Exception:
            await event.respond(text, buttons=buttons)

    @client.on(events.CallbackQuery(pattern=r"^clone_profile_(.+)$"))
    async def clone_profile_callback(event):
        phone = event.pattern_match.group(1)
        user_id = event.sender_id
        user = database.get_user(user_id)
        lang = user.get("language", "en") if user else "en"
        
        if not userbot_manager.is_bot_running(phone):
            await event.answer("⚠️ Userbot must be running to clone a profile.", alert=True)
            return
            
        text = (
            "👤 **Profile Cloning Options**\n\n"
            "Choose which aspect of the target profile you would like to clone to your Userbot:"
        )
        
        sess = database.get_session(phone)
        buttons = [
            [
                utils.styled_button("👤 Complete Profile Clone", f"clone_opt_complete_{phone}", style="success")
            ],
            [
                utils.styled_button("✏️ Clone Name Only", f"clone_opt_name_{phone}", style="primary"),
                utils.styled_button("📝 Clone Bio Only", f"clone_opt_bio_{phone}", style="primary")
            ],
            [
                utils.styled_button("🖼️ Clone Photo Only", f"clone_opt_photo_{phone}", style="primary")
            ]
        ]
        
        if sess and "original_first_name" in sess:
            buttons.append([utils.styled_button("🔄 Return to Original Profile", f"restore_profile_{phone}", style="success")])
            
        buttons.append([utils.styled_button("🔙 Back", f"select_bot_{phone}", style="danger")])
        
        try:
            await event.edit(text, buttons=buttons)
        except Exception:
            await event.respond(text, buttons=buttons)

    @client.on(events.CallbackQuery(pattern=r"^clone_opt_(complete|name|bio|photo)_(.+)$"))
    async def clone_opt_callback(event):
        clone_type = event.pattern_match.group(1)
        phone = event.pattern_match.group(2)
        user_id = event.sender_id
        
        if not userbot_manager.is_bot_running(phone):
            await event.answer("⚠️ Userbot must be running to clone a profile.", alert=True)
            return
            
        _bot_action_states[user_id] = {
            "phone": phone,
            "action": "WAITING_FOR_CLONE_TARGET",
            "clone_type": clone_type
        }
        
        type_display = {
            "complete": "Complete Profile",
            "name": "Name Only",
            "bio": "Bio Only",
            "photo": "Photo Only"
        }.get(clone_type, "Complete Profile")
        
        prompt_text = (
            f"👤 **Clone Profile ({type_display})**\n\n"
            f"Enter the username (e.g. `@username` or `username`) or User ID of the target profile you want to clone:"
        )
        
        buttons = [[utils.styled_button("🔙 Cancel", f"clone_profile_{phone}", style="danger")]]
        
        try:
            await event.edit(prompt_text, buttons=buttons)
        except Exception:
            await event.respond(prompt_text, buttons=buttons)

    @client.on(events.CallbackQuery(pattern=r"^restore_profile_(.+)$"))
    async def restore_profile_callback(event):
        phone = event.pattern_match.group(1)
        user_id = event.sender_id
        
        if not userbot_manager.is_bot_running(phone):
            await event.answer("⚠️ Userbot must be running to restore a profile.", alert=True)
            return
            
        progress_msg = await event.reply("⏳ **Restoring original profile, please wait...**")
        success, msg = await userbot_manager.restore_original_profile(phone)
        await progress_msg.delete()
        
        if success:
            flash = f"✅ **Profile restored!**\n{msg}"
        else:
            flash = f"❌ **Restoration failed:** {msg}"
            
        await show_bot_dashboard(event, phone, user_id, flash_message=flash)

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

    @client.on(events.CallbackQuery(pattern=r"^restart_bot_(.+)$"))
    async def restart_bot_callback(event):
        phone = event.pattern_match.group(1)
        user_id = event.sender_id
        
        # Stop
        await userbot_manager.stop_userbot(phone)
        # Start
        success = await userbot_manager.start_userbot(phone)
        if success:
            flash = "🔄 **Userbot successfully restarted!**"
        else:
            flash = "❌ **Failed to start Userbot after stopping.**"
            
        await show_bot_dashboard(event, phone, user_id, flash_message=flash)

    @client.on(events.CallbackQuery(pattern=r"^view_settings_info_(.+)$"))
    async def view_settings_info_callback(event):
        phone = event.pattern_match.group(1)
        user_id = event.sender_id
        
        sess = database.get_session(phone)
        if not sess or str(sess.get("user_id")) != str(user_id):
            await event.answer("❌ Session error.", alert=True)
            return
            
        settings = sess.get("settings", {})
        
        spam_status = "🟢 ON" if settings.get("auto_spam") else "🔴 OFF"
        welcome_status = "🟢 ON" if settings.get("auto_welcome") else "🔴 OFF"
        interval = settings.get("broadcast_interval", 300)
        spam_msg = settings.get("broadcast_msg", "None")
        welcome_msg = settings.get("welcome_msg", "None")
        
        # Format a clean message
        text = (
            f"ℹ️ **UserBot Settings Info**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📞 Account: `{phone}`\n"
            f"🏷️ Name: **{sess.get('name', 'Userbot')}**\n"
            f"🔗 Username: @{sess.get('username', 'None')}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📢 **Auto-Spam Settings**:\n"
            f"• Status: {spam_status}\n"
            f"• Interval: **{interval} seconds**\n"
            f"• Broadcast Message:\n"
            f"  `{spam_msg}`\n\n"
            f"👋 **Auto-Welcome Settings**:\n"
            f"• Status: {welcome_status}\n"
            f"• Welcome Message:\n"
            f"  `{welcome_msg}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"_Use the dashboard controls to edit these values._"
        )
        
        buttons = [[utils.styled_button("🔙 Back to Dashboard", f"select_bot_{phone}", style="primary")]]
        try:
            await event.edit(text, buttons=buttons)
        except Exception:
            await event.respond(text, buttons=buttons)

    @client.on(events.CallbackQuery(pattern=r"^delete_bot_(.+)$"))
    async def delete_bot_callback(event):
        phone = event.pattern_match.group(1)
        user_id = event.sender_id
        
        await userbot_manager.remove_userbot(phone)
        await show_bots_list(event, user_id, flash_message="🗑️ **Userbot session successfully deleted.**")

    # ------------------ Toggles ------------------
    @client.on(events.CallbackQuery(pattern=r"^toggle_(spam|welcome)_(.+)$"))
    async def toggles_callback(event):
        feature = event.pattern_match.group(1)
        phone = event.pattern_match.group(2)
        user_id = event.sender_id
        
        sess = database.get_session(phone)
        flash = None
        if sess and str(sess.get("user_id")) == str(user_id):
            settings = sess.setdefault("settings", {})
            
            key_map = {
                "spam": "auto_spam",
                "welcome": "auto_welcome"
            }
            db_key = key_map[feature]
            settings[db_key] = not settings.get(db_key, False)
            database.save_session(sess)
            userbot_manager.reload_bot_settings(phone)
            
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
        if sess and str(sess.get("user_id")) == str(user_id):
            if userbot_manager.is_bot_running(phone):
                bot_obj = userbot_manager._running_bots[phone]
                try:
                    # Force refresh the groups cache, which also updates the DB stats
                    groups = await bot_obj.get_groups(force_refresh=True)
                    sess = database.get_session(phone)
                    users = sess["stats"]["user_count"]
                    
                    flash = f"🔄 **Stats refreshed! Groups: {len(groups)} | Contacts: {users}**"
                except Exception as e:
                    logger.error(f"Error refreshing stats: {e}")
                    flash = f"❌ **Error during refresh: {e}**"
            else:
                flash = "⚠️ **Bot must be running to refresh statistics.**"
                
        await show_bot_dashboard(event, phone, user_id, flash_message=flash)

    # ------------------ Text Prompts ------------------
    @client.on(events.CallbackQuery(pattern=r"^set_(broadcast|welcome|name)_(.+)$"))
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
        if sess and str(sess.get("user_id")) == str(user_id):
            sess["settings"]["broadcast_interval"] = val
            database.save_session(sess)
            userbot_manager.reload_bot_settings(phone)
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
        if not sess or str(sess.get("user_id")) != str(user_id):
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
            
        # 3. Clone Profile
        elif action == "WAITING_FOR_CLONE_TARGET":
            target = event.text.strip()
            if not target:
                await event.reply("❌ Target cannot be empty. Please enter a valid username/ID.")
                return
                
            clone_type = state.get("clone_type", "complete")
            progress_msg = await event.reply("⏳ **Cloning profile details, please wait...**")
            success, msg = await userbot_manager.clone_profile(phone, target, clone_type=clone_type)
            await progress_msg.delete()
            
            if success:
                flash = f"✅ **Profile successfully cloned!**\n{msg}"
            else:
                flash = f"❌ **Cloning failed:** {msg}"

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
        userbot_manager.reload_bot_settings(phone)
        await show_bot_dashboard(event, phone, user_id, flash_message=flash)
