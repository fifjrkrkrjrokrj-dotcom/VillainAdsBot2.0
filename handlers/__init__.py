def register_all_handlers(client):
    """
    Registers all bot event handlers onto the client instance.
    """
    import utils
    from telethon.tl.types import PeerUser, InputPeerUser, User
    
    def should_add_menu_button(entity, buttons) -> bool:
        if buttons is not None:
            return False
            
        if isinstance(entity, int):
            return entity > 0
        if isinstance(entity, str):
            return not entity.startswith("-")
        if isinstance(entity, (PeerUser, InputPeerUser, User)):
            return True
        if hasattr(entity, "id") and isinstance(entity.id, int):
            if entity.__class__.__name__ == "User":
                return True
        return False

    original_send_message = client.send_message
    async def patched_send_message(entity, message, *args, **kwargs):
        buttons = kwargs.get("buttons")
        if should_add_menu_button(entity, buttons):
            kwargs["buttons"] = [[utils.styled_button("🏠 Main Menu", "menu_start", style="primary")]]
        return await original_send_message(entity, message, *args, **kwargs)
    client.send_message = patched_send_message

    original_send_file = client.send_file
    async def patched_send_file(entity, file, *args, **kwargs):
        buttons = kwargs.get("buttons")
        if should_add_menu_button(entity, buttons):
            kwargs["buttons"] = [[utils.styled_button("🏠 Main Menu", "menu_start", style="primary")]]
        return await original_send_file(entity, file, *args, **kwargs)
    client.send_file = patched_send_file

    original_edit_message = client.edit_message
    async def patched_edit_message(entity, message, *args, **kwargs):
        buttons = kwargs.get("buttons")
        if should_add_menu_button(entity, buttons):
            kwargs["buttons"] = [[utils.styled_button("🏠 Main Menu", "menu_start", style="primary")]]
        return await original_edit_message(entity, message, *args, **kwargs)
    client.edit_message = patched_edit_message

    from . import start, callbacks, add_bot, my_bots, settings, admin, status, payments, payments_extended
    
    # Register the callbacks handler first to intercept queries and display helper popups
    callbacks.register_handlers(client)
    
    # Register core command and workflow handlers
    start.register_handlers(client)
    add_bot.register_handlers(client)
    my_bots.register_handlers(client)
    settings.register_handlers(client)
    admin.register_handlers(client)
    status.register_handlers(client)
    payments.register_handlers(client)
    payments_extended.register_handlers(client)
