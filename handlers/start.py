import logging
from telethon import events
import database
import models
import config
from utils import styled_button, get_text

logger = logging.getLogger(__name__)

async def check_onboarding(client, event) -> bool:
    """
    Checks if user is onboarded. If not, kicks off the onboarding flow and returns False.
    """
    user_id = event.sender_id
    user = database.get_user(user_id)
    
    if not user:
        user = models.create_default_user(user_id)
        database.save_user(user)
        
    if not user.get("language"):
        # Show Language Selection Buttons
        buttons = [
            [
                styled_button("English 🇬🇧", "set_lang_en", style="primary"),
                styled_button("Hindi 🇮🇳", "set_lang_hi", style="primary"),
                styled_button("Russian 🇷🇺", "set_lang_ru", style="primary")
            ]
        ]
        msg = get_text("select_lang", "en")
        await event.respond(msg, buttons=buttons)
        return False
        
    if not user.get("tos_accepted"):
        # Show TOS Agreement
        lang = user.get("language")
        msg = get_text("tos_text", lang)
        buttons = [
            [styled_button(get_text("tos_accept_btn", lang), "accept_tos", style="success")]
        ]
        await event.respond(msg, buttons=buttons)
        return False
        
    return True

async def show_main_menu(event, user_id):
    """
    Displays the primary bot dashboard containing main actions.
    """
    user = database.get_user(user_id)
    if not user:
        return
        
    lang = user.get("language", "en") or "en"
    import utils
    allowed = utils.get_allowed_slots(user_id)
    sessions = database.get_sessions(user_id)
    used = len(sessions)
    
    text = get_text("main_menu", lang, allowed=allowed, used=used)
    
    global_settings = database.get_global_settings()
    admins_list = global_settings.get("admins", [])
    is_admin = user_id in admins_list or user_id in config.ORIGINAL_ADMIN_IDS
    
    # Configure main menu dashboard buttons
    buttons = [
        [
            styled_button(get_text("btn_add_bot", lang), "menu_add_bot", style="primary"),
            styled_button(get_text("btn_my_bots", lang), "menu_my_bots", style="primary")
        ],
        [
            styled_button(get_text("btn_settings", lang), "menu_settings", style="primary"),
            styled_button(get_text("btn_status", lang), "menu_status", style="primary")
        ]
    ]
    
    if is_admin:
        buttons.append([styled_button(get_text("btn_admin_panel", lang), "menu_admin", style="primary")])
        
    start_image = global_settings.get("start_image")
    try:
        if start_image:
            if hasattr(event, "edit"):
                try:
                    await event.delete()
                except Exception:
                    pass
            await event.respond(text, file=start_image, buttons=buttons)
        else:
            if hasattr(event, "edit"):
                await event.edit(text, buttons=buttons)
            else:
                await event.respond(text, buttons=buttons)
    except Exception as e:
        logger.error(f"Error rendering main menu: {e}")
        await event.respond(text, buttons=buttons)

def register_handlers(client):
    @client.on(events.NewMessage(pattern="/start"))
    async def start_cmd(event):
        if not event.is_private:
            return
            
        user_id = event.sender_id
        ref_id = None
        
        # Parse referral details if present
        if event.text and len(event.text.split()) > 1:
            arg = event.text.split()[1]
            if arg.startswith("ref_"):
                try:
                    ref_id = int(arg.replace("ref_", ""))
                except ValueError:
                    pass
                    
        user = database.get_user(user_id)
        if not user:
            user = models.create_default_user(user_id)
            if ref_id and ref_id != user_id:
                ref_parent = database.get_user(ref_id)
                if ref_parent:
                    user["referred_by"] = ref_id
                    logger.info(f"New user {user_id} referred by parent admin/user {ref_id}")
            database.save_user(user)
            
        # Security verification checks (bans, maintenance, force subscribe)
        import utils
        if await utils.guard(event, client):
            return
            
        onboarded = await check_onboarding(client, event)
        if onboarded:
            await show_main_menu(event, event.sender_id)

    @client.on(events.CallbackQuery(pattern="^menu_start$"))
    async def menu_start_callback(event):
        await event.answer()
        await show_main_menu(event, event.sender_id)

    @client.on(events.CallbackQuery(pattern="^close_menu$"))
    async def close_menu_callback(event):
        await event.answer()
        try:
            await event.delete()
        except Exception:
            pass

    @client.on(events.CallbackQuery(pattern=r"^set_lang_(en|hi|ru)$"))
    async def set_lang_callback(event):
        lang_code = event.pattern_match.group(1)
        user_id = event.sender_id
        
        user = database.get_user(user_id)
        if not user:
            user = models.create_default_user(user_id)
            
        user["language"] = lang_code
        database.save_user(user)
        
        # Respond to callback query
        await event.answer()
        
        # Progress to next step of onboarding (TOS)
        await check_onboarding(client, event)

    @client.on(events.CallbackQuery(pattern="^accept_tos$"))
    async def accept_tos_callback(event):
        user_id = event.sender_id
        user = database.get_user(user_id)
        
        if user:
            user["tos_accepted"] = True
            database.save_user(user)
            
        await event.answer()
        
        # Display congratulations and open main menu
        lang = user.get("language", "en") if user else "en"
        await event.respond(get_text("tos_accepted_msg", lang))
        await show_main_menu(event, user_id)
