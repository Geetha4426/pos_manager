"""
Polymarket Telegram Sniper Bot

Main entry point - registers all handlers and starts the bot.
"""

import asyncio
import logging
from telegram import Update
from telegram.ext import (
    Application, 
    CommandHandler, 
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    filters
)

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from core.polymarket_client import get_polymarket_client
from core.favorites_db import get_favorites_db
from bot.keyboards.inline import main_menu_keyboard

# Import handlers
from bot.handlers.positions import (
    positions_command, position_detail_callback, sell_callback,
    confirm_sell_callback, custom_sell_input, CUSTOM_SELL_PERCENT
)
from bot.handlers.trading import (
    buy_command, category_callback, sport_callback, page_callback,
    market_callback, outcome_callback, amount_callback,
    execute_buy_callback, custom_amount_input, CUSTOM_AMOUNT
)
from bot.handlers.search import (
    search_command, search_callback, info_command,
    hot_command, hot_callback
)
from bot.handlers.favorites import (
    favorites_command, favorites_callback,
    fav_add_callback, fav_view_callback, fav_del_callback
)
from bot.handlers.wallet import balance_command, balance_callback


# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


async def start_command(update: Update, context):
    """Handle /start command - welcome message."""
    user = update.effective_user
    mode = "📝 Paper Trading" if Config.is_paper_mode() else "💱 Live Trading"
    
    text = f"""
🚀 <b>Polymarket Sniper Bot</b>

Welcome, {user.first_name}! ⚡

<b>Mode:</b> {mode}

<b>Commands:</b>
📊 /positions - View active positions
💰 /balance - Wallet overview
🛒 /buy - Buy new position
🔍 /search - Search markets
⭐ /favorites - Saved markets
🔥 /hot - Trending markets

<i>Lightning-fast trading at your fingertips! 🏎️</i>
"""
    
    await update.message.reply_text(
        text,
        parse_mode='HTML',
        reply_markup=main_menu_keyboard()
    )


async def help_command(update: Update, context):
    """Handle /help command."""
    text = """
📖 <b>Bot Commands</b>

<b>Trading:</b>
/buy - Start buy flow with categories
/search <query> - Search markets
/info <query> - Market details

<b>Positions:</b>
/positions - View all positions
/balance - Wallet balance

<b>Favorites:</b>
/favorites - Saved markets

<b>Discovery:</b>
/hot - Trending markets

<b>Settings:</b>
/start - Main menu
/help - This help

<b>Tips:</b>
• Use button menus for fastest trading
• Partial sells: 25%, 50%, or custom %
• Add favorites for quick access
"""
    
    await update.message.reply_text(text, parse_mode='HTML')


async def menu_callback(update: Update, context):
    """Handle menu button - return to main menu."""
    query = update.callback_query
    await query.answer()
    
    mode = "📝 Paper Trading" if Config.is_paper_mode() else "💱 Live Trading"
    
    text = f"""
🚀 <b>Polymarket Sniper Bot</b>

<b>Mode:</b> {mode}

Select an option below:
"""
    
    await query.edit_message_text(
        text,
        parse_mode='HTML',
        reply_markup=main_menu_keyboard()
    )


async def error_handler(update: object, context) -> None:
    """Handle errors."""
    logger.error("Exception while handling update:", exc_info=context.error)
    
    if update and hasattr(update, 'effective_message') and update.effective_message:
        await update.effective_message.reply_text(
            "⚠️ An error occurred. Please try again."
        )


def main():
    """Start the bot."""
    if not Config.TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN not set!")
        print("Set it in .env file or environment variables.")
        return
    
    Config.print_status()
    
    # Build application
    app = Application.builder().token(Config.TELEGRAM_BOT_TOKEN).build()
    
    # ═══════════════════════════════════════════════════════════════════
    # COMMAND HANDLERS
    # ═══════════════════════════════════════════════════════════════════
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("positions", positions_command))
    app.add_handler(CommandHandler("balance", balance_command))
    app.add_handler(CommandHandler("buy", buy_command))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("info", info_command))
    app.add_handler(CommandHandler("favorites", favorites_command))
    app.add_handler(CommandHandler("hot", hot_command))
    
    # ═══════════════════════════════════════════════════════════════════
    # CALLBACK HANDLERS
    # ═══════════════════════════════════════════════════════════════════
    
    # Menu navigation
    app.add_handler(CallbackQueryHandler(menu_callback, pattern="^menu$"))
    app.add_handler(CallbackQueryHandler(balance_callback, pattern="^balance$"))
    app.add_handler(CallbackQueryHandler(positions_command, pattern="^positions$"))
    app.add_handler(CallbackQueryHandler(buy_command, pattern="^buy$"))
    app.add_handler(CallbackQueryHandler(search_callback, pattern="^search$"))
    app.add_handler(CallbackQueryHandler(favorites_callback, pattern="^favorites$"))
    app.add_handler(CallbackQueryHandler(hot_callback, pattern="^hot$"))
    
    # Position handlers
    app.add_handler(CallbackQueryHandler(position_detail_callback, pattern="^pos_detail_"))
    app.add_handler(CallbackQueryHandler(sell_callback, pattern="^sell_"))
    app.add_handler(CallbackQueryHandler(confirm_sell_callback, pattern="^confirm_sell_"))
    
    # Trading handlers
    app.add_handler(CallbackQueryHandler(category_callback, pattern="^cat_"))
    app.add_handler(CallbackQueryHandler(sport_callback, pattern="^sport_"))
    app.add_handler(CallbackQueryHandler(page_callback, pattern="^page_"))
    app.add_handler(CallbackQueryHandler(market_callback, pattern="^market_"))
    app.add_handler(CallbackQueryHandler(outcome_callback, pattern="^outcome_"))
    app.add_handler(CallbackQueryHandler(amount_callback, pattern="^amount_"))
    app.add_handler(CallbackQueryHandler(execute_buy_callback, pattern="^exec_buy_"))
    
    # Favorites handlers
    app.add_handler(CallbackQueryHandler(fav_add_callback, pattern="^fav_add_"))
    app.add_handler(CallbackQueryHandler(fav_view_callback, pattern="^fav_view_"))
    app.add_handler(CallbackQueryHandler(fav_del_callback, pattern="^fav_del_"))
    
    # Error handler
    app.add_error_handler(error_handler)
    
    # ═══════════════════════════════════════════════════════════════════
    # START BOT
    # ═══════════════════════════════════════════════════════════════════
    print("🚀 Starting Polymarket Telegram Bot...")
    print("Press Ctrl+C to stop.\n")
    
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
