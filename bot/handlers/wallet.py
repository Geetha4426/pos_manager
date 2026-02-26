"""
Wallet Handlers

Handles /balance and /wallet commands.
"""

from telegram import Update
from telegram.ext import ContextTypes

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config import Config
from core.polymarket_client import get_polymarket_client, require_auth
from bot.keyboards.inline import main_menu_keyboard


async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /balance command - show wallet overview."""
    client = await require_auth(update)
    if not client:
        return
    
    balance = await client.get_balance()
    positions = await client.get_positions()
    
    position_value = sum(p.value for p in positions)
    total_value = balance + position_value
    total_pnl = sum(p.pnl for p in positions)
    
    pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
    pnl_percent = (total_pnl / (total_value - total_pnl) * 100) if (total_value - total_pnl) > 0 else 0
    
    mode_text = "📝 Paper" if Config.is_paper_mode() else "💱 Live"
    
    text = f"""
💰 <b>Wallet Overview</b>

💵 <b>USDC Balance:</b> ${balance:.2f}
📊 <b>Position Value:</b> ${position_value:.2f}
━━━━━━━━━━━━━━━━━━━
📈 <b>Total Value:</b> ${total_value:.2f}

{pnl_emoji} <b>Unrealized P&L:</b> ${total_pnl:+.2f} ({pnl_percent:+.1f}%)
📊 <b>Active Positions:</b> {len(positions)}

<b>Mode:</b> {mode_text}
"""
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            parse_mode='HTML',
            reply_markup=main_menu_keyboard()
        )
    else:
        await update.message.reply_text(
            text,
            parse_mode='HTML',
            reply_markup=main_menu_keyboard()
        )


async def balance_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle balance button callback."""
    await update.callback_query.answer()
    await balance_command(update, context)


async def debug_wallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /debug_wallet command - show wallet config for debugging signature issues."""
    from core.polymarket_client import get_polymarket_client
    
    client = get_polymarket_client()
    
    # Mask private key
    pk = Config.POLYGON_PRIVATE_KEY
    pk_display = f"{pk[:6]}...{pk[-4:]}" if len(pk) > 10 else "(not set)"
    
    # Funder address
    funder = Config.FUNDER_ADDRESS
    funder_display = funder if funder else "NOT SET ⚠️"
    
    # Signature type
    sig_type = Config.SIGNATURE_TYPE
    sig_label = {0: "EOA (direct wallet)", 1: "Proxy/Magic (email login)", 2: "Proxy"}.get(sig_type, f"Unknown ({sig_type})")
    
    # Signer (EOA) address from ClobClient
    signer = "(unknown)"
    actual_funder = "(unknown)"
    if client and client.clob_client:
        try:
            signer = client.clob_client.get_address()
        except Exception:
            pass
        actual_funder = getattr(client, '_funder_address', funder_display)
    
    # Relay config
    relay = Config.CLOB_RELAY_URL or "NOT SET (direct)"
    relay_auth = "SET" if Config.CLOB_RELAY_AUTH_TOKEN else "NOT SET"
    
    # Trading mode
    mode = "PAPER 📝" if Config.is_paper_mode() else "LIVE 💱"
    
    text = f"""
🔧 <b>Wallet Debug Info</b>

<b>Trading Mode:</b> {mode}

<b>Signer (EOA):</b> <code>{signer}</code>
<b>Funder (Proxy):</b> <code>{actual_funder}</code>
<b>Private Key:</b> <code>{pk_display}</code>

<b>Signature Type:</b> {sig_type} ({sig_label})
<b>Chain ID:</b> {Config.POLYGON_CHAIN_ID}

<b>CLOB URL:</b> {Config.get_clob_url()}
<b>Relay:</b> {relay}
<b>Relay Auth:</b> {relay_auth}

━━━━━━━━━━━━━━━━━━━
<b>Troubleshooting "invalid signature":</b>

• If you created your Polymarket account via <b>email/browser</b>:
  → SIGNATURE_TYPE should be <b>1</b>
  → FUNDER_ADDRESS must be your <b>proxy wallet</b> address
  (Find it on polygonscan: the contract that holds your USDC)

• If you use a <b>direct EOA wallet</b> (MetaMask export):
  → SIGNATURE_TYPE should be <b>0</b>
  → FUNDER_ADDRESS can be empty

• FUNDER_ADDRESS ≠ Signer address for proxy wallets
"""
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode='HTML')
    else:
        await update.message.reply_text(text, parse_mode='HTML')
