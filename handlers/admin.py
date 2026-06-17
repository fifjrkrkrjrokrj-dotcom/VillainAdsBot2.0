import logging
from telethon import events
import database
import config
import utils

logger = logging.getLogger(__name__)

# In-memory dictionary containing active prompt states for administrator actions
# Structure: { user_id: str } (where value is the WAITING_FOR_... action)
_admin_action_states = {}
_admin_plan_temp = {}

def check_admin(user_id: int) -> bool:
    """
    Checks if a user is an administrator (either defined in config env or DB).
    """
    global_settings = database.get_global_settings()
    admins = global_settings.get("admins", [])
    return user_id in admins or user_id in config.ORIGINAL_ADMIN_IDS

async def show_admin_panel(event, user_id: int):
    """
    Renders the administrator control panel.
    """
    user = database.get_user(user_id)
    lang = user.get("language", "en") if user else "en"
    
    if not check_admin(user_id):
        await event.respond(utils.get_text("error_not_admin", lang))
        return
        
    global_settings = database.get_global_settings()
    maint_text = "🔴 Disable Maintenance" if global_settings.get("maintenance_mode", False) else "🟢 Enable Maintenance"
    
    text = utils.get_text("admin_title", lang)
    buttons = [
        [
            utils.styled_button(utils.get_text("btn_manage_plans", lang), "admin_manage_plans", style="primary"),
            utils.styled_button(utils.get_text("btn_set_fj", lang), "admin_set_fj", style="primary")
        ],
        [
            utils.styled_button(utils.get_text("btn_set_lg", lang), "admin_set_lg", style="primary"),
            utils.styled_button(utils.get_text("btn_set_bu", lang), "admin_set_bu", style="primary")
        ],
        [
            utils.styled_button(utils.get_text("btn_set_bd", lang), "admin_set_bd", style="primary"),
            utils.styled_button(utils.get_text("btn_set_imgs", lang), "admin_set_imgs", style="primary")
        ],
        [
            utils.styled_button("🏦 Set UPI ID", "admin_set_upi", style="primary"),
            utils.styled_button("🪙 Set BEP20 USDT", "admin_set_usdt", style="primary")
        ],
        [
            utils.styled_button("📊 Set Commission", "admin_set_comm", style="primary"),
            utils.styled_button(maint_text, "admin_toggle_maint", style="primary")
        ],
        [
            utils.styled_button(utils.get_text("btn_manage_admins", lang), "admin_manage_admins", style="primary"),
            utils.styled_button(utils.get_text("back_to_menu", lang), "menu_start", style="primary")
        ]
    ]
    
    try:
        await event.edit(text, buttons=buttons)
    except Exception:
        await event.respond(text, buttons=buttons)

def register_handlers(client):
    
    # ------------------ Navigation ------------------
    @client.on(events.NewMessage(pattern="/admin"))
    async def admin_cmd(event):
        if not event.is_private:
            return
        import utils
        if await utils.guard(event, client):
            return
        await show_admin_panel(event, event.sender_id)

    @client.on(events.CallbackQuery(pattern="^menu_admin$"))
    async def admin_menu_callback(event):
        await show_admin_panel(event, event.sender_id)

    @client.on(events.CallbackQuery(pattern="^cancel_admin_plan$"))
    async def cancel_admin_plan_callback(event):
        user_id = event.sender_id
        if not check_admin(user_id):
            return
        _admin_action_states.pop(user_id, None)
        _admin_plan_temp.pop(user_id, None)
        await admin_manage_plans_callback(event)

    @client.on(events.CallbackQuery(pattern="^cancel_admin_setting$"))
    async def cancel_admin_setting_callback(event):
        user_id = event.sender_id
        if not check_admin(user_id):
            return
        _admin_action_states.pop(user_id, None)
        await show_admin_panel(event, user_id)


    @client.on(events.CallbackQuery(pattern="^admin_manage_plans$"))
    async def admin_manage_plans_callback(event):
        user_id = event.sender_id
        user = database.get_user(user_id)
        lang = user.get("language", "en") if user else "en"
        
        if not check_admin(user_id):
            await event.respond(utils.get_text("error_not_admin", lang))
            return
            
        global_settings = database.get_global_settings()
        plans = global_settings.get("subscription_plans", [])
        
        text = "📅 **Subscription Plans Management**\n\nConfigure custom duration-based slot options for your users.\n\n"
        if not plans:
            text += "_No plans configured yet._"
        else:
            text += "**Active Plans:**\n"
            for i, p in enumerate(plans, 1):
                text += f"{i}. **{p.get('button_name')}**\n" \
                        f"   • ID: `{p.get('id')}`\n" \
                        f"   • Duration: **{p.get('days')} days**\n" \
                        f"   • Price/account: **₹{p.get('price'):.2f}**\n\n"
                        
        buttons = [
            [
                utils.styled_button("➕ Add Plan", "admin_add_plan_start", style="success"),
                utils.styled_button("❌ Remove Plan", "admin_remove_plan_start", style="danger")
            ],
            [utils.styled_button("🔙 Back to Admin Panel", "menu_admin", style="primary")]
        ]
        
        try:
            await event.edit(text, buttons=buttons)
        except Exception:
            await event.respond(text, buttons=buttons)

    @client.on(events.CallbackQuery(pattern="^admin_add_plan_start$"))
    async def admin_add_plan_start_callback(event):
        user_id = event.sender_id
        user = database.get_user(user_id)
        lang = user.get("language", "en") if user else "en"
        
        if not check_admin(user_id):
            await event.respond(utils.get_text("error_not_admin", lang))
            return
            
        _admin_action_states[user_id] = "WAITING_FOR_PLAN_DAYS"
        _admin_plan_temp[user_id] = {}
        
        prompt_text = utils.get_text("prompt_plan_days", lang)
        buttons = [[utils.styled_button("🔙 Cancel", "cancel_admin_plan", style="danger")]]
        try:
            await event.edit(prompt_text, buttons=buttons)
        except Exception:
            await event.respond(prompt_text, buttons=buttons)


    @client.on(events.CallbackQuery(pattern="^admin_remove_plan_start$"))
    async def admin_remove_plan_start_callback(event):
        user_id = event.sender_id
        user = database.get_user(user_id)
        lang = user.get("language", "en") if user else "en"
        
        if not check_admin(user_id):
            await event.respond(utils.get_text("error_not_admin", lang))
            return
            
        global_settings = database.get_global_settings()
        plans = global_settings.get("subscription_plans", [])
        
        if not plans:
            buttons = [[utils.styled_button("🔙 Back to Plans", "admin_manage_plans", style="primary")]]
            await event.respond("❌ **No subscription plans are currently configured.**", buttons=buttons)
            return
            
        text = "❌ **Select Plan to Remove**\n\nTap on any plan button below to delete it immediately:"
        buttons = []
        for plan in plans:
            btn_label = f"🗑️ {plan['button_name']} (₹{plan['price']:.0f} / {plan['days']} days)"
            buttons.append([
                utils.styled_button(btn_label, f"admin_remplan_id_{plan['id']}", style="danger")
            ])
        buttons.append([utils.styled_button("🔙 Back to Plans", "admin_manage_plans", style="primary")])
        
        try:
            await event.edit(text, buttons=buttons)
        except Exception:
            await event.respond(text, buttons=buttons)

    @client.on(events.CallbackQuery(pattern=r"^admin_remplan_id_(.+)$"))
    async def admin_remplan_id_callback(event):
        user_id = event.sender_id
        user = database.get_user(user_id)
        lang = user.get("language", "en") if user else "en"
        
        if not check_admin(user_id):
            await event.respond(utils.get_text("error_not_admin", lang))
            return
            
        plan_id = event.pattern_match.group(1)
        
        global_settings = database.get_global_settings()
        plans = global_settings.get("subscription_plans", [])
        original_len = len(plans)
        global_settings["subscription_plans"] = [p for p in plans if p["id"] != plan_id]
        
        if len(global_settings["subscription_plans"]) < original_len:
            database.save_global_settings(global_settings)
            await event.answer("✅ Plan removed successfully!", alert=True)
        else:
            await event.answer("❌ Plan ID not found.", alert=True)
            
        await admin_remove_plan_start_callback(event)

    @client.on(events.CallbackQuery(pattern="^admin_manage_admins$"))
    async def manage_admins_menu(event):
        user_id = event.sender_id
        user = database.get_user(user_id)
        lang = user.get("language", "en") if user else "en"
        
        if not check_admin(user_id):
            await event.respond(utils.get_text("error_not_admin", lang))
            return
            
        text = "👥 **Administrator Management**\n\nChoose an option below:"
        buttons = [
            [
                utils.styled_button("➕ Add Admin", "admin_add_admin", style="success"),
                utils.styled_button("➖ Remove Admin", "admin_rem_admin", style="danger")
            ],
            [utils.styled_button("🔙 Back to Admin Panel", "menu_admin", style="primary")]
        ]
        await event.respond(text, buttons=buttons)

    # ------------------ Button Actions ------------------
    @client.on(events.CallbackQuery(pattern="^admin_toggle_maint$"))
    async def admin_toggle_maint_callback(event):
        user_id = event.sender_id
        if not check_admin(user_id):
            return
            
        global_settings = database.get_global_settings()
        global_settings["maintenance_mode"] = not global_settings.get("maintenance_mode", False)
        database.save_global_settings(global_settings)
        
        status_word = "enabled" if global_settings["maintenance_mode"] else "disabled"
        await event.answer(f"🔧 Maintenance Mode is now {status_word}.", alert=True)
        await show_admin_panel(event, user_id)

    @client.on(events.CallbackQuery(pattern=r"^admin_(set_(price|fj|lg|bu|bd|imgs|upi|usdt|comm)|add_admin|rem_admin)$"))
    async def admin_setting_callback(event):
        action = event.pattern_match.group(1)
        user_id = event.sender_id
        user = database.get_user(user_id)
        lang = user.get("language", "en") if user else "en"
        
        if not check_admin(user_id):
            await event.respond(utils.get_text("error_not_admin", lang))
            return
            
        # Register prompt state
        _admin_action_states[user_id] = f"WAITING_FOR_{action.upper()}"
        
        # Select prompt message key
        prompt_keys = {
            "set_price": "prompt_set_price",
            "set_fj": "prompt_set_fj",
            "set_lg": "prompt_set_lg",
            "set_bu": "prompt_set_bu",
            "set_bd": "prompt_set_bd",
            "set_imgs": "prompt_set_imgs",
            "set_upi": "prompt_set_upi",
            "set_usdt": "prompt_set_usdt",
            "set_comm": "prompt_set_comm",
            "add_admin": "prompt_add_admin",
            "rem_admin": "prompt_rem_admin"
        }
        
        prompt_key = prompt_keys.get(action, "error_generic")
        
        # Custom prompt display helper
        if action == "set_upi":
            prompt_text = "🏦 Send the new Admin UPI ID (e.g. `merchant@upi`):"
        elif action == "set_usdt":
            prompt_text = "🪙 Send the new USDT BEP20 wallet address:"
        elif action == "set_comm":
            prompt_text = "📊 Send the new referral commission rate (0.01 - 0.99 for 1%-99%):"
        else:
            prompt_text = utils.get_text(prompt_key, lang)
            
        buttons = [[utils.styled_button("🔙 Cancel", "cancel_admin_setting", style="danger")]]
        try:
            await event.edit(prompt_text, buttons=buttons)
        except Exception:
            await event.respond(prompt_text, buttons=buttons)


    # ------------------ Admin Message Input Listener ------------------
    @client.on(events.NewMessage)
    async def admin_text_input_handler(event):
        if not event.is_private:
            return
            
        user_id = event.sender_id
        if user_id not in _admin_action_states:
            return
            
        if event.text.startswith("/start"):
            _admin_action_states.pop(user_id, None)
            _admin_plan_temp.pop(user_id, None)
            return
            
        action = _admin_action_states.pop(user_id)
        user = database.get_user(user_id)
        lang = user.get("language", "en") if user else "en"
        
        if not check_admin(user_id):
            await event.reply(utils.get_text("error_not_admin", lang))
            return
            
        global_settings = database.get_global_settings()
        success = False
        val_str = event.text.strip()
        
        try:
            # 0.1 Plan Days
            if action == "WAITING_FOR_PLAN_DAYS":
                days = int(val_str)
                if days <= 0:
                    raise ValueError("Days must be positive")
                _admin_plan_temp.setdefault(user_id, {})["days"] = days
                _admin_action_states[user_id] = "WAITING_FOR_PLAN_PRICE"
                buttons = [[utils.styled_button("🔙 Cancel", "cancel_admin_plan", style="danger")]]
                await event.reply(utils.get_text("prompt_plan_price", lang), buttons=buttons)
                return
                
            # 0.2 Plan Price
            elif action == "WAITING_FOR_PLAN_PRICE":
                price = float(val_str)
                if price <= 0:
                    raise ValueError("Price must be positive")
                _admin_plan_temp.setdefault(user_id, {})["price"] = price
                _admin_action_states[user_id] = "WAITING_FOR_PLAN_NAME"
                buttons = [[utils.styled_button("🔙 Cancel", "cancel_admin_plan", style="danger")]]
                await event.reply(utils.get_text("prompt_plan_name", lang), buttons=buttons)
                return

                
            # 0.3 Plan Name
            elif action == "WAITING_FOR_PLAN_NAME":
                name = val_str
                if not name:
                    raise ValueError("Name cannot be empty")
                
                temp_data = _admin_plan_temp.pop(user_id, None)
                if not temp_data or "days" not in temp_data or "price" not in temp_data:
                    await event.reply("❌ State lost. Please start over.")
                    # Show manage plans sub-menu
                    class MockEvent:
                        def __init__(self, uid, ev):
                            self.sender_id = uid
                            self.respond = ev.respond
                            self.edit = ev.respond
                        async def answer(self, *args, **kwargs):
                            pass
                    await admin_manage_plans_callback(MockEvent(user_id, event))
                    return
                    
                days = temp_data["days"]
                price = temp_data["price"]
                
                import uuid
                plan_id = "plan_" + str(uuid.uuid4())[:6]
                
                plans = global_settings.setdefault("subscription_plans", [])
                plans.append({
                    "id": plan_id,
                    "days": days,
                    "price": price,
                    "button_name": name
                })
                database.save_global_settings(global_settings)
                
                await event.reply(
                    f"✅ **Subscription Plan Added Successfully!**\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Plan ID: `{plan_id}`\n"
                    f"Name: **{name}**\n"
                    f"Days: **{days}**\n"
                    f"Price per account: **₹{price:.2f}**"
                )
                
                # Show manage plans sub-menu
                class MockEvent:
                    def __init__(self, uid, ev):
                        self.sender_id = uid
                        self.respond = ev.respond
                        self.edit = ev.respond
                    async def answer(self, *args, **kwargs):
                        pass
                await admin_manage_plans_callback(MockEvent(user_id, event))
                return

            # 1. Set global Price per extra ID
            elif action == "WAITING_FOR_SET_PRICE":
                global_settings["price_per_id"] = float(val_str)
                success = True
                
            # 2. Set Force Join channels
            elif action == "WAITING_FOR_SET_FJ":
                if val_str.lower() == "none":
                    global_settings["force_join_links"] = []
                else:
                    global_settings["force_join_links"] = [x.strip() for x in val_str.split(",") if x.strip()]
                success = True
                
            # 3. Set log group ID
            elif action == "WAITING_FOR_SET_LG":
                # Must be an integer ID
                global_settings["log_group_id"] = int(val_str)
                success = True
                
            # 4. Set branding username
            elif action == "WAITING_FOR_SET_BU":
                if val_str.lower() == "none":
                    global_settings["branding_username"] = None
                else:
                    # Strip @ if present
                    global_settings["branding_username"] = val_str.replace("@", "")
                success = True
                
            # 5. Set branding duration
            elif action == "WAITING_FOR_SET_BD":
                global_settings["branding_duration"] = int(val_str)
                success = True
                
            # 6. Set Images (Start, Ping, Help)
            elif action == "WAITING_FOR_SET_IMGS":
                parts = [p.strip() for p in val_str.split(",") if p.strip()]
                if len(parts) == 3:
                    global_settings["start_image"] = parts[0] if parts[0].lower() != "none" else None
                    global_settings["ping_image"] = parts[1] if parts[1].lower() != "none" else None
                    global_settings["help_image"] = parts[2] if parts[2].lower() != "none" else None
                    success = True
                else:
                    raise ValueError("Must provide 3 comma-separated File IDs (or 'none').")
                    
            # 6.1 Set UPI ID
            elif action == "WAITING_FOR_SET_UPI":
                global_settings["upi_id"] = val_str
                success = True
                
            # 6.2 Set USDT BEP20 address
            elif action == "WAITING_FOR_SET_USDT":
                global_settings["usdt_bep20_address"] = val_str
                success = True
                
            # 6.3 Set referral commission
            elif action == "WAITING_FOR_SET_COMM":
                val = float(val_str)
                if 0.0 <= val <= 1.0:
                    global_settings["referral_commission"] = val
                    success = True
                else:
                    raise ValueError("Commission must be between 0.0 and 1.0")
                    
            # 7. Add Administrator
            elif action == "WAITING_FOR_ADD_ADMIN":
                new_admin = int(val_str)
                admins_list = global_settings.setdefault("admins", [])
                if new_admin not in admins_list:
                    admins_list.append(new_admin)
                success = True
                
            # 8. Remove Administrator
            elif action == "WAITING_FOR_REM_ADMIN":
                rem_admin = int(val_str)
                if rem_admin in config.ORIGINAL_ADMIN_IDS:
                    await event.reply("❌ Original administrators cannot be removed.")
                else:
                    admins_list = global_settings.setdefault("admins", [])
                    if rem_admin in admins_list:
                        admins_list.remove(rem_admin)
                    success = True
                    
        except Exception as e:
            logger.error(f"Failed to update admin settings: {e}")
            await event.reply(utils.get_text("admin_invalid", lang))
            
        if success:
            database.save_global_settings(global_settings)
            await event.reply(utils.get_text("admin_updated", lang))
            
        # Return to admin panel
        await show_admin_panel(event, user_id)
