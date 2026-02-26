"""Quick Gamma API field research — no auth needed."""
import httpx
import json

GAMMA = 'https://gamma-api.polymarket.com'

print("=" * 60)
print("CLOSED MARKETS — what fields does Gamma set?")
print("=" * 60)
r = httpx.get(f'{GAMMA}/markets', params={'closed': True, 'limit': 3}, timeout=30)
for m in r.json()[:3]:
    q = m.get('question', '')[:60]
    print(f"\nQ: {q}")
    print(f"  ALL KEYS: {sorted(m.keys())}")
    status_keys = [
        'closed', 'resolved', 'active', 'accepting_orders',
        'accepting_order_timestamp', 'end_date_iso', 'endDate', 'end_date',
        'game_start_date', 'start_date', 'ready', 'funded',
        'enable_order_book', 'market_type'
    ]
    for k in status_keys:
        if k in m:
            print(f"  {k} = {m[k]}")
    
    tokens = m.get('tokens', [])
    if tokens:
        print(f"  tokens: {len(tokens)} items")
        for t in tokens[:2]:
            print(f"    token keys: {sorted(t.keys())}")
            print(f"    outcome={t.get('outcome')} winner={t.get('winner')}")

print("\n" + "=" * 60)
print("ACTIVE MARKETS — comparison")
print("=" * 60)
r2 = httpx.get(f'{GAMMA}/markets', params={'active': True, 'closed': False, 'limit': 3}, timeout=30)
for m in r2.json()[:3]:
    q = m.get('question', '')[:60]
    print(f"\nQ: {q}")
    status_keys = [
        'closed', 'resolved', 'active', 'accepting_orders',
        'accepting_order_timestamp', 'end_date_iso', 'endDate', 'end_date',
        'game_start_date', 'start_date', 'ready', 'funded',
        'enable_order_book'
    ]
    for k in status_keys:
        if k in m:
            print(f"  {k} = {m[k]}")

print("\n" + "=" * 60)
print("CLOB PUBLIC: market status for a closed condition_id")
print("=" * 60)
# Grab condition_id from one of the closed markets
closed_markets = r.json()
if closed_markets:
    cid = closed_markets[0].get('condition_id', '')
    print(f"Testing condition_id: {cid[:20]}...")
    try:
        r3 = httpx.get(f'https://clob.polymarket.com/markets/{cid}', timeout=15)
        print(f"  HTTP status: {r3.status_code}")
        if r3.status_code == 200:
            data = r3.json()
            print(f"  CLOB keys: {sorted(data.keys())}")
            for k in ['accepting_orders', 'active', 'closed', 'condition_id',
                       'end_date_iso', 'end_date', 'resolved', 'question',
                       'tokens', 'enable_order_book', 'market_slug']:
                if k in data:
                    v = data[k]
                    if k == 'tokens' and isinstance(v, list):
                        print(f"  {k}: {len(v)} tokens")
                        for t in v[:2]:
                            print(f"    keys: {sorted(t.keys())}")
                            print(f"    outcome={t.get('outcome')} winner={t.get('winner')}")
                    else:
                        print(f"  {k} = {v}")
    except Exception as e:
        print(f"  Error: {e}")
