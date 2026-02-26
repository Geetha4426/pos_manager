"""
Debug script: Inspect CLOB trades and market status to find
why closed positions still show up.

Run: python debug_positions.py
"""
import os
import sys
import json
import httpx
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

# Try to use ClobClient for authenticated trade fetch
try:
    from py_clob_client.client import ClobClient
    CLOB_AVAILABLE = True
except ImportError:
    CLOB_AVAILABLE = False
    print("⚠️ py-clob-client not installed")

CLOB_URL = os.getenv('CLOB_RELAY_URL', '').rstrip('/') or 'https://clob.polymarket.com'
GAMMA_URL = 'https://gamma-api.polymarket.com'
PRIVATE_KEY = os.getenv('POLYGON_PRIVATE_KEY', '')
FUNDER = os.getenv('FUNDER_ADDRESS', '')
SIG_TYPE = int(os.getenv('SIGNATURE_TYPE', '1'))
CHAIN_ID = int(os.getenv('POLYGON_CHAIN_ID', '137'))

now_utc = datetime.now(timezone.utc)
print(f"🕐 Current UTC: {now_utc.isoformat()}")
print(f"🔗 CLOB URL: {CLOB_URL}")
print()

# ── Step 1: Fetch trades from CLOB ──
if not CLOB_AVAILABLE or not PRIVATE_KEY:
    print("❌ Need py-clob-client + POLYGON_PRIVATE_KEY to fetch trades")
    sys.exit(1)

client = ClobClient(
    CLOB_URL,
    key=PRIVATE_KEY,
    chain_id=CHAIN_ID,
    signature_type=SIG_TYPE,
    funder=FUNDER or None
)
client.set_api_creds(client.create_or_derive_api_creds())

print("📊 Fetching trades from CLOB...")
trades = client.get_trades()
print(f"   Got {len(trades)} trades\n")

# ── Step 2: Aggregate net positions ──
agg = {}
for trade in trades:
    token_id = trade.get('asset_id', trade.get('tokenID', ''))
    if not token_id:
        continue
    side = trade.get('side', 'BUY').upper()
    size = float(trade.get('size', 0))
    price = float(trade.get('price', 0))
    
    if token_id not in agg:
        condition_id = trade.get('market', trade.get('conditionId', ''))
        agg[token_id] = {
            'size': 0, 'cost': 0,
            'condition_id': condition_id,
            'outcome': trade.get('outcome', trade.get('trader_side', '?')),
        }
    if side == 'BUY':
        agg[token_id]['cost'] += size * price
        agg[token_id]['size'] += size
    else:
        agg[token_id]['size'] -= size
        agg[token_id]['cost'] -= size * price

positions = {tid: info for tid, info in agg.items() if info['size'] > 0.001}
print(f"📦 Net positions with size > 0: {len(positions)}\n")

# ── Step 3: For each position, dump CLOB + Gamma market data ──
for i, (token_id, info) in enumerate(positions.items(), 1):
    cid = info['condition_id']
    print(f"{'='*70}")
    print(f"POSITION #{i}")
    print(f"  token_id:     {token_id[:20]}...")
    print(f"  condition_id: {cid[:20]}...")
    print(f"  net size:     {info['size']:.4f}")
    print(f"  outcome:      {info['outcome']}")
    
    # ── CLOB get_market ──
    print(f"\n  📡 CLOB get_market({cid[:16]}...):")
    try:
        mkt = client.get_market(cid)
        if isinstance(mkt, dict):
            # Print ALL keys so we can see what's available
            print(f"     Keys: {sorted(mkt.keys())}")
            for key in ['accepting_orders', 'active', 'closed', 'resolved',
                        'is_resolved', 'condition_id', 'question', 'description',
                        'end_date_iso', 'end_date', 'market_slug',
                        'tokens', 'minimum_order_size', 'minimum_tick_size']:
                if key in mkt:
                    val = mkt[key]
                    if key == 'tokens' and isinstance(val, list):
                        print(f"     {key}: [{len(val)} tokens]")
                        for t in val:
                            print(f"       - token_id={t.get('token_id','')[:16]}... outcome={t.get('outcome','')} winner={t.get('winner', '?')}")
                    elif isinstance(val, str) and len(val) > 80:
                        print(f"     {key}: {val[:80]}...")
                    else:
                        print(f"     {key}: {val}")
        else:
            print(f"     Response type: {type(mkt)} = {str(mkt)[:200]}")
    except Exception as e:
        print(f"     Error: {e}")
    
    # ── Gamma API ──
    print(f"\n  🌐 Gamma API /markets/{cid[:16]}...:")
    try:
        r = httpx.get(f"{GAMMA_URL}/markets/{cid}", timeout=15)
        if r.status_code == 200:
            gamma = r.json()
            print(f"     Keys: {sorted(gamma.keys())}")
            for key in ['question', 'closed', 'resolved', 'active',
                        'accepting_orders', 'accepting_order_timestamp',
                        'end_date_iso', 'endDate', 'end_date',
                        'game_start_date', 'start_date',
                        'condition_id', 'market_slug', 'description',
                        'tokens', 'volume', 'liquidity']:
                if key in gamma:
                    val = gamma[key]
                    if key == 'tokens' and isinstance(val, list):
                        print(f"     {key}: [{len(val)} tokens]")
                        for t in val:
                            print(f"       - token_id={t.get('token_id','')[:16]}... outcome={t.get('outcome','')} winner={t.get('winner', '?')}")
                    elif isinstance(val, str) and len(val) > 80:
                        print(f"     {key}: {val[:80]}...")
                    else:
                        print(f"     {key}: {val}")
        else:
            print(f"     HTTP {r.status_code}")
    except Exception as e:
        print(f"     Error: {e}")
    
    # ── CLOB price check ──
    print(f"\n  💰 CLOB price check:")
    try:
        from py_clob_client.clob_types import BookParams
        book = client.get_order_book(token_id)
        if isinstance(book, dict):
            bids = book.get('bids', [])
            asks = book.get('asks', [])
            best_bid = float(bids[0]['price']) if bids else 0
            best_ask = float(asks[0]['price']) if asks else 0
            print(f"     best_bid={best_bid:.4f}  best_ask={best_ask:.4f}")
        else:
            print(f"     Response: {str(book)[:200]}")
    except Exception as e:
        print(f"     Error: {e}")
    
    print()

print(f"\n{'='*70}")
print(f"DONE. {len(positions)} positions inspected.")
print(f"Use the output above to understand exactly what fields the API returns")
print(f"and which ones indicate a closed/resolved market.")
