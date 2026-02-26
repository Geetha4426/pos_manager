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
    from html import escape as esc
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
    
    post_status = None  # Track POST result for diagnostics
    
    lines = [
        f"🔧 <b>Signature Test</b>\n",
        f"<b>sig_type:</b> {sig_type} (0=EOA, 1=Proxy, 2=GnosisSafe)",
        f"<b>signer:</b> <code>{esc(str(signer_addr))}</code>",
        f"<b>funder:</b> <code>{esc(str(funder))}</code>",
        f"<b>same?:</b> {'YES ⚠️' if str(signer_addr).lower() == str(funder).lower() else 'NO ✅ (expected for proxy)'}",
        "",
    ]
    
    # Test 1: Create API creds
    try:
        creds = cc.create_or_derive_api_creds()
        cc.set_api_creds(creds)
        lines.append("✅ API creds: OK")
    except Exception as e:
        lines.append(f"❌ API creds: {esc(str(e))}")
    
    # Test 2: Fetch a real active market token to use for signing test
    test_token = None
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as hc:
            resp = await hc.get(
                "https://gamma-api.polymarket.com/markets",
                params={"closed": "false", "limit": "1", "active": "true"},
            )
            mkts = resp.json()
            if mkts and isinstance(mkts, list):
                test_token = mkts[0].get("clobTokenIds")
                if test_token:
                    # clobTokenIds is a JSON string like '["tok1","tok2"]'
                    import json
                    tokens = json.loads(test_token) if isinstance(test_token, str) else test_token
                    test_token = tokens[0] if tokens else None
                if not test_token:
                    test_token = mkts[0].get("tokens", [{}])[0].get("token_id")
                lines.append(f"✅ Found active market token: ...{str(test_token)[-8:]}")
            else:
                lines.append("❌ No active markets found on Gamma API")
    except Exception as e:
        lines.append(f"❌ Fetch active market: {esc(str(e))}")
    
    # Helper to safely stringify EIP712 struct fields (may be objects, not strings)
    def _s(val):
        """Convert EIP712 struct field to plain string, HTML-escaped."""
        s = str(val) if val is not None else '?'
        # Some fields are EIP712 types with hex values
        if hasattr(val, 'value'):
            s = str(val.value)
        elif hasattr(val, '__hex__'):
            s = hex(val)
        return esc(s)
    
    # Test 3: Try signing a GTC limit order with the real token
    signed = None
    if test_token:
        try:
            from py_clob_client.clob_types import OrderArgs, MarketOrderArgs, OrderType
            from py_clob_client.order_builder.constants import BUY
            
            order_args = OrderArgs(
                token_id=test_token,
                price=0.01,
                size=5.0,
                side=BUY
            )
            signed = cc.create_order(order_args)
            lines.append(f"✅ GTC sign: OK")
            
            if hasattr(signed, 'order'):
                o = signed.order
                lines.append(f"   maker: <code>{_s(getattr(o, 'maker', '?'))}</code>")
                lines.append(f"   signer: <code>{_s(getattr(o, 'signer', '?'))}</code>")
                lines.append(f"   sigType: {_s(getattr(o, 'signatureType', getattr(o, 'sigType', '?')))}")
        except Exception as e:
            lines.append(f"❌ GTC sign: {esc(str(e))}")
    else:
        lines.append("⏭️ Skipping sign test (no token)")
    
    # Test 3b: Try signing a FAK market order (this is what buy_market uses)
    fak_signed = None
    if test_token:
        try:
            from py_clob_client.clob_types import MarketOrderArgs, OrderType
            from py_clob_client.order_builder.constants import BUY
            
            mkt_args = MarketOrderArgs(
                token_id=test_token,
                amount=1.0,
                side=BUY
            )
            fak_signed = cc.create_market_order(mkt_args)
            lines.append(f"✅ FAK sign: OK")
            
            if hasattr(fak_signed, 'order'):
                o = fak_signed.order
                lines.append(f"   maker: <code>{_s(getattr(o, 'maker', '?'))}</code>")
                lines.append(f"   sigType: {_s(getattr(o, 'signatureType', getattr(o, 'sigType', '?')))}")
        except Exception as e:
            lines.append(f"❌ FAK sign: {esc(str(e))}")
    
    # Test 4: Post order via RAW httpx (bypass py-clob post_order to get full response)
    post_target = fak_signed or signed
    post_type = "FAK" if fak_signed else "GTC"
    post_label = "FAK" if fak_signed else "GTC"
    if post_target:
        try:
            import json as _json
            from py_clob_client.headers.headers import create_level_2_headers
            from py_clob_client.clob_types import RequestArgs
            
            # Build exact same body as post_order
            body = {
                "order": post_target.dict(),
                "owner": cc.creds.api_key,
                "orderType": post_type,
                "postOnly": False,
            }
            serialized = _json.dumps(body, separators=(",", ":"), ensure_ascii=False)
            
            # Show key order fields
            od = body["order"]
            lines.append(f"\n<b>Order payload:</b>")
            lines.append(f"   maker: <code>{esc(str(od.get('maker','')))[:20]}...</code>")
            lines.append(f"   signer: <code>{esc(str(od.get('signer','')))[:20]}...</code>")
            lines.append(f"   sigType: {od.get('signatureType', '?')}")
            lines.append(f"   side: {od.get('side', '?')}")
            lines.append(f"   tokenId: ...{esc(str(od.get('tokenId','')))[-8:]}")
            lines.append(f"   sig: <code>{esc(str(od.get('signature','')))[:20]}...</code>")
            
            # Build L2 auth headers
            req_args = RequestArgs(
                method="POST",
                request_path="/order",
                body=body,
                serialized_body=serialized,
            )
            headers = create_level_2_headers(cc.signer, cc.creds, req_args)
            headers["Content-Type"] = "application/json"
            headers["User-Agent"] = "py_clob_client"
            
            lines.append(f"\n<b>Auth headers:</b>")
            lines.append(f"   POLY_ADDRESS: <code>{esc(headers.get('POLY_ADDRESS','')[:16])}...</code>")
            lines.append(f"   POLY_API_KEY: <code>{esc(headers.get('POLY_API_KEY','')[:12])}...</code>")
            
            # Post via raw httpx to relay
            import httpx
            relay_url = cc.host + "/order"
            async with httpx.AsyncClient(timeout=15) as hc:
                raw_resp = await hc.post(relay_url, content=serialized.encode(), headers=headers)
            post_status = raw_resp.status_code
            
            lines.append(f"\n<b>POST {post_label} → {esc(cc.host[:30])}:</b>")
            lines.append(f"   status: {raw_resp.status_code}")
            resp_text = raw_resp.text[:200]
            lines.append(f"   body: <code>{esc(resp_text)}</code>")
            
            if raw_resp.status_code == 200:
                try:
                    rj = raw_resp.json()
                    if rj.get('success'):
                        lines.append(f"✅ Post {post_label}: SUCCESS 🎉")
                        oid = rj.get('orderID', '')
                        if oid:
                            try:
                                cc.cancel(oid)
                                lines.append(f"   (cancelled)")
                            except Exception:
                                lines.append(f"   ⚠️ Cancel failed. ID: {oid}")
                except Exception:
                    pass
                    
        except Exception as e:
            lines.append(f"❌ Post {post_label}: {esc(str(e)[:200])}")
    else:
        lines.append("⏭️ Skipping post test (signing failed)")
    
    # ═══ On-chain diagnostics ═══
    import httpx  # Ensure available outside POST try block
    lines.append(f"\n<b>═══ On-chain Checks ═══</b>")
    rpc_url = "https://polygon-bor-rpc.publicnode.com"
    usdc_contract = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC.e
    
    # Check USDC balance on both addresses
    for label, addr in [("EOA", str(signer_addr)), ("Funder", str(funder))]:
        if not addr or addr == '?' or not addr.startswith('0x'):
            continue
        try:
            padded = addr[2:].lower().zfill(64)
            call_data = f"0x70a08231{padded}"  # balanceOf(address)
            async with httpx.AsyncClient(timeout=10) as hc:
                rpc_resp = await hc.post(rpc_url, json={
                    "jsonrpc": "2.0", "method": "eth_call",
                    "params": [{"to": usdc_contract, "data": call_data}, "latest"],
                    "id": 1,
                })
                result = rpc_resp.json().get("result", "0x0")
                balance_wei = int(result, 16)
                balance_usd = balance_wei / 1e6
                emoji = "💰" if balance_usd > 0.01 else "⚠️"
                lines.append(f"   {emoji} {label} USDC.e: ${balance_usd:.2f}")
        except Exception as e:
            lines.append(f"   ⚠️ {label} balance: {esc(str(e)[:50])}")
    
    # Check operator approval on exchange contracts (only for proxy sig types)
    if str(sig_type) not in ('0', '?') and str(signer_addr).startswith('0x') and str(funder).startswith('0x'):
        exchanges = [
            ("CTF", "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"),
            ("NegRisk", "0xC5d563A36AE78145C45a50134d48A1215220f80a"),
        ]
        owner_padded = str(funder)[2:].lower().zfill(64)
        operator_padded = str(signer_addr)[2:].lower().zfill(64)
        # isApprovedForAll(address,address) selector
        call_data = f"0xe985e9c5{owner_padded}{operator_padded}"
        for ex_name, ex_addr in exchanges:
            try:
                async with httpx.AsyncClient(timeout=10) as hc:
                    rpc_resp = await hc.post(rpc_url, json={
                        "jsonrpc": "2.0", "method": "eth_call",
                        "params": [{"to": ex_addr, "data": call_data}, "latest"],
                        "id": 1,
                    })
                    result = rpc_resp.json().get("result", "0x0")
                    approved = int(result, 16) != 0
                    st = "✅ Approved" if approved else "❌ NOT approved"
                    lines.append(f"   {ex_name}: signer→funder {st}")
            except Exception as e:
                lines.append(f"   ⚠️ {ex_name}: {esc(str(e)[:50])}")
    
    # Check CLOB allowance
    try:
        from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
        ba_params = BalanceAllowanceParams(
            asset_type=AssetType.COLLATERAL,
            signature_type=int(sig_type) if str(sig_type).isdigit() else 0,
        )
        ba_resp = cc.get_balance_allowance(ba_params)
        if isinstance(ba_resp, dict):
            allowance = float(ba_resp.get('allowance', 0))
            if allowance > 1_000_000:
                allowance /= 1e6
            clob_bal = float(ba_resp.get('balance', 0))
            if clob_bal > 1_000_000:
                clob_bal /= 1e6
            lines.append(f"   CLOB balance: ${clob_bal:.2f}, allowance: ${allowance:.2f}")
    except Exception as e:
        lines.append(f"   ⚠️ CLOB allowance: {esc(str(e)[:60])}")
    
    # Actionable summary
    lines.append("")
    if post_status == 400:
        lines.append("<b>⚠️ Fixing 'invalid signature':</b>")
        lines.append("1️⃣ Try <b>sig_type=0</b> (EOA mode):")
        lines.append("   /disconnect → /connect")
        lines.append("   Leave funder empty, pick EOA")
        lines.append("2️⃣ Ensure USDC is on your EOA address")
        lines.append("3️⃣ If using proxy wallet:")
        lines.append("   Operator approval must exist on-chain")
    else:
        lines.append("<b>If issues persist:</b>")
        lines.append("→ /disconnect → /connect with correct settings")
    
    # Send (split if too long for Telegram's 4096 limit)
    full_text = '\n'.join(lines)
    if len(full_text) > 4000:
        mid = len(lines) // 2
        await update.message.reply_text('\n'.join(lines[:mid]), parse_mode='HTML')
        await update.message.reply_text('\n'.join(lines[mid:]), parse_mode='HTML')
    else:
        await update.message.reply_text(full_text, parse_mode='HTML')
