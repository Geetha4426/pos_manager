"""
Auth Handlers

Multi-user wallet connection and session management.
- /connect  : Link wallet (private key encrypted with password)
- /unlock   : Decrypt key and start trading session
- /lock     : Destroy session immediately
- /disconnect: Remove wallet entirely
- /mystatus : Show session & wallet info

Security:
- Private key messages are IMMEDIATELY deleted
- Password messages are IMMEDIATELY deleted
- Keys encrypted with AES-256-GCM (PBKDF2 key derivation)
- Decrypted key lives in memory only during active session
- Sessions are permanent by default (no timeout)
- All users must /connect via Telegram (no env var keys)
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler,
    CommandHandler, MessageHandler, CallbackQueryHandler,
    filters
)

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.user_manager import get_user_manager


# ═══════════════════════════════════════════════════════════════════
# CONVERSATION STATES
# ═══════════════════════════════════════════════════════════════════
WAITING_KEY = 0
WAITING_PASSWORD = 1
WAITING_FUNDER = 2
WAITING_UNLOCK_PASSWORD = 3
WAITING_DISCONNECT_CONFIRM = 4


# ═══════════════════════════════════════════════════════════════════
# /connect - MULTI-STEP WALLET REGISTRATION
# ═══════════════════════════════════════════════════════════════════

async def connect_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /connect - start wallet connection flow."""
    um = get_user_manager()
    user_id = update.effective_user.id

    # Check if already registered
    if await um.is_registered(user_id):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔓 Unlock Wallet", callback_data="auth_unlock")],
            [InlineKeyboardButton("🔄 Re-connect (overwrite)", callback_data="auth_reconnect")],
        ])
        await update.message.reply_text(
            "🔗 <b>Wallet Already Connected</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "You already have a wallet linked.\n\n"
            "• /unlock to start trading\n"
            "• Re-connect to overwrite with a new key",
            parse_mode='HTML',
            reply_markup=keyboard
        )
        return ConversationHandler.END

    await _ask_for_key(update)
    return WAITING_KEY


async def reconnect_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle re-connect button — restart the connect flow."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🔑 <b>Re-connect Wallet</b>\n\n"
        "⚠️ This will overwrite your existing key.\n\n"
        "Send your <b>Polygon private key</b> now.\n"
        "It will be <b>immediately deleted</b> from chat.\n\n"
        "<i>Format: 0x... (64 hex chars)</i>",
        parse_mode='HTML'
    )
    return WAITING_KEY


async def _ask_for_key(update: Update):
    """Prompt user to send private key."""
    text = (
        "🔐 <b>Connect Wallet</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Send your <b>Polygon private key</b> now.\n\n"
        "🛡️ <b>Security:</b>\n"
        "• Message <b>instantly deleted</b>\n"
        "• Encrypted with AES-256-GCM\n"
        "• Password NEVER stored\n\n"
        "<i>Format: 0x... (64 hex characters)</i>\n"
        "Send /cancel to abort."
    )
    if update.message:
        await update.message.reply_text(text, parse_mode='HTML')
    elif update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode='HTML')


async def receive_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive private key — DELETE the message immediately."""
    # IMMEDIATELY delete the message containing the private key
    try:
        await update.message.delete()
    except Exception:
        pass  # Bot may lack delete permissions in groups

    key = update.message.text.strip()

    # Basic validation
    clean = key[2:] if key.startswith('0x') else key
    if len(clean) != 64 or not all(c in '0123456789abcdefABCDEF' for c in clean):
        await update.message.reply_text(
            "❌ Invalid private key format.\n"
            "Must be 64 hex characters (with or without 0x prefix).\n\n"
            "Send your key again or /cancel to abort."
        )
        return WAITING_KEY

    # Store temporarily in context (memory only, never persisted)
    context.user_data['_temp_key'] = key
    
    await update.effective_chat.send_message(
        "✅ Key received and <b>deleted</b>.\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Set an <b>encryption password</b>.\n"
        "You'll need it to unlock your wallet.\n\n"
        "⚠️ <b>Forget password = key unrecoverable</b>\n\n"
        "<i>Min 6 characters · message auto-deleted</i>\n"
        "Send /cancel to abort.",
        parse_mode='HTML'
    )
    return WAITING_PASSWORD


async def receive_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive encryption password — DELETE the message."""
    try:
        await update.message.delete()
    except Exception:
        pass

    password = update.message.text.strip()
    
    if len(password) < 6:
        await update.effective_chat.send_message(
            "❌ Password too short. Use at least 6 characters.\n\n"
            "Send your password again or /cancel to abort."
        )
        return WAITING_PASSWORD

    context.user_data['_temp_password'] = password

    await update.effective_chat.send_message(
        "🏦 <b>Funder Address</b> (optional)\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "If you use a <b>Polymarket proxy wallet</b>\n"
        "(Magic/email login), send the <b>proxy address</b>.\n\n"
        "Direct EOA wallet \u2192 send /skip\n\n"
        "<i>Format: 0x... (Polygon address)</i>",
        parse_mode='HTML'
    )
    return WAITING_FUNDER


async def receive_funder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive funder address and complete registration."""
    text = update.message.text.strip()
    
    funder = ''
    sig_type = 0  # Default: EOA
    if text.lower() not in ('/skip', 'skip', '-', 'none', 'no'):
        if text.startswith('0x') and len(text) == 42:
            funder = text
            sig_type = 2  # Polymarket proxy wallet = GnosisSafe (sig_type=2)
        else:
            await update.message.reply_text(
                "❌ Invalid address format. Must be 0x... (42 characters).\n\n"
                "Send the address again, or /skip to use default."
            )
            return WAITING_FUNDER

    # Complete registration
    key = context.user_data.pop('_temp_key', None)
    password = context.user_data.pop('_temp_password', None)

    if not key or not password:
        await update.message.reply_text(
            "⚠️ Session expired. Please start over with /connect."
        )
        return ConversationHandler.END

    um = get_user_manager()
    user = update.effective_user
    display_name = user.first_name or user.username or str(user.id)

    success, message = await um.register_user(
        telegram_id=user.id,
        private_key=key,
        password=password,
        funder_address=funder,
        signature_type=sig_type,  # 0=EOA (no funder), 2=GnosisSafe (proxy wallet)
        display_name=display_name
    )

    # Clear sensitive data
    key = None
    password = None

    if success:
        sig_label = "EOA (direct)" if sig_type == 0 else "GnosisSafe (proxy)"
        await update.message.reply_text(
            f"✅ <b>Wallet Connected</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🔐 Encrypted (AES-256-GCM)\n"
            f"🏦 {funder[:8]}...{funder[-4:] if funder else 'default (EOA)'}\n"
            f"📝 {sig_label}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"• /unlock to start trading\n"
            f"• /disconnect to remove wallet",
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text(f"❌ {message}")

    return ConversationHandler.END


async def connect_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the connect flow."""
    context.user_data.pop('_temp_key', None)
    context.user_data.pop('_temp_password', None)
    await update.message.reply_text("❌ Wallet connection cancelled.")
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════════
# /unlock - START TRADING SESSION
# ═══════════════════════════════════════════════════════════════════

async def unlock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /unlock - ask for password to decrypt key."""
    um = get_user_manager()
    user_id = update.effective_user.id

    if not await um.is_registered(user_id):
        await update.message.reply_text(
            "🔗 No wallet connected. Use /connect first."
        )
        return ConversationHandler.END

    # Check if already unlocked
    if um.is_unlocked(user_id):
        session = um.get_session(user_id)
        addr = session.funder_address if session else '?'
        await update.message.reply_text(
            f"🔓 <b>Already Unlocked</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🏦 <code>{addr[:8]}...{addr[-4:]}</code>\n\n"
            f"Use /lock to end session.",
            parse_mode='HTML'
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "🔑 <b>Unlock Wallet</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Send your <b>encryption password</b>.\n"
        "<i>Message auto-deleted</i>\n\n"
        "Send /cancel to abort.",
        parse_mode='HTML'
    )
    return WAITING_UNLOCK_PASSWORD


async def unlock_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle unlock button from inline keyboard."""
    query = update.callback_query
    await query.answer()
    
    um = get_user_manager()
    user_id = update.effective_user.id
    
    if um.is_unlocked(user_id):
        await query.edit_message_text("🔓 Already unlocked! Start trading.")
        return ConversationHandler.END
    
    await query.edit_message_text(
        "🔑 <b>Unlock Wallet</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Send your <b>encryption password</b>.\n"
        "<i>Message auto-deleted</i>\n\n"
        "Send /cancel to abort.",
        parse_mode='HTML'
    )
    return WAITING_UNLOCK_PASSWORD


async def receive_unlock_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive password for unlock — DELETE message, create session."""
    try:
        await update.message.delete()
    except Exception:
        pass

    password = update.message.text.strip()
    um = get_user_manager()
    user_id = update.effective_user.id

    success, message = await um.unlock_session(user_id, password)

    if success:
        await update.effective_chat.send_message(
            f"🔓 <b>Wallet Unlocked</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{message}\n\n"
            f"✅ Session is permanent (no timeout)\n"
            f"🔒 /lock to end session manually\n\n"
            f"Ready to trade! Try /positions or /buy",
            parse_mode='HTML'
        )
    else:
        await update.effective_chat.send_message(
            f"❌ {message}\n\nTry again or send /cancel.",
        )
        return WAITING_UNLOCK_PASSWORD

    return ConversationHandler.END


async def unlock_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel unlock flow."""
    await update.message.reply_text("❌ Unlock cancelled.")
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════════
# /lock - END SESSION
# ═══════════════════════════════════════════════════════════════════

async def lock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /lock - destroy active session."""
    um = get_user_manager()
    user_id = update.effective_user.id

    if um.lock_session(user_id):
        await update.message.reply_text(
            "🔒 <b>Session Locked</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "ClobClient destroyed\n"
            "Decrypted key cleared from memory\n\n"
            "/unlock to start a new session",
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text(
            "ℹ️ No active session to lock."
        )


# ═══════════════════════════════════════════════════════════════════
# /disconnect - REMOVE WALLET ENTIRELY
# ═══════════════════════════════════════════════════════════════════

async def disconnect_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /disconnect - ask for confirmation before deleting wallet."""
    um = get_user_manager()
    user_id = update.effective_user.id

    if not await um.is_registered(user_id):
        await update.message.reply_text("ℹ️ No wallet connected.")
        return ConversationHandler.END

    await update.message.reply_text(
        "⚠️ <b>Disconnect Wallet</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "This will <b>permanently delete</b> your\n"
        "encrypted key from the bot.\n\n"
        "Type <b>CONFIRM</b> to proceed, or /cancel",
        parse_mode='HTML'
    )
    return WAITING_DISCONNECT_CONFIRM


async def receive_disconnect_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirm wallet deletion."""
    text = update.message.text.strip().upper()
    
    if text != 'CONFIRM':
        await update.message.reply_text(
            "❌ Disconnect cancelled. Type CONFIRM to proceed."
        )
        return WAITING_DISCONNECT_CONFIRM

    um = get_user_manager()
    user_id = update.effective_user.id

    success = await um.delete_user(user_id)
    if success:
        await update.message.reply_text(
            "✅ <b>Wallet Disconnected</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Encrypted key deleted\n"
            "Session destroyed\n\n"
            "/connect to link a new wallet",
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text("❌ Failed to disconnect. Try again.")

    return ConversationHandler.END


async def disconnect_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel disconnect."""
    await update.message.reply_text("❌ Disconnect cancelled.")
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════════
# /mystatus - SESSION INFO
# ═══════════════════════════════════════════════════════════════════

async def mystatus_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /mystatus - show session and wallet info."""
    um = get_user_manager()
    user_id = update.effective_user.id

    registered = await um.is_registered(user_id)
    session = um.get_session(user_id) if registered else None

    if not registered:
        text = (
            "� <b>Account Status</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🔴 Wallet: Not connected\n\n"
            "/connect to link your wallet"
        )
    elif session:
        import time
        elapsed = int(time.time() - session.session_start)
        mins = elapsed // 60
        idle = int(time.time() - session.last_activity)
        addr = session.funder_address
        text = (
            f"👤 <b>Account Status</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🟢 <b>Session: ACTIVE</b>\n"
            f"🏦 <code>{addr[:8]}...{addr[-4:]}</code>\n\n"
            f"⏱️ Active: {mins}m  |  💤 Idle: {idle}s\n"
            f"👤 {session.display_name}\n\n"
            f"/lock to end session"
        )
    else:
        text = (
            "👤 <b>Account Status</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🔒 <b>Session: LOCKED</b>\n"
            "🔗 Wallet: Connected (encrypted)\n\n"
            "/unlock to start trading"
        )

    total_users = await um.get_user_count()
    active = um.get_active_session_count()
    text += f"\n\n━━━━━━━━━━━━━━━━━━━━━\n📊 {total_users} users · {active} active"

    await update.message.reply_text(text, parse_mode='HTML')


# ═══════════════════════════════════════════════════════════════════
# BUILD CONVERSATION HANDLERS
# ═══════════════════════════════════════════════════════════════════

def build_connect_handler() -> ConversationHandler:
    """Build the /connect conversation handler."""
    return ConversationHandler(
        entry_points=[
            CommandHandler("connect", connect_command),
            CallbackQueryHandler(reconnect_callback, pattern="^auth_reconnect$"),
        ],
        states={
            WAITING_KEY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_key)
            ],
            WAITING_PASSWORD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_password)
            ],
            WAITING_FUNDER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_funder),
                CommandHandler("skip", receive_funder),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", connect_cancel),
            CommandHandler("start", connect_cancel),
        ],
        name="connect_wallet",
        persistent=False,
        per_message=False,
    )


def build_unlock_handler() -> ConversationHandler:
    """Build the /unlock conversation handler."""
    return ConversationHandler(
        entry_points=[
            CommandHandler("unlock", unlock_command),
            CallbackQueryHandler(unlock_callback, pattern="^auth_unlock$"),
        ],
        states={
            WAITING_UNLOCK_PASSWORD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_unlock_password)
            ],
        },
        fallbacks=[
            CommandHandler("cancel", unlock_cancel),
            CommandHandler("start", unlock_cancel),
        ],
        name="unlock_wallet",
        persistent=False,
        per_message=False,
    )


def build_disconnect_handler() -> ConversationHandler:
    """Build the /disconnect conversation handler."""
    return ConversationHandler(
        entry_points=[
            CommandHandler("disconnect", disconnect_command),
        ],
        states={
            WAITING_DISCONNECT_CONFIRM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_disconnect_confirm)
            ],
        },
        fallbacks=[
            CommandHandler("cancel", disconnect_cancel),
            CommandHandler("start", disconnect_cancel),
        ],
        name="disconnect_wallet",
        persistent=False,
        per_message=False,
    )
