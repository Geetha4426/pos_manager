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
