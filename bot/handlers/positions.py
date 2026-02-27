"""
Position Handlers

Handles /positions command, sell operations, and instant sell.
Features:
- Live P&L with best bid/ask from WS
- One-click instant sell (FOK → GTC fallback)
- Refresh button for live price updates
- Position detail with spread and fee info
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config import Config
from core.polymarket_client import get_polymarket_client, require_auth, Position
from core.alerts import get_alert_manager, AlertType
from bot.keyboards.inline import (
    positions_keyboard, position_detail_keyboard, sell_confirm_keyboard,
    instant_sell_keyboard
)


# Conversation states
CUSTOM_SELL_PERCENT = 0
STOP_LOSS_PRICE = 1
TAKE_PROFIT_PRICE = 2


async def positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /positions command - show all active positions with live P&L.
    
    Filters out resolved/settled markets (price ≤ 2¢ or ≥ 98¢, or -100% P&L).
    Shows settled positions in a compact section at the bottom.
    """
    client = await require_auth(update)
    if not client:
        return
    positions = await client.get_positions()
    
    # Try to enrich with WS live prices
    try:
        from core.ws_client import get_ws_client
        ws = get_ws_client()
        for pos in positions:
            snap = ws.get_snapshot(pos.token_id)
            if snap:
                pos.current_price = snap.price
                pos.pnl = (snap.price - pos.avg_price) * pos.size
                pos.pnl_percent = ((snap.price / pos.avg_price) - 1) * 100 if pos.avg_price > 0 else 0
                pos.value = snap.price * pos.size
    except Exception:
        pass
    
    # Try position manager for even richer data
    try:
        from core.position_manager import get_position_manager
        pm = get_position_manager()
        for pos in positions:
            live = pm.get_position(pos.token_id)
            if live and live.best_bid > 0:
                pos.current_price = live.best_bid
                pos.pnl = live.pnl
                pos.pnl_percent = live.pnl_percent
                pos.value = live.value
    except Exception:
        pass
    
    # ── Split: active vs settled/resolved ──
    active_positions = []
    settled_positions = []
    for pos in positions:
        # Settled: price snapped to 0/1 or extreme loss/gain
        if (pos.current_price <= 0.02 or pos.current_price >= 0.98
                or pos.pnl_percent <= -95 or pos.pnl_percent >= 95):
            settled_positions.append(pos)
        else:
            active_positions.append(pos)
    
    # Store ONLY active positions for sell callbacks (keyboard indices)
    context.user_data['positions'] = active_positions
    
    if not active_positions and not settled_positions:
        text = (
            "📊 <b>Portfolio</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "<i>No open positions</i>\n\n"
            "Use /buy to open a new position."
        )
        if update.callback_query:
            await update.callback_query.edit_message_text(text, parse_mode='HTML')
        else:
            await update.message.reply_text(text, parse_mode='HTML')
        return
    
    mode_tag = "📝 PAPER" if Config.is_paper_mode() else "🔴 LIVE"
    
    if active_positions:
        # Build active positions display
        total_value = sum(p.value for p in active_positions)
        total_pnl = sum(p.pnl for p in active_positions)
        pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
        
        text = (
            f"📊 <b>Portfolio</b> | {mode_tag}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 ${total_value:.2f}  |  {pnl_emoji} ${total_pnl:+.2f}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
        )
        
        for i, pos in enumerate(active_positions):
            emoji = "🟢" if pos.pnl >= 0 else "🔴"
            text += (
                f"\n{emoji} <b>{pos.market_question[:40]}</b>\n"
                f"    {pos.outcome} · {pos.size:.1f}sh @ {pos.avg_price*100:.0f}¢ → {pos.current_price*100:.0f}¢\n"
                f"    ${pos.value:.2f}  |  ${pos.pnl:+.2f} ({pos.pnl_percent:+.1f}%)\n"
            )
        
        text += (
            f"\n━━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>Tap to manage · ⚡ = instant sell</i>"
        )
    else:
        text = (
            f"📊 <b>Portfolio</b> | {mode_tag}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<i>No active positions</i>\n"
            f"Use /buy to open a new position."
        )
    
    # Append settled/resolved section (compact, no sell buttons)
    if settled_positions:
        text += (
            f"\n\n📜 <b>Settled ({len(settled_positions)})</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
        )
        for pos in settled_positions[:5]:  # Show max 5 settled
            if pos.current_price >= 0.98:
                tag = "✅ WON"
            elif pos.current_price <= 0.02:
                tag = "❌ LOST"
            else:
                tag = "🏁 ENDED"
            text += (
                f"{tag}  <b>{pos.market_question[:35]}</b>\n"
                f"       {pos.outcome} · {pos.size:.1f}sh · ${pos.pnl:+.2f}\n"
            )
        if len(settled_positions) > 5:
            text += f"\n<i>+{len(settled_positions) - 5} more settled positions</i>\n"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, 
            parse_mode='HTML',
            reply_markup=positions_keyboard(active_positions) if active_positions else None
        )
    else:
        await update.message.reply_text(
            text, 
            parse_mode='HTML',
            reply_markup=positions_keyboard(active_positions) if active_positions else None
        )


async def refresh_positions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle refresh button - reload positions with fresh prices."""
    query = update.callback_query
    await query.answer("🔄 Refreshing...")
    await positions_command(update, context)


async def position_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle position detail view callback with live bid/ask data."""
    query = update.callback_query
    await query.answer()
    
    # Extract position index from callback: pos_0 -> 0
    idx = int(query.data.split('_')[1])
    
    positions = context.user_data.get('positions', [])
    if idx >= len(positions):
        await query.edit_message_text("⚠️ Position not found")
        return
    
    pos = positions[idx]
    
    # Store current position for sell operations
    context.user_data['current_position'] = pos
    context.user_data['current_position_index'] = idx
    
    # Get live bid/ask from WS
    best_bid = pos.current_price
    best_ask = 0.0
    spread = 0.0
    try:
        from core.ws_client import get_ws_client
        ws = get_ws_client()
        snap = ws.get_snapshot(pos.token_id)
        if snap:
            best_bid = snap.best_bid if snap.best_bid > 0 else pos.current_price
            best_ask = snap.best_ask if snap.best_ask > 0 else 0
            spread = snap.spread
    except Exception:
        pass
    
    # Try position manager for even more detail
    try:
        from core.position_manager import get_position_manager, calc_fee
        pm = get_position_manager()
        live = pm.get_position(pos.token_id)
        if live and live.best_bid > 0:
            best_bid = live.best_bid
            best_ask = live.best_ask
            spread = live.spread
    except Exception:
        pass
    
    pnl = (best_bid - pos.avg_price) * pos.size
    pnl_pct = ((best_bid / pos.avg_price) - 1) * 100 if pos.avg_price > 0 else 0
    pnl_color = "🟢" if pnl >= 0 else "🔴"
    value = best_bid * pos.size
    
    # Calculate estimated fee on sell
    try:
        from core.position_manager import calc_fee
        sell_fee = calc_fee(best_bid)
        fee_pct = sell_fee * 100
    except Exception:
        fee_pct = 0
    
    text = (
        f"📊 <b>Position Detail</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 <b>{pos.market_question}</b>\n\n"
        f"🎯 {pos.outcome}\n"
        f"📦 {pos.size:.2f} shares\n\n"
        f"Entry     {pos.avg_price*100:.1f}¢\n"
        f"Bid       {best_bid*100:.1f}¢"
    )
    
    if best_ask > 0:
        text += f"  |  Ask  {best_ask*100:.1f}¢"
    if spread > 0:
        text += f"\nSpread    {spread*100:.1f}¢"
    
    text += (
        f"\n━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Value    ${value:.2f}\n"
        f"{pnl_color} P&L      ${pnl:+.2f} ({pnl_pct:+.1f}%)\n"
    )
    
    if fee_pct > 0:
        text += f"💸 Fee      {fee_pct:.2f}%\n"
    
    text += (
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>⚡ = FOK market sell (fastest)</i>"
    )
    
    await query.edit_message_text(
        text,
        parse_mode='HTML',
        reply_markup=instant_sell_keyboard(idx)
    )


async def instant_sell_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle instant sell - ONE CLICK, NO CONFIRMATION."""
    query = update.callback_query
    
    # Parse: isell_0_100
    parts = query.data.split('_')
    pos_index = int(parts[1])
    percent = int(parts[2])
    
    pos = context.user_data.get('current_position')
    if not pos:
        positions = context.user_data.get('positions', [])
        if pos_index < len(positions):
            pos = positions[pos_index]
    
    if not pos:
        await query.answer("⚠️ Position not found")
        await query.edit_message_text("⚠️ Position not found. Use /positions to refresh.")
        return
    
    await query.answer("⚡ Selling NOW...")
    
    # Show selling status immediately 
    await query.edit_message_text(
        f"⚡ <b>SELLING {percent}%</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 {pos.market_question[:50]}\n"
        f"📦 {pos.size * percent / 100:.1f} shares\n\n"
        f"<i>Executing FOK market sell...</i>",
        parse_mode='HTML'
    )
    
    client = await require_auth(update)
    if not client:
        return
    
    # Use instant_sell for maximum speed
    if hasattr(client, 'instant_sell'):
        result = await client.instant_sell(pos.token_id, percent=percent)
    else:
        result = await client.sell_market(pos.token_id, percent=percent)
    
    if result.success:
        # Update position manager
        try:
            from core.position_manager import get_position_manager
            pm = get_position_manager()
            remaining = pos.size * (1 - percent / 100)
            await pm.update_position_size(pos.token_id, remaining)
        except Exception:
            pass
        
        proceeds = result.filled_size * result.avg_price if result.avg_price > 0 else pos.value * (percent / 100)
        pnl = (result.avg_price - pos.avg_price) * result.filled_size if result.avg_price > 0 else 0
        pnl_emoji = "🟢" if pnl >= 0 else "🔴"
        
        text = (
            f"✅ <b>Sold Successfully</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 {pos.market_question[:50]}\n\n"
            f"📦 Sold     {result.filled_size:.1f} shares\n"
            f"💵 Price    {result.avg_price*100:.1f}¢\n"
            f"💰 Proceeds ${proceeds:.2f}\n"
            f"{pnl_emoji} P&L      ${pnl:+.2f}\n"
        )
        if result.order_id:
            text += f"━━━━━━━━━━━━━━━━━━━━━\n🆔 <code>{result.order_id[:16]}...</code>\n"
        text += f"\n<i>{'📝 Paper' if Config.is_paper_mode() else '💱 Live'}</i>"
    else:
        text = (
            f"❌ <b>Sell Failed</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 {pos.market_question[:50]}\n\n"
            f"Error: {result.error}\n\n"
            f"<i>Try again or reduce size</i>"
        )
    
    # Add back to positions button
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Back to Positions", callback_data="refresh_positions")]
    ])
    
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=keyboard)


async def sell_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle sell button callbacks (for custom %)."""
    query = update.callback_query
    await query.answer()
    
    # Parse: sell_0_100 or sell_0_c
    parts = query.data.split('_')
    pos_index = int(parts[1])
    percent_str = parts[2]
    
    if percent_str == 'c':
        # Ask for custom percentage
        await query.edit_message_text(
            "✏️ <b>Custom Sell</b>\n\nEnter percentage to sell (1-100):",
            parse_mode='HTML'
        )
        context.user_data['sell_pos_index'] = pos_index
        return CUSTOM_SELL_PERCENT
    
    percent = int(percent_str)
    pos = context.user_data.get('current_position')
    
    if not pos:
        # Try to get from positions list
        positions = context.user_data.get('positions', [])
        if pos_index < len(positions):
            pos = positions[pos_index]
            context.user_data['current_position'] = pos
    
    if not pos:
        await query.edit_message_text("⚠️ Position not found")
        return
    
    sell_value = pos.value * (percent / 100)
    sell_shares = pos.size * (percent / 100)
    
    context.user_data['sell_percent'] = percent
    
    text = (
        f"⚡ <b>Confirm Sell</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 {pos.market_question}\n"
        f"🎯 {pos.outcome}\n\n"
        f"Selling   {percent}%\n"
        f"Shares    {sell_shares:.2f}\n"
        f"Value     ${sell_value:.2f}\n"
        f"Price     {pos.current_price*100:.1f}¢\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>FOK market order · instant execution</i>"
    )
    
    await query.edit_message_text(
        text,
        parse_mode='HTML',
        reply_markup=sell_confirm_keyboard(pos_index, percent)
    )


async def confirm_sell_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Execute the sell order."""
    query = update.callback_query
    await query.answer("⚡ Executing sell...")
    
    # Parse: csell_0_100
    parts = query.data.split('_')
    pos_index = int(parts[1])
    percent = int(parts[2])
    
    pos = context.user_data.get('current_position')
    if not pos:
        positions = context.user_data.get('positions', [])
        if pos_index < len(positions):
            pos = positions[pos_index]
    
    if not pos:
        await query.edit_message_text("⚠️ Position not found. Use /positions to refresh.")
        return
    
    client = await require_auth(update)
    if not client:
        return
    result = await client.sell_market(pos.token_id, percent=percent)
    
    if result.success:
        # Update position manager
        try:
            from core.position_manager import get_position_manager
            pm = get_position_manager()
            remaining = pos.size * (1 - percent / 100)
            await pm.update_position_size(pos.token_id, remaining)
        except Exception:
            pass
        
        text = (
            f"✅ <b>Sell Executed</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📦 {result.filled_size:.2f} shares @ {result.avg_price*100:.1f}¢\n"
            f"🆔 <code>{result.order_id[:16]}...</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>{'📝 Paper trade' if Config.is_paper_mode() else '💱 Live trade'}</i>"
        )
    else:
        err = result.error or 'Unknown error'
        err_lower = err.lower()
        if 'geo' in err_lower or 'region' in err_lower or '451' in err:
            hint = "\n\n\ud83c\udf0d Server may be in a restricted region."
        elif 'expired' in err_lower or 'auth' in err_lower or '403' in err:
            hint = "\n\n\ud83d\udd04 Session may have expired. Try again."
        elif 'insufficient' in err_lower or 'size' in err_lower:
            hint = "\n\nReduce sell size or check position."
        else:
            hint = "\n\nPlease try again or check your position."
        text = (
            f"\u274c <b>Sell Failed</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Error: {err}{hint}"
        )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Back to Positions", callback_data="refresh_positions")]
    ])
    
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=keyboard)


async def custom_sell_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle custom sell percentage input."""
    try:
        percent = int(update.message.text.strip())
        if percent < 1 or percent > 100:
            await update.message.reply_text("⚠️ Enter a number between 1 and 100")
            return CUSTOM_SELL_PERCENT
        
        pos_index = context.user_data.get('sell_pos_index', 0)
        pos = context.user_data.get('current_position')
        
        if not pos:
            positions = context.user_data.get('positions', [])
            if pos_index < len(positions):
                pos = positions[pos_index]
        
        if not pos:
            await update.message.reply_text("⚠️ Position not found. Use /positions again.")
            return ConversationHandler.END
        
        sell_value = pos.value * (percent / 100)
        sell_shares = pos.size * (percent / 100)
        
        context.user_data['sell_percent'] = percent
        
        text = (
            f"⚡ <b>Confirm Sell</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 {pos.market_question}\n"
            f"🎯 {pos.outcome}\n\n"
            f"Selling   {percent}%\n"
            f"Shares    {sell_shares:.2f}\n"
            f"Value     ${sell_value:.2f}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>FOK market order · instant execution</i>"
        )
        
        await update.message.reply_text(
            text,
            parse_mode='HTML',
            reply_markup=sell_confirm_keyboard(pos_index, percent)
        )
        
        return ConversationHandler.END
        
    except ValueError:
        await update.message.reply_text("⚠️ Please enter a valid number (1-100)")
        return CUSTOM_SELL_PERCENT


# ═══════════════════════════════════════════════════════════════════
# STOP LOSS & TAKE PROFIT (from position detail)
# ═══════════════════════════════════════════════════════════════════

async def stop_loss_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Stop Loss button from position detail — ask for price."""
    query = update.callback_query
    await query.answer()
    
    # Parse: sl_0
    pos_index = int(query.data.split('_')[1])
    
    pos = context.user_data.get('current_position')
    if not pos:
        positions = context.user_data.get('positions', [])
        if pos_index < len(positions):
            pos = positions[pos_index]
    
    if not pos:
        await query.edit_message_text("⚠️ Position not found. Use /positions to refresh.")
        return ConversationHandler.END
    
    context.user_data['sl_tp_position'] = pos
    context.user_data['sl_tp_index'] = pos_index
    
    current_price_cents = int(pos.current_price * 100)
    # Suggest some stop loss levels
    suggested = [max(1, current_price_cents - 10), max(1, current_price_cents - 20), max(1, current_price_cents - 30)]
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"🛑 {suggested[0]}¢", callback_data=f"slset_{pos_index}_{suggested[0]}"),
            InlineKeyboardButton(f"🛑 {suggested[1]}¢", callback_data=f"slset_{pos_index}_{suggested[1]}"),
            InlineKeyboardButton(f"🛑 {suggested[2]}¢", callback_data=f"slset_{pos_index}_{suggested[2]}"),
        ],
        [InlineKeyboardButton("🔙 Back", callback_data=f"pos_{pos_index}")]
    ])
    
    await query.edit_message_text(
        f"🛑 <b>Set Stop Loss</b>\n\n"
        f"📋 {pos.market_question[:50]}\n"
        f"📍 Current price: {current_price_cents}¢\n"
        f"💵 Entry: {pos.avg_price*100:.0f}¢\n\n"
        f"Select a stop-loss price or send a custom price in cents (e.g. 35):\n\n"
        f"<i>When price drops below your stop, position auto-sells 100%.</i>",
        parse_mode='HTML',
        reply_markup=keyboard
    )
    return STOP_LOSS_PRICE


async def take_profit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Take Profit button from position detail — ask for price."""
    query = update.callback_query
    await query.answer()
    
    # Parse: tp_0
    pos_index = int(query.data.split('_')[1])
    
    pos = context.user_data.get('current_position')
    if not pos:
        positions = context.user_data.get('positions', [])
        if pos_index < len(positions):
            pos = positions[pos_index]
    
    if not pos:
        await query.edit_message_text("⚠️ Position not found. Use /positions to refresh.")
        return ConversationHandler.END
    
    context.user_data['sl_tp_position'] = pos
    context.user_data['sl_tp_index'] = pos_index
    
    current_price_cents = int(pos.current_price * 100)
    # Suggest some take profit levels
    suggested = [min(99, current_price_cents + 10), min(99, current_price_cents + 20), min(99, current_price_cents + 30)]
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"🎯 {suggested[0]}¢", callback_data=f"tpset_{pos_index}_{suggested[0]}"),
            InlineKeyboardButton(f"🎯 {suggested[1]}¢", callback_data=f"tpset_{pos_index}_{suggested[1]}"),
            InlineKeyboardButton(f"🎯 {suggested[2]}¢", callback_data=f"tpset_{pos_index}_{suggested[2]}"),
        ],
        [InlineKeyboardButton("🔙 Back", callback_data=f"pos_{pos_index}")]
    ])
    
    await query.edit_message_text(
        f"🎯 <b>Set Take Profit</b>\n\n"
        f"📋 {pos.market_question[:50]}\n"
        f"📍 Current price: {current_price_cents}¢\n"
        f"💵 Entry: {pos.avg_price*100:.0f}¢\n\n"
        f"Select a take-profit price or send a custom price in cents (e.g. 80):\n\n"
        f"<i>When price rises above your target, position auto-sells 100%.</i>",
        parse_mode='HTML',
        reply_markup=keyboard
    )
    return TAKE_PROFIT_PRICE


async def sl_set_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle stop loss price button selection."""
    query = update.callback_query
    await query.answer("🛑 Setting stop loss...")
    
    # Parse: slset_0_35
    parts = query.data.split('_')
    pos_index = int(parts[1])
    price_cents = int(parts[2])
    
    pos = context.user_data.get('sl_tp_position')
    if not pos:
        positions = context.user_data.get('positions', [])
        if pos_index < len(positions):
            pos = positions[pos_index]
    
    if not pos:
        await query.edit_message_text("⚠️ Position not found.")
        return
    
    stop_price = price_cents / 100.0
    user_id = str(update.effective_user.id)
    
    manager = get_alert_manager()
    alert_id = await manager.add_stop_loss(
        user_id=user_id,
        token_id=pos.token_id,
        market_question=pos.market_question,
        stop_price=stop_price
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Back to Position", callback_data=f"pos_{pos_index}")],
        [InlineKeyboardButton("🔔 View All Alerts", callback_data="alerts")]
    ])
    
    await query.edit_message_text(
        f"✅ <b>Stop Loss Set!</b>\n\n"
        f"📋 {pos.market_question[:50]}\n"
        f"🛑 Trigger: {price_cents}¢ (sell when price drops below)\n"
        f"📍 Current: {pos.current_price*100:.0f}¢\n"
        f"📦 Will sell: 100% of position\n\n"
        f"<i>Auto-sell executes when price monitor detects trigger.</i>",
        parse_mode='HTML',
        reply_markup=keyboard
    )


async def tp_set_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle take profit price button selection."""
    query = update.callback_query
    await query.answer("🎯 Setting take profit...")
    
    # Parse: tpset_0_80
    parts = query.data.split('_')
    pos_index = int(parts[1])
    price_cents = int(parts[2])
    
    pos = context.user_data.get('sl_tp_position')
    if not pos:
        positions = context.user_data.get('positions', [])
        if pos_index < len(positions):
            pos = positions[pos_index]
    
    if not pos:
        await query.edit_message_text("⚠️ Position not found.")
        return
    
    target_price = price_cents / 100.0
    user_id = str(update.effective_user.id)
    
    manager = get_alert_manager()
    alert_id = await manager.add_take_profit(
        user_id=user_id,
        token_id=pos.token_id,
        market_question=pos.market_question,
        target_price=target_price
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Back to Position", callback_data=f"pos_{pos_index}")],
        [InlineKeyboardButton("🔔 View All Alerts", callback_data="alerts")]
    ])
    
    await query.edit_message_text(
        f"✅ <b>Take Profit Set!</b>\n\n"
        f"📋 {pos.market_question[:50]}\n"
        f"🎯 Trigger: {price_cents}¢ (sell when price rises above)\n"
        f"📍 Current: {pos.current_price*100:.0f}¢\n"
        f"📦 Will sell: 100% of position\n\n"
        f"<i>Auto-sell executes when price monitor detects trigger.</i>",
        parse_mode='HTML',
        reply_markup=keyboard
    )


async def stop_loss_price_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle custom stop loss price text input."""
    try:
        price_cents = int(update.message.text.strip())
        if price_cents < 1 or price_cents > 99:
            await update.message.reply_text("⚠️ Price must be between 1¢ and 99¢")
            return STOP_LOSS_PRICE
        
        pos = context.user_data.get('sl_tp_position')
        if not pos:
            await update.message.reply_text("⚠️ Position not found. Use /positions again.")
            return ConversationHandler.END
        
        stop_price = price_cents / 100.0
        user_id = str(update.effective_user.id)
        pos_index = context.user_data.get('sl_tp_index', 0)
        
        manager = get_alert_manager()
        await manager.add_stop_loss(
            user_id=user_id,
            token_id=pos.token_id,
            market_question=pos.market_question,
            stop_price=stop_price
        )
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Back to Position", callback_data=f"pos_{pos_index}")],
            [InlineKeyboardButton("🔔 View All Alerts", callback_data="alerts")]
        ])
        
        await update.message.reply_text(
            f"✅ <b>Stop Loss Set!</b>\n\n"
            f"📋 {pos.market_question[:50]}\n"
            f"🛑 Trigger: {price_cents}¢\n"
            f"📍 Current: {pos.current_price*100:.0f}¢\n\n"
            f"<i>Auto-sell when price drops below trigger.</i>",
            parse_mode='HTML',
            reply_markup=keyboard
        )
        return ConversationHandler.END
        
    except ValueError:
        await update.message.reply_text("⚠️ Enter a valid price in cents (e.g. 35)")
        return STOP_LOSS_PRICE


async def take_profit_price_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle custom take profit price text input."""
    try:
        price_cents = int(update.message.text.strip())
        if price_cents < 1 or price_cents > 99:
            await update.message.reply_text("⚠️ Price must be between 1¢ and 99¢")
            return TAKE_PROFIT_PRICE
        
        pos = context.user_data.get('sl_tp_position')
        if not pos:
            await update.message.reply_text("⚠️ Position not found. Use /positions again.")
            return ConversationHandler.END
        
        target_price = price_cents / 100.0
        user_id = str(update.effective_user.id)
        pos_index = context.user_data.get('sl_tp_index', 0)
        
        manager = get_alert_manager()
        await manager.add_take_profit(
            user_id=user_id,
            token_id=pos.token_id,
            market_question=pos.market_question,
            target_price=target_price
        )
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Back to Position", callback_data=f"pos_{pos_index}")],
            [InlineKeyboardButton("🔔 View All Alerts", callback_data="alerts")]
        ])
        
        await update.message.reply_text(
            f"✅ <b>Take Profit Set!</b>\n\n"
            f"📋 {pos.market_question[:50]}\n"
            f"🎯 Trigger: {price_cents}¢\n"
            f"📍 Current: {pos.current_price*100:.0f}¢\n\n"
            f"<i>Auto-sell when price rises above trigger.</i>",
            parse_mode='HTML',
            reply_markup=keyboard
        )
        return ConversationHandler.END
        
    except ValueError:
        await update.message.reply_text("⚠️ Enter a valid price in cents (e.g. 80)")
        return TAKE_PROFIT_PRICE
