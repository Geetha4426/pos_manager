"""
Polymarket Telegram Sniper Bot

Main entry point - registers all handlers and starts the bot.
Features:
- Event-based sports navigation with sub-markets
- WebSocket real-time price feed
- Position manager with live P&L
- Instant one-click sell (FOK → GTC fallback)
"""

import asyncio
import logging
import warnings
from telegram import Update
from telegram.ext import (
    Application, 
    CommandHandler, 
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    PicklePersistence,
    filters
)

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from core.polymarket_client import get_polymarket_client, init_polymarket_client
from core.favorites_db import get_favorites_db
from bot.keyboards.inline import main_menu_keyboard

# Import handlers
from bot.handlers.positions import (
    positions_command, position_detail_callback, sell_callback,
    confirm_sell_callback, custom_sell_input, CUSTOM_SELL_PERCENT,
    instant_sell_callback, refresh_positions_callback
)
from bot.handlers.trading import (
    buy_command, category_callback, sport_callback, league_callback,
    event_callback, events_page_callback, sub_market_callback,
    back_events_callback, back_sub_callback, back_out_callback,
    outcome_callback, amount_callback, market_callback, page_callback,
    execute_buy_callback, custom_amount_input, CUSTOM_AMOUNT
)
from bot.handlers.search import (
    search_command, search_callback, search_text_input, info_command,
    hot_command, hot_callback, SEARCH_INPUT
)
from bot.handlers.favorites import (
    favorites_command, favorites_callback,
    fav_add_callback, fav_view_callback, fav_del_callback
)
from bot.handlers.wallet import balance_command, balance_callback
from bot.handlers.orders import (
    orders_command, orders_callback, cancel_order_callback,
    cancel_all_callback, order_book_callback
)
from bot.handlers.alerts import (
    alerts_command, alert_command, stoploss_command, takeprofit_command,
    delete_alert_callback, alerts_callback
)
from bot.handlers.auth import (
    build_connect_handler, build_unlock_handler, build_disconnect_handler,
    lock_command, mystatus_command
)


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
    instant = "✅ ON" if Config.USE_INSTANT_SELL else "❌ OFF"
    
    text = (
        f"🚀 <b>Polymarket Sniper Bot</b>\n\n"
        f"Welcome, {user.first_name}! ⚡\n\n"
        f"<b>Mode:</b> {mode}\n"
        f"<b>Instant Sell:</b> {instant}\n\n"
        f"<b>🔐 Wallet:</b>\n"
        f"🔗 /connect - Link your wallet\n"
        f"🔓 /unlock - Unlock to trade\n"
        f"🔒 /lock - Lock session\n"
        f"📋 /mystatus - Session info\n\n"
        f"<b>📊 Trading:</b>\n"
        f"📊 /positions - View positions (live P&L)\n"
        f"💰 /balance - Wallet overview\n"
        f"🛒 /buy - Buy new position\n"
        f"🔍 /search - Search markets\n"
        f"⭐ /favorites - Saved markets\n"
        f"🔥 /hot - Trending markets\n\n"
        f"<i>⚡ One-click instant sell • Live bid/ask prices</i>"
    )
    
    await update.message.reply_text(
        text,
        parse_mode='HTML',
        reply_markup=main_menu_keyboard()
    )


async def help_command(update: Update, context):
    """Handle /help command."""
    text = """
📖 <b>Bot Commands</b>

<b>🔐 Wallet:</b>
/connect - Link your wallet (encrypted)
/unlock - Start trading session
/lock - End session (clear from memory)
/disconnect - Remove wallet permanently
/mystatus - Session & wallet info

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
• Use /connect first, then /unlock to start trading
• Sessions auto-lock after 30 min of inactivity
• Your private key is AES-256-GCM encrypted
"""
    
    await update.message.reply_text(text, parse_mode='HTML')


async def menu_callback(update: Update, context):
    """Handle menu button - return to main menu."""
    query = update.callback_query
    await query.answer()
    
    mode = "📝 Paper Trading" if Config.is_paper_mode() else "💱 LIVE Trading"
    
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
    print("🟢 Bot process starting...", flush=True)
    
    if not Config.TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN not set!")
        print("Set it in .env file or environment variables.")
        return
    
    # Suppress PTB per_message warnings for ConversationHandlers with CallbackQuery entry points
    warnings.filterwarnings('ignore', message=".*per_message.*", category=UserWarning)
    
    Config.print_status()
    
    # Persistence: user_data survives bot restarts
    import os
    persistence = None
    try:
        data_dir = os.path.dirname(Config.DATABASE_PATH)
        if data_dir:
            os.makedirs(data_dir, exist_ok=True)
        persistence_path = os.path.join(data_dir or '.', 'bot_data.pickle')
        # Remove corrupt pickle if it exists and is tiny/empty
        if os.path.exists(persistence_path):
            fsize = os.path.getsize(persistence_path)
            if fsize < 10:
                os.remove(persistence_path)
                print(f"🗑️ Removed corrupt pickle ({fsize}B)")
        persistence = PicklePersistence(filepath=persistence_path)
        print(f"💾 Persistence: {persistence_path}")
    except Exception as e:
        print(f"⚠️ Persistence init failed (non-fatal): {e}")
        persistence = None
    
    # Build application
    builder = Application.builder().token(Config.TELEGRAM_BOT_TOKEN)
    if persistence:
        builder = builder.persistence(persistence)
    app = builder.build()
    print("✅ Application built", flush=True)
    
    # Initialize async components on startup
    async def post_init(application):
        """Initialize async components: client, WS feed, position tracker."""
        import time as _time
        t0 = _time.time()
        
        # 1. Initialize Polymarket client (+ load paper positions)
        t1 = _time.time()
        await init_polymarket_client()
        print(f"✅ Polymarket client initialized ({_time.time()-t1:.1f}s)")
        
        # 2. Initialize position manager (load positions + start tracking)
        try:
            t2 = _time.time()
            from core.position_manager import init_position_manager
            await init_position_manager()
            print(f"✅ Position manager initialized ({_time.time()-t2:.1f}s)")
        except Exception as e:
            print(f"⚠️ Position manager init error: {e}")
        
        # 3. Start WebSocket price feed in background (non-blocking)
        try:
            from core.ws_client import start_price_monitor
            bot = application.bot
            asyncio.create_task(start_price_monitor(bot=bot))
            print("📡 WebSocket price feed started")
        except Exception as e:
            print(f"⚠️ WebSocket start error: {e}")
        
        # 4. Initialize user manager and start session cleanup
        try:
            from core.user_manager import get_user_manager
            um = get_user_manager()
            await um._init_db()
            user_count = await um.get_user_count()
            print(f"👥 User manager initialized ({user_count} registered users)")
            
            # Periodic session cleanup (every 5 minutes)
            async def _session_cleanup_loop():
                while True:
                    await asyncio.sleep(300)
                    try:
                        await um.cleanup_expired()
                    except Exception:
                        pass
            asyncio.create_task(_session_cleanup_loop())
        except Exception as e:
            print(f"⚠️ User manager init error: {e}")
        
        print(f"🚀 Total init: {_time.time()-t0:.1f}s")
    
    app.post_init = post_init
    
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
    app.add_handler(CommandHandler("orders", orders_command))
    app.add_handler(CommandHandler("alerts", alerts_command))
    app.add_handler(CommandHandler("alert", alert_command))
    app.add_handler(CommandHandler("stoploss", stoploss_command))
    app.add_handler(CommandHandler("takeprofit", takeprofit_command))
    app.add_handler(CommandHandler("lock", lock_command))
    app.add_handler(CommandHandler("mystatus", mystatus_command))
    
    # ═══════════════════════════════════════════════════════════════════
    # AUTH CONVERSATION HANDLERS (connect, unlock, disconnect)
    # Must be before other ConversationHandlers
    # ═══════════════════════════════════════════════════════════════════
    app.add_handler(build_connect_handler())
    app.add_handler(build_unlock_handler())
    app.add_handler(build_disconnect_handler())
    
    # ═══════════════════════════════════════════════════════════════════
    # CONVERSATION HANDLERS (must be BEFORE regular callback handlers)
    # These capture text input for custom amount/percentage
    # ═══════════════════════════════════════════════════════════════════
    
    # ConversationHandler for custom buy amount
    custom_amount_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(amount_callback, pattern="^amt_custom$")
        ],
        states={
            CUSTOM_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, custom_amount_input)
            ]
        },
        fallbacks=[
            CommandHandler("buy", buy_command),
            CommandHandler("start", start_command),
            CommandHandler("cancel", start_command),
            CallbackQueryHandler(menu_callback, pattern="^menu$")
        ],
        name="custom_amount_conversation",
        persistent=False,
        per_message=False
    )
    app.add_handler(custom_amount_handler)
    
    # ConversationHandler for custom sell percentage
    custom_sell_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(sell_callback, pattern=r"^sell_\d+_c$")
        ],
        states={
            CUSTOM_SELL_PERCENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, custom_sell_input)
            ]
        },
        fallbacks=[
            CommandHandler("positions", positions_command),
            CommandHandler("start", start_command),
            CommandHandler("cancel", start_command),
            CallbackQueryHandler(menu_callback, pattern="^menu$")
        ],
        name="custom_sell_conversation",
        persistent=False,
        per_message=False
    )
    app.add_handler(custom_sell_handler)
    
    # ConversationHandler for inline search button
    search_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(search_callback, pattern="^search$")
        ],
        states={
            SEARCH_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, search_text_input)
            ]
        },
        fallbacks=[
            CommandHandler("start", start_command),
            CommandHandler("cancel", start_command),
            CommandHandler("search", search_command),
            CallbackQueryHandler(menu_callback, pattern="^menu$")
        ],
        name="search_conversation",
        persistent=False,
        per_message=False
    )
    app.add_handler(search_conv_handler)
    
    # ═══════════════════════════════════════════════════════════════════
    # CALLBACK HANDLERS
    # ═══════════════════════════════════════════════════════════════════
    
    # Menu navigation
    app.add_handler(CallbackQueryHandler(menu_callback, pattern="^menu$"))
    app.add_handler(CallbackQueryHandler(balance_callback, pattern="^balance$"))
    app.add_handler(CallbackQueryHandler(positions_command, pattern="^positions$"))
    app.add_handler(CallbackQueryHandler(buy_command, pattern="^buy$"))
    # Note: search$ is now handled by ConversationHandler above
    app.add_handler(CallbackQueryHandler(favorites_callback, pattern="^favorites$"))
    app.add_handler(CallbackQueryHandler(hot_callback, pattern="^hot$"))
    
    # Position handlers (non-custom - custom is handled by ConversationHandler above)
    app.add_handler(CallbackQueryHandler(position_detail_callback, pattern=r"^pos_\d+$"))
    app.add_handler(CallbackQueryHandler(sell_callback, pattern=r"^sell_\d+_(?!c$)\w+$"))
    app.add_handler(CallbackQueryHandler(confirm_sell_callback, pattern=r"^csell_\d+_\d+$"))
    
    # Instant sell - ONE CLICK, NO CONFIRMATION
    app.add_handler(CallbackQueryHandler(instant_sell_callback, pattern=r"^isell_\d+_\d+$"))
    
    # Refresh positions
    app.add_handler(CallbackQueryHandler(refresh_positions_callback, pattern="^refresh_positions$"))
    
    # Trading handlers - EVENT BASED FLOW
    app.add_handler(CallbackQueryHandler(category_callback, pattern="^cat_"))
    app.add_handler(CallbackQueryHandler(sport_callback, pattern="^sp_"))
    
    # League navigation (Sport → Leagues → Events)
    app.add_handler(CallbackQueryHandler(league_callback, pattern=r"^lg_"))
    
    # Event navigation (Events → Sub-Markets)
    app.add_handler(CallbackQueryHandler(event_callback, pattern=r"^evt_\d+$"))
    app.add_handler(CallbackQueryHandler(events_page_callback, pattern=r"^evp_\d+$"))
    app.add_handler(CallbackQueryHandler(sub_market_callback, pattern=r"^sub_\d+_\d+$"))
    
    # Back navigation
    app.add_handler(CallbackQueryHandler(back_events_callback, pattern="^back_events$"))
    app.add_handler(CallbackQueryHandler(back_sub_callback, pattern="^back_sub$"))
    app.add_handler(CallbackQueryHandler(back_out_callback, pattern="^back_out$"))
    
    # Trading flow (non-custom amounts - custom is handled by ConversationHandler)
    app.add_handler(CallbackQueryHandler(outcome_callback, pattern="^out_"))
    app.add_handler(CallbackQueryHandler(amount_callback, pattern=r"^amt_(?!custom)\w+$"))
    app.add_handler(CallbackQueryHandler(execute_buy_callback, pattern="^exec_buy$"))
    
    # Legacy market handlers (for search results)
    app.add_handler(CallbackQueryHandler(market_callback, pattern=r"^mkt_\d+$"))
    app.add_handler(CallbackQueryHandler(page_callback, pattern=r"^pg_\d+$"))
    
    # Favorites handlers
    app.add_handler(CallbackQueryHandler(fav_add_callback, pattern="^fav_add$"))
    app.add_handler(CallbackQueryHandler(fav_view_callback, pattern=r"^fv_\d+$"))
    app.add_handler(CallbackQueryHandler(fav_del_callback, pattern=r"^fd_\d+$"))
    
    # Orders handlers (cancel_all MUST be before cancel_ to avoid pattern shadowing)
    app.add_handler(CallbackQueryHandler(orders_callback, pattern="^orders$"))
    app.add_handler(CallbackQueryHandler(order_book_callback, pattern="^orderbook$"))
    app.add_handler(CallbackQueryHandler(cancel_all_callback, pattern="^cancel_all$"))
    app.add_handler(CallbackQueryHandler(cancel_order_callback, pattern="^cancel_"))
    
    # Alerts handlers
    app.add_handler(CallbackQueryHandler(alerts_callback, pattern="^alerts$"))
    app.add_handler(CallbackQueryHandler(delete_alert_callback, pattern="^del_alert_"))
    
    # Error handler
    app.add_error_handler(error_handler)
    
    # ═══════════════════════════════════════════════════════════════════
    # START BOT
    # ═══════════════════════════════════════════════════════════════════
    print("🚀 Starting Polymarket Telegram Sniper Bot...")
    print("⚡ Features: Instant sell, live P&L, WebSocket prices")
    print("� Multi-user: /connect → /unlock → trade")
    print("�📊 Sports flow: Sport → Events → Sub-Markets → Yes/No")
    print("Press Ctrl+C to stop.\n")
        # Delete any existing webhook and drop pending updates to avoid 409 Conflict
    # This ensures only this instance polls for updates
    async def post_init(application):
        await application.bot.delete_webhook(drop_pending_updates=True)
        print("✅ Webhook cleared, polling mode active")
    
    app.post_init = post_init    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        print(f"💥 FATAL: {e}", flush=True)
        traceback.print_exc()
        raise
