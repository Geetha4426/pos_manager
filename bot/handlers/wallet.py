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
    actual_sig_type = sig_type
    if client and client.clob_client:
        try:
            signer = client.clob_client.get_address()
        except Exception:
            pass
        actual_funder = getattr(client, '_funder_address', funder_display)
        # Get actual sig_type from the ClobClient (may differ from env var)
        actual_sig_type = getattr(client.clob_client, 'sig_type',
                         getattr(client.clob_client, 'signature_type', sig_type))
    
    # Also check per-user session sig_type
    per_user_sig = "(no session)"
    per_user_funder = "(no session)"
    per_user_signer = "(no session)"
    try:
        from core.user_manager import get_user_manager
        um = get_user_manager()
        user_id = update.effective_user.id
        session = um.get_session(user_id)
        if session:
            per_user_sig = session.signature_type
            per_user_funder = session.funder_address or "(empty)"
            # Get from the session's ClobClient.builder (actual runtime value)
            if session.clob_client:
                builder = getattr(session.clob_client, 'builder', None)
                if builder:
                    per_user_sig = getattr(builder, 'sig_type', per_user_sig)
                    per_user_funder = getattr(builder, 'funder', per_user_funder)
                try:
                    per_user_signer = session.clob_client.get_address()
                except Exception:
                    pass
    except Exception:
        pass
    
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

<b>Env SIGNATURE_TYPE:</b> {sig_type} ({sig_label})
<b>Chain ID:</b> {Config.POLYGON_CHAIN_ID}

<b>Per-User Session (used for trades!):</b>
  sig_type: <b>{per_user_sig}</b> (0=EOA, 1=Proxy, 2=GnosisSafe)
  funder: <code>{per_user_funder}</code>
  signer: <code>{per_user_signer}</code>

<b>CLOB URL:</b> {Config.get_clob_url()}
<b>Relay:</b> {relay}
<b>Relay Auth:</b> {relay_auth}

━━━━━━━━━━━━━━━━━━━
<b>Troubleshooting "invalid signature":</b>

• If you created your Polymarket account via <b>email/browser</b>:
  → sig_type should be <b>1</b>
  → FUNDER_ADDRESS must be your <b>proxy wallet</b> address
  (Find it on polygonscan: the contract that holds your USDC)

• If you use a <b>direct EOA wallet</b> (MetaMask export):
  → sig_type should be <b>0</b>
  → FUNDER_ADDRESS can be empty

• To fix: /disconnect → /connect again with correct settings
• The env var SIGNATURE_TYPE is for the global client (browse only)
• Your per-user sig_type (from /connect) is what matters for trades
"""
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode='HTML')
    else:
        await update.message.reply_text(text, parse_mode='HTML')


async def test_sign_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /test_sign - test order signing to diagnose 'invalid signature' errors."""
    from core.polymarket_client import require_auth
    
    client = await require_auth(update)
    if not client:
        return
    
    cc = client.clob_client
    if not cc:
        await update.message.reply_text("❌ No ClobClient available.")
        return
    
    builder = getattr(cc, 'builder', None)
    sig_type = getattr(builder, 'sig_type', '?') if builder else '?'
    funder = getattr(builder, 'funder', '?') if builder else '?'
    
    try:
        signer_addr = cc.get_address()
    except Exception:
        signer_addr = '?'
    
    lines = [
        f"🔧 <b>Signature Test</b>\n",
        f"<b>sig_type:</b> {sig_type} (0=EOA, 1=Proxy, 2=GnosisSafe)",
        f"<b>signer:</b> <code>{signer_addr}</code>",
        f"<b>funder:</b> <code>{funder}</code>",
        f"<b>same?:</b> {'YES ⚠️' if str(signer_addr).lower() == str(funder).lower() else 'NO ✅ (expected for proxy)'}",
        "",
    ]
    
    # Test 1: Create API creds
    try:
        creds = cc.create_or_derive_api_creds()
        cc.set_api_creds(creds)
        lines.append("✅ API creds: OK")
    except Exception as e:
        lines.append(f"❌ API creds: {e}")
    
    # Test 2: Try signing a dummy order (don't post it)
    try:
        from py_clob_client.clob_types import OrderArgs, OrderType
        from py_clob_client.order_builder.constants import BUY
        
        # Use a known active token_id (USDC dummy)
        test_token = "71321045679252212594626385532706912750332728571942532289631379312455583992563"
        order_args = OrderArgs(
            token_id=test_token,
            price=0.50,
            size=1.0,
            side=BUY
        )
        signed = cc.create_order(order_args)
        lines.append(f"✅ Order signing: OK")
        lines.append(f"   Signed order type: {type(signed).__name__}")
        
        # Check if signed order has expected fields
        if hasattr(signed, 'order'):
            o = signed.order
            lines.append(f"   maker: {getattr(o, 'maker', '?')}")
            lines.append(f"   signer: {getattr(o, 'signer', '?')}")
            lines.append(f"   sigType: {getattr(o, 'signatureType', getattr(o, 'sigType', '?'))}")
    except Exception as e:
        lines.append(f"❌ Order signing: {e}")
    
    # Test 3: Try posting the signed order (this will actually test the relay + polymarket)
    try:
        resp = cc.post_order(signed, OrderType.GTC)
        success = resp.get('success', False) if isinstance(resp, dict) else getattr(resp, 'success', False)
        if success:
            lines.append(f"✅ Post order: SUCCESS")
            # Cancel it immediately
            order_id = resp.get('orderID', '') if isinstance(resp, dict) else getattr(resp, 'orderID', '')
            if order_id:
                try:
                    cc.cancel(order_id)
                    lines.append(f"   (cancelled test order)")
                except Exception:
                    lines.append(f"   ⚠️ Order posted but cancel failed. Order ID: {order_id}")
        else:
            error = resp.get('error', str(resp)) if isinstance(resp, dict) else str(resp)
            lines.append(f"❌ Post order: {error}")
    except Exception as e:
        lines.append(f"❌ Post order: {e}")
    
    await update.message.reply_text('\n'.join(lines), parse_mode='HTML')
