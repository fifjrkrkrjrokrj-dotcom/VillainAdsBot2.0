import logging
import time
import secrets
import asyncio
from telethon import events, Button
import database
import models
import config
import utils

logger = logging.getLogger(__name__)

# State cache for payments and coupons
# Structure: { user_id: { "payment_id": str, "method": str, "step": str } }
_payment_user_states = {}

def is_admin(user_id: int) -> bool:
    global_settings = database.get_global_settings()
    admins = global_settings.get("admins", [])
    return user_id in admins or user_id in config.ORIGINAL_ADMIN_IDS

def register_handlers(client):
    
    # ==================== Force Subscribe Verification ====================
    @client.on(events.CallbackQuery(pattern="^verify_sub$"))
    async def verify_sub_callback(event):
        user_id = event.sender_id
        user = database.get_user(user_id)
        lang = user.get("language", "en") if user else "en"
        
        not_joined = await utils.check_force_sub(client, user_id)
        if not_joined:
            # Re-render check-join warning popup and message
            await event.answer(utils.get_text("tos_blocked_msg", lang), alert=True)
            
            buttons = []
            for i, ch in enumerate(not_joined, 1):
                label = ch.get("channel_name") or f"Channel {i}"
                buttons.append([Button.url(f"➕ Join {label}", url=ch.get("channel_link"))])
            buttons.append([utils.styled_button("✅ I've Joined — Verify", "verify_sub", style="success")])
            
            lines = [
                "❌ **Still not joined all channels!**\n━━━━━━━━━━━━━━━━━━━━\nJoin these channels to continue:\n"
            ]
            for ch in not_joined:
                lines.append(f"• {ch.get('channel_name') or ch.get('channel_id')}")
            lines.append("\n━━━━━━━━━━━━━━━━━━━━\n_Tap Verify after joining._")
            
            try:
                await event.edit("\n".join(lines), buttons=buttons)
            except Exception:
                pass
        else:
            await event.answer("✅ Verification successful!", alert=True)
            try:
                await event.delete()
            except Exception:
                pass
            # Check onboarding next (Language & TOS)
            from handlers.start import show_main_menu
            await show_main_menu(event, user_id)

    # ==================== Redeem Coupon System ====================
    @client.on(events.CallbackQuery(pattern="^settings_redeem_coupon$"))
    async def redeem_coupon_prompt(event):
        user_id = event.sender_id
        user = database.get_user(user_id)
        lang = user.get("language", "en") if user else "en"
        
        _payment_user_states[user_id] = {"action": "WAITING_FOR_COUPON"}
        
        text = (
            "🎟️ **Redeem Coupon**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Enter your coupon code below to credit your wallet:"
        )
        buttons = [[utils.styled_button("🔙 Cancel", "menu_settings", style="danger")]]
        await event.respond(text, buttons=buttons)
        try:
            await event.delete()
        except Exception:
            pass

    @client.on(events.NewMessage)
    async def coupon_input_handler(event):
        if not event.is_private:
            return
        user_id = event.sender_id
        if user_id not in _payment_user_states or _payment_user_states[user_id].get("action") != "WAITING_FOR_COUPON":
            return
            
        if event.text.startswith("/start"):
            _payment_user_states.pop(user_id, None)
            return
            
        _payment_user_states.pop(user_id, None)
        code = event.text.strip().upper()
        
        user = database.get_user(user_id)
        lang = user.get("language", "en") if user else "en"
        
        coupon = database.get_coupon(code)
        if not coupon or not coupon.get("is_active"):
            await event.reply("❌ Invalid or expired coupon code.")
            return
            
        if coupon.get("current_uses", 0) >= coupon.get("max_uses", 1):
            await event.reply("❌ This coupon has reached its maximum uses.")
            return
            
        if database.has_used_coupon(code, user_id):
            await event.reply("❌ You have already used this coupon code.")
            return
            
        # Apply Coupon
        amount = coupon.get("amount_inr", 0.0)
        coupon["current_uses"] = coupon.get("current_uses", 0) + 1
        if coupon["current_uses"] >= coupon["max_uses"]:
            coupon["is_active"] = False
            
        database.save_coupon(coupon)
        database.save_coupon_usage(code, user_id)
        
        # Credit wallet balance
        user["wallet_balance"] = user.get("wallet_balance", 0.0) + amount
        database.save_user(user)
        
        await event.reply(
            f"🎉 **Coupon Redeemed Successfully!**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Amount: **₹{amount:.2f}** has been credited to your wallet balance."
        )
        # Return to settings
        from handlers.settings import show_settings_menu
        await show_settings_menu(event, user_id)

    # ==================== Referrals Dashboard ====================
    @client.on(events.CallbackQuery(pattern="^settings_referrals$"))
    async def referrals_dashboard_callback(event):
        user_id = event.sender_id
        user = database.get_user(user_id)
        lang = user.get("language", "en") if user else "en"
        
        # Calculate stats
        referred_count = database.count_referred_users(user_id)
        earnings = user.get("referral_earnings", 0.0)
        
        # Generate referral link
        me = await client.get_me()
        bot_username = me.username
        ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
        
        global_settings = database.get_global_settings()
        comm_rate = global_settings.get("referral_commission", 0.10) * 100
        
        text = (
            f"👥 **Refer & Earn Program**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 Your Referral Link:\n`{ref_link}`\n\n"
            f"💰 Get **₹1.00** instantly when a new user starts the bot using your link!\n"
            f"📈 Also earn **{comm_rate:.0f}%** commission on all their slot upgrades!\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 Total referred: **{referred_count}**\n"
            f"👛 Total referral earnings: **₹{earnings:.2f}**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"_Share your link and start earning wallet balance to buy slots!_"
        )
        
        kb = [
            [Button.url("🔗 Share Referral Link", url=f"https://t.me/share/url?url={ref_link}&text=Manage%20your%20Telegram%20UserBots%20easily!")],
            [utils.styled_button("🔙 Back", "menu_settings", style="primary")]
        ]
        
        await event.respond(text, buttons=kb)
        try:
            await event.delete()
        except Exception:
            pass

    # ==================== Subscription Plan Upgrades checkout ====================
    @client.on(events.CallbackQuery(pattern=r"^buy_plan_(.+)$"))
    async def buy_plan_callback(event):
        data = event.pattern_match.group(1)
        if "_qty_" in data:
            return
            
        plan_id = data
        user_id = event.sender_id
        
        # Ask quantity
        text = (
            "⚙️ **Select Slots Quantity**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "How many bot account slots would you like to purchase under this plan?"
        )
        buttons = []
        for qty in range(1, 6):
            buttons.append([
                utils.styled_button(f"Request {qty} Account Slot(s)", f"buy_plan_qty_{plan_id}_{qty}", style="primary")
            ])
        buttons.append([utils.styled_button("🔙 Back", "settings_buy_slots", style="primary")])
        
        await event.respond(text, buttons=buttons)
        try:
            await event.delete()
        except Exception:
            pass

    @client.on(events.CallbackQuery(pattern=r"^buy_plan_qty_(.+)_(.+)$"))
    async def buy_plan_qty_callback(event):
        plan_id = event.pattern_match.group(1)
        qty = int(event.pattern_match.group(2))
        user_id = event.sender_id
        
        global_settings = database.get_global_settings()
        plans = global_settings.get("subscription_plans", [])
        plan = next((p for p in plans if p["id"] == plan_id), None)
        if not plan:
            await event.respond("❌ Selected plan not found.")
            return
            
        import uuid
        payment_id = str(uuid.uuid4())[:8]
        
        # Calculate cost
        amount = plan["price"] * qty
        days = plan["days"]
        
        req_data = models.create_payment_request(payment_id, user_id, qty)
        req_data["plan_id"] = plan_id
        req_data["plan_name"] = plan["button_name"]
        req_data["amount"] = amount
        req_data["days"] = days
        database.save_payment_request(req_data)
        
        # Redirect
        class MockMatch:
            def group(self, group_idx):
                if group_idx == 1:
                    return qty
                elif group_idx == 2:
                    return payment_id
                return None
                
        event.pattern_match = MockMatch()
        await choose_method_callback(event)

    # ==================== UPI/USDT Payment Method selection ====================
    @client.on(events.CallbackQuery(pattern=r"^select_method_(\d+)_(.+)$"))
    async def choose_method_callback(event):
        qty = int(event.pattern_match.group(1))
        payment_id = event.pattern_match.group(2)
        user_id = event.sender_id
        
        user = database.get_user(user_id)
        lang = user.get("language", "en") if user else "en"
        
        # Get actual price from payment record
        pay_record = database.get_payment_request(payment_id)
        if pay_record and "amount" in pay_record:
            cost_inr = pay_record["amount"]
        else:
            global_settings = database.get_global_settings()
            price_per_id = global_settings.get("price_per_id", 10.0)
            cost_inr = price_per_id * qty
            
        wallet_bal = user.get("wallet_balance", 0.0)
        
        text = (
            f"💳 **Select Payment Method**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Quantity: **{qty} ID(s)**\n"
            f"Total Cost: **₹{cost_inr:.2f}**\n"
            f"Wallet Balance: **₹{wallet_bal:.2f}**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Choose your payment method below:"
        )
        
        buttons = [
            [utils.styled_button("💳 UPI Payment", f"pay_method_upi_{qty}_{payment_id}", style="primary")],
            [utils.styled_button("🪙 USDT (BEP20)", f"pay_method_usdt_{qty}_{payment_id}", style="primary")],
            [utils.styled_button("💎 TON (Toncoin)", f"pay_method_ton_{qty}_{payment_id}", style="primary")]
        ]
        
        # Allow paying using wallet if balance covers it
        if wallet_bal >= cost_inr:
            buttons.append([utils.styled_button("👛 Pay via Wallet Balance", f"pay_method_wallet_{qty}_{payment_id}", style="success")])
            
        buttons.append([utils.styled_button("❌ Cancel", "menu_settings", style="danger")])
        await event.respond(text, buttons=buttons)
        try:
            await event.delete()
        except Exception:
            pass

    # ==================== Payment Handler (Wallet Instant) ====================
    @client.on(events.CallbackQuery(pattern=r"^pay_method_wallet_(\d+)_(.+)$"))
    async def pay_wallet_callback(event):
        qty = int(event.pattern_match.group(1))
        payment_id = event.pattern_match.group(2)
        user_id = event.sender_id
        
        user = database.get_user(user_id)
        lang = user.get("language", "en") if user else "en"
        
        # Get actual price from payment record
        pay_record = database.get_payment_request(payment_id)
        if pay_record and "amount" in pay_record:
            cost_inr = pay_record["amount"]
        else:
            global_settings = database.get_global_settings()
            price_per_id = global_settings.get("price_per_id", 10.0)
            cost_inr = price_per_id * qty
            
        wallet_bal = user.get("wallet_balance", 0.0)
        
        if wallet_bal < cost_inr:
            await event.answer("❌ Insufficient wallet balance.", alert=True)
            return
            
        # Deduct wallet balance
        user["wallet_balance"] = wallet_bal - cost_inr
        database.save_user(user)
        
        # Save payment record
        if pay_record:
            pay_record["status"] = "approved"
            pay_record["method"] = "wallet"
            database.save_payment_request(pay_record)
            
        # Allocate subscription slots
        days = pay_record.get("days", 30) if pay_record else 30
        plan_name = pay_record.get("plan_name", "Slot Upgrade") if pay_record else "Slot Upgrade"
        expires_at = utils.allocate_slots_subscription(
            user_id, qty, days, plan_name, payment_id
        )
        
        import datetime
        expiry_str = datetime.datetime.fromtimestamp(expires_at).strftime('%d %b %Y %H:%M')
        
        await event.answer("🎉 Payment successful! Slots upgraded.", alert=True)
        await event.respond(
            f"🎉 **Upgrade Successful!**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Plan: **{plan_name}**\n"
            f"Slots purchased: **{qty}**\n"
            f"Cost: **₹{cost_inr:.2f}** deducted from wallet balance.\n"
            f"Expiry Date: **{expiry_str}**"
        )
        
        # Handle referral commission
        referrer_id = user.get("referred_by")
        if referrer_id:
            ref_user = database.get_user(referrer_id)
            if ref_user:
                global_settings = database.get_global_settings()
                comm_rate = global_settings.get("referral_commission", 0.10)
                commission = cost_inr * comm_rate
                ref_user["wallet_balance"] = ref_user.get("wallet_balance", 0.0) + commission
                ref_user["referral_earnings"] = ref_user.get("referral_earnings", 0.0) + commission
                database.save_user(ref_user)
                try:
                    await client.send_message(
                        referrer_id,
                        f"💰 **Commission Received!**\n"
                        f"Referred user upgraded slots. **₹{commission:.2f}** added to your wallet."
                    )
                except Exception:
                    pass
                    
        # Go to settings
        from handlers.settings import show_settings_menu
        await show_settings_menu(event, user_id)

    # ==================== Payment Handler (UPI/USDT/TON details) ====================
    @client.on(events.CallbackQuery(pattern=r"^pay_method_(upi|usdt|ton)_(\d+)_(.+)$"))
    async def pay_invoice_callback(event):
        method = event.pattern_match.group(1)
        qty = int(event.pattern_match.group(2))
        payment_id = event.pattern_match.group(3)
        user_id = event.sender_id
        
        user = database.get_user(user_id)
        lang = user.get("language", "en") if user else "en"
        
        # Fetch payment record to get exact amount
        pay_record = database.get_payment_request(payment_id)
        if pay_record and "amount" in pay_record:
            cost_inr = pay_record["amount"]
        else:
            global_settings = database.get_global_settings()
            price_per_id = global_settings.get("price_per_id", 10.0)
            cost_inr = price_per_id * qty
            
        global_settings = database.get_global_settings()
        
        # Save state
        _payment_user_states[user_id] = {
            "payment_id": payment_id,
            "method": method,
            "qty": qty,
            "amount": cost_inr,
            "action": "WAITING_FOR_SCREENSHOT"
        }
        
        if method == "upi":
            upi_id = global_settings.get('upi_id', 'merchant@upi')
            address_text = f"🏦 UPI ID: `{upi_id}`"
            import urllib.parse
            import config
            pn_encoded = urllib.parse.quote(config.BOT_NAME)
            upi_uri = f"upi://pay?pa={upi_id}&pn={pn_encoded}&am={cost_inr:.2f}&cu=INR&tn={payment_id}"
            qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(upi_uri)}"
        elif method == "usdt":
            address_text = f"🪙 USDT (BEP20) Address:\n`{global_settings.get('usdt_bep20_address', '0x000')}`"
            qr_url = None
        else: # ton
            address_text = f"💎 TON (Toncoin) Address:\n`{global_settings.get('ton_address', 'UQ00000000000000000000000000000000000000000000000')}`"
            qr_url = None
            
        text = (
            f"💳 **Make Payment**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Method: **{method.upper()}**\n"
            f"Amount to Pay: **₹{cost_inr:.2f}**\n"
            f"{address_text}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📸 Send your payment confirmation **screenshot (as a photo or image link)**:"
        )
        
        buttons = [[utils.styled_button("❌ Cancel", "menu_settings", style="danger")]]
        if qr_url:
            import urllib.request
            import tempfile
            import os
            try:
                # Download QR code image from the API
                req = urllib.request.Request(qr_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req) as response:
                    qr_bytes = response.read()
                
                # Write to temp file with .png extension to force photo upload
                fd, temp_file_path = tempfile.mkstemp(suffix=".png")
                try:
                    with os.fdopen(fd, 'wb') as tmp:
                        tmp.write(qr_bytes)
                    await event.respond(text, file=temp_file_path, buttons=buttons)
                finally:
                    try:
                        os.remove(temp_file_path)
                    except Exception:
                        pass
            except Exception as e:
                logger.error(f"Failed to fetch or send QR code: {e}")
                # Fallback to sending URL directly if download fails
                await event.respond(text, file=qr_url, buttons=buttons)
        else:
            await event.respond(text, buttons=buttons)
        try:
            await event.delete()
        except Exception:
            pass

    # ==================== Screenshot and UTR Receivers ====================
    @client.on(events.NewMessage)
    async def screenshot_and_utr_handler(event):
        if not event.is_private:
            return
        user_id = event.sender_id
        if user_id not in _payment_user_states:
            return
            
        state = _payment_user_states[user_id]
        action = state.get("action")
        
        user = database.get_user(user_id)
        lang = user.get("language", "en") if user else "en"
        
        # 1. Screenshot photo input
        if action == "WAITING_FOR_SCREENSHOT":
            photo = event.message.photo or event.photo
            file_to_save = None
            
            if photo:
                file_to_save = photo
            elif event.text and ("http://" in event.text or "https://" in event.text):
                import re
                urls = re.findall(r'(https?://[^\s]+)', event.text)
                if urls:
                    file_to_save = urls[0]
            
            if not file_to_save:
                await event.reply("❌ Please upload the payment screenshot as a photo or send a valid image link (e.g. ending in .jpg/.png).")
                return
                
            state["photo_file_id"] = file_to_save
            state["action"] = "WAITING_FOR_UTR"
            
            buttons = [[utils.styled_button("❌ Cancel", "menu_settings", style="danger")]]
            await event.reply(
                "📸 **Screenshot received!**\n\n"
                "🔢 **Now enter your UTR / Transaction Hash:**\n"
                "Example: `612207806800` or transaction reference code.",
                buttons=buttons
            )

        # 2. UTR transaction code input
        elif action == "WAITING_FOR_UTR":
            utr_code = event.text.strip()
            if not utr_code:
                await event.reply("❌ Please enter a valid Transaction Hash/UTR:")
                return
                
            # Pop state
            _payment_user_states.pop(user_id, None)
            
            payment_id = state["payment_id"]
            method = state["method"]
            qty = state["qty"]
            amount = state["amount"]
            photo_file_id = state["photo_file_id"]
            
            # Save detail in payment record
            pay_record = database.get_payment_request(payment_id)
            if pay_record:
                pay_record["method"] = method
                pay_record["utr_code"] = utr_code
                if isinstance(photo_file_id, str):
                    pay_record["screenshot"] = photo_file_id
                else:
                    pay_record["screenshot"] = f"photo_{photo_file_id.id}"
                database.save_payment_request(pay_record)
                
            # Confirm to User
            await event.reply("📩 **Payment submitted successfully!**\nAn administrator will review your submission shortly.")
            
            # Forward notification and screenshot to Admin log group
            global_settings = database.get_global_settings()
            log_group_id = global_settings.get("log_group_id")
            if log_group_id:
                try:
                    user_mention = f"[{user_id}](tg://user?id={user_id})"
                    admin_text = (
                        f"🚨 **New Payment Verification Request**\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"User: {user_mention} (`{user_id}`)\n"
                        f"Method: **{method.upper()}**\n"
                        f"Amount: **₹{amount:.2f}** (qty: {qty})\n"
                        f"UTR/Hash: `{utr_code}`\n"
                        f"━━━━━━━━━━━━━━━━━━━━"
                    )
                    
                    buttons = [
                        [
                            utils.styled_button("✅ Approve", f"approve_payment_{payment_id}", style="success"),
                            utils.styled_button("❌ Reject", f"reject_payment_{payment_id}", style="danger")
                        ]
                    ]
                    
                    await client.send_message(
                        log_group_id,
                        admin_text,
                        file=photo_file_id,
                        buttons=buttons
                    )
                except Exception as e:
                    logger.error(f"Failed to log payment to admin log group: {e}")

    # ==================== Admin Force Sub commands ====================
    @client.on(events.NewMessage(pattern=r"^/addchannel"))
    async def addchannel_cmd(event):
        if not is_admin(event.sender_id):
            return
            
        args = event.text.split()
        if len(args) < 3:
            await event.reply("Usage: `/addchannel <channel_id_or_username> <invite_link> [Channel Name]`")
            return
            
        ch_id = args[1]
        ch_link = args[2]
        ch_name = " ".join(args[3:]) if len(args) > 3 else ch_id
        
        database.add_force_channel(ch_id, ch_link, ch_name)
        await event.reply(f"✅ Channel added to force subscribe list: **{ch_name}**")

    @client.on(events.NewMessage(pattern=r"^/removechannel"))
    async def removechannel_cmd(event):
        if not is_admin(event.sender_id):
            return
            
        args = event.text.split()
        if len(args) < 2:
            await event.reply("Usage: `/removechannel <channel_id_or_username>`")
            return
            
        ch_id = args[1]
        database.delete_force_channel(ch_id)
        await event.reply(f"✅ Channel **{ch_id}** removed from force subscribe list.")

    # ==================== Admin Coupon commands ====================
    @client.on(events.NewMessage(pattern=r"^/addcoupon"))
    async def addcoupon_cmd(event):
        if not is_admin(event.sender_id):
            return
            
        args = event.text.split()
        if len(args) < 3:
            await event.reply("Usage: `/addcoupon <amount_inr> <max_uses>`")
            return
            
        try:
            amount = float(args[1])
            max_uses = int(args[2])
            if amount <= 0 or max_uses < 1:
                raise ValueError
        except ValueError:
            await event.reply("❌ Invalid parameters. Enter a positive amount and max uses.")
            return
            
        # Generate code
        code = "SLOT-" + secrets.token_hex(4).upper()
        coupon_data = {
            "code": code,
            "amount_inr": amount,
            "max_uses": max_uses,
            "current_uses": 0,
            "is_active": True
        }
        database.save_coupon(coupon_data)
        await event.reply(
            f"🎟️ **Coupon Code Generated Successfully!**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔑 Code: `{code}`\n"
            f"💰 Amount: **₹{amount:.2f}**\n"
            f"👥 Max Uses: **{max_uses}**"
        )

    @client.on(events.NewMessage(pattern=r"^/removecoupon"))
    async def removecoupon_cmd(event):
        if not is_admin(event.sender_id):
            return
            
        args = event.text.split()
        if len(args) < 2:
            await event.reply("Usage: `/removecoupon <code>`")
            return
            
        code = args[1].upper()
        database.delete_coupon(code)
        await event.reply(f"✅ Coupon `{code}` removed.")

    # ==================== Admin Subscription Plan commands ====================
    @client.on(events.NewMessage(pattern=r"^/addplan"))
    async def addplan_cmd(event):
        if not is_admin(event.sender_id):
            return
            
        args = event.text.split()
        if len(args) < 4:
            await event.reply("Usage: `/addplan <days> <price_per_account> <button_name>`")
            return
            
        try:
            days = int(args[1])
            price = float(args[2])
            button_name = " ".join(args[3:])
            if days <= 0 or price <= 0 or not button_name:
                raise ValueError
        except ValueError:
            await event.reply("❌ Invalid parameters. Enter a positive number of days and price.")
            return
            
        import uuid
        plan_id = "plan_" + str(uuid.uuid4())[:6]
        
        global_settings = database.get_global_settings()
        plans = global_settings.setdefault("subscription_plans", [])
        plans.append({
            "id": plan_id,
            "days": days,
            "price": price,
            "button_name": button_name
        })
        database.save_global_settings(global_settings)
        await event.reply(
            f"✅ **Subscription Plan Added Successfully!**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Plan ID: `{plan_id}`\n"
            f"Name: **{button_name}**\n"
            f"Days: **{days}**\n"
            f"Price per account: **₹{price:.2f}**"
        )

    @client.on(events.NewMessage(pattern=r"^/removeplan"))
    async def removeplan_cmd(event):
        if not is_admin(event.sender_id):
            return
            
        args = event.text.split()
        if len(args) < 2:
            await event.reply("Usage: `/removeplan <plan_id>`")
            return
            
        plan_id = args[1]
        
        global_settings = database.get_global_settings()
        plans = global_settings.get("subscription_plans", [])
        original_len = len(plans)
        global_settings["subscription_plans"] = [p for p in plans if p["id"] != plan_id]
        
        if len(global_settings["subscription_plans"]) < original_len:
            database.save_global_settings(global_settings)
            await event.reply(f"✅ Subscription plan `{plan_id}` successfully removed.")
        else:
            await event.reply(f"❌ Plan ID `{plan_id}` not found.")


# ==================== Gmail Auto-Approval background tasks ====================

def parse_famapp_email(body: str):
    """
    Parses FamApp notification emails to extract the UTR (12-digit code) and amount.
    """
    import re
    # 1. Search for 12-digit numeric UTR code
    utr_match = re.search(r'\b\d{12}\b', body)
    utr = utr_match.group(0) if utr_match else None
    
    # 2. Extract transaction ID if UTR not found
    if not utr:
        txn_match = re.search(r'Transaction ID[:\s]+([A-Z0-9]+)', body, re.IGNORECASE)
        if txn_match:
            utr = txn_match.group(1)
            
    # 3. Extract amount
    amount = None
    amt_match = re.search(r'(?:Rs|INR|₹)\.?\s*(\d+(?:\.\d+)?)', body, re.IGNORECASE)
    if amt_match:
        try:
            amount = float(amt_match.group(1))
        except ValueError:
            pass
            
    return utr, amount

def poll_gmail(bot_client):
    """
    Connects to Gmail IMAP, checks for new FamApp emails, and triggers automated approvals.
    """
    import imaplib
    import email
    
    if not config.GMAIL_USER or not config.GMAIL_APP_PASS:
        return
        
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(config.GMAIL_USER, config.GMAIL_APP_PASS)
        mail.select("inbox")
        
        # Search for unseen emails from FamApp senders
        for sender in config.FAMAPP_EMAILS:
            status, response = mail.search(None, f'(UNSEEN FROM "{sender}")')
            if status != "OK":
                continue
                
            msg_ids = response[0].split()
            for num in msg_ids:
                status, data = mail.fetch(num, '(RFC822)')
                if status != "OK":
                    continue
                    
                raw_email = data[0][1]
                msg = email.message_from_bytes(raw_email)
                
                # Retrieve email text body
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        content_type = part.get_content_type()
                        content_disposition = str(part.get("Content-Disposition"))
                        if content_type == "text/plain" and "attachment" not in content_disposition:
                            body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                            break
                        elif content_type == "text/html" and "attachment" not in content_disposition:
                            body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                else:
                    body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
                    
                if not body:
                    continue
                    
                utr, amount = parse_famapp_email(body)
                if utr:
                    logger.info(f"Gmail Autopay: Found UTR `{utr}` with amount ₹{amount} in email.")
                    # Trigger async database updates and user notifications
                    asyncio.run_coroutine_threadsafe(
                        approve_matching_payment(bot_client, utr, amount),
                        bot_client.loop
                    )
                    # Mark email as read/seen
                    mail.store(num, '+FLAGS', '\\Seen')
                    
        mail.close()
        mail.logout()
    except Exception as e:
        logger.error(f"Gmail IMAP check failed: {e}")

async def approve_matching_payment(bot_client, utr: str, amount: float):
    """
    Checks if there is a pending payment matching this UTR code, and approves it.
    """
    payments = database.get_payment_requests()
    for pay in payments:
        if pay.get("status") == "pending" and pay.get("utr_code") == utr:
            user_id = pay["user_id"]
            qty = pay["count"]
            payment_id = pay["payment_id"]
            
            # Approve payment
            pay["status"] = "approved"
            pay["auto_approved"] = True
            database.save_payment_request(pay)
            
            # Upgrade user slots subscription
            user = database.get_user(user_id)
            if user:
                days = pay.get("days", 30)
                plan_name = pay.get("plan_name", "Slot Upgrade")
                expires_at = utils.allocate_slots_subscription(
                    user_id, qty, days, plan_name, payment_id
                )
                
                # Notify User
                try:
                    import datetime
                    expiry_str = datetime.datetime.fromtimestamp(expires_at).strftime('%d %b %Y %H:%M')
                    await bot_client.send_message(
                        user_id,
                        f"🎉 **Payment Automatically Verified!**\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"Your payment with UTR `{utr}` has been auto-approved.\n"
                        f"Slots added: **{qty}**\n"
                        f"New slots limit: **{user['allowed_slots']}**"
                    )
                except Exception as ne:
                    logger.warning(f"Failed to notify user: {ne}")
                    
            # Log to Admin Channel
            global_settings = database.get_global_settings()
            log_group_id = global_settings.get("log_group_id")
            if log_group_id:
                try:
                    user_mention = f"[{user_id}](tg://user?id={user_id})"
                    await bot_client.send_message(
                        log_group_id,
                        f"✅ **Auto-Payment Approved (Gmail)**\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"User: {user_mention} (`{user_id}`)\n"
                        f"Amount: ₹{amount}\n"
                        f"UTR Code: `{utr}`\n"
                        f"Slots upgraded: **{qty}**"
                    )
                except Exception as le:
                    logger.warning(f"Failed to log to admin group: {le}")
                    
            # Apply referral commission
            if user:
                referrer_id = user.get("referred_by")
                if referrer_id:
                    ref_user = database.get_user(referrer_id)
                    if ref_user:
                        comm_rate = global_settings.get("referral_commission", 0.10)
                        commission = (global_settings.get("price_per_id", 10.0) * qty) * comm_rate
                        ref_user["wallet_balance"] = ref_user.get("wallet_balance", 0.0) + commission
                        ref_user["referral_earnings"] = ref_user.get("referral_earnings", 0.0) + commission
                        database.save_user(ref_user)
                        try:
                            await bot_client.send_message(
                                referrer_id,
                                f"💰 **Commission Received!**\n"
                                f"Referred user upgraded slots. **₹{commission:.2f}** added to your wallet."
                            )
                        except Exception:
                            pass
            break

async def start_gmail_polling(bot_client):
    """
    Asynchronous loop for periodic Gmail polling in a background worker task.
    """
    logger.info("Starting Gmail auto-approval polling thread...")
    while True:
        try:
            if config.GMAIL_USER and config.GMAIL_APP_PASS:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, poll_gmail, bot_client)
        except Exception as e:
            logger.error(f"Error checking Gmail IMAP inbox: {e}")
        # Poll every 30 seconds
        await asyncio.sleep(30)
