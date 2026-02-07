"""Test Polymarket API for sports and events."""
import httpx
import json

# Fetch sports series
print("=" * 60)
print("POLYMARKET SPORTS API TEST")
print("=" * 60)

# 1. Fetch /sports endpoint
print("\n1. Fetching /sports endpoint...")
try:
    r = httpx.get('https://gamma-api.polymarket.com/sports', timeout=30)
    sports = r.json()
    print(f"   Found {len(sports)} sports series")
    for s in sports[:10]:
        print(f"   - {s.get('name')}: slug={s.get('slug')}, id={s.get('id')}")
except Exception as e:
    print(f"   Error: {e}")
    sports = []

# 2. Fetch events for cricket (or first sport with "cricket" in name)
print("\n2. Looking for Cricket events...")
cricket_series = None
for s in sports:
    name = s.get('name', '').lower()
    if 'cricket' in name or 'ipl' in name or 't20' in name:
        cricket_series = s
        break

if cricket_series:
    print(f"   Found cricket series: {cricket_series.get('name')}, id={cricket_series.get('id')}")
    
    # Fetch events for this series
    series_id = cricket_series.get('id')
    r = httpx.get(
        'https://gamma-api.polymarket.com/events',
        params={'series_id': series_id, 'active': True, 'closed': False},
        timeout=30
    )
    events = r.json()
    print(f"   Found {len(events)} events")
    
    for event in events[:3]:
        print(f"\n   EVENT: {event.get('title', event.get('question', 'Unknown'))}")
        print(f"   ID: {event.get('id')}")
        
        # Check for markets within event
        markets = event.get('markets', [])
        print(f"   SUB-MARKETS ({len(markets)}):")
        for m in markets[:5]:
            print(f"      - {m.get('question', m.get('groupItemTitle', 'Unknown'))}")
else:
    print("   No cricket series found in /sports")

# 3. Try fetching by tag
print("\n3. Trying tag-based fetch...")
try:
    r = httpx.get(
        'https://gamma-api.polymarket.com/events',
        params={'tag': 'sports', 'active': True, 'closed': False, 'limit': 10},
        timeout=30
    )
    events = r.json()
    print(f"   Found {len(events)} events with tag='sports'")
    for event in events[:5]:
        title = event.get('title', event.get('question', 'Unknown'))
        markets = event.get('markets', [])
        print(f"   - {title[:60]} ({len(markets)} sub-markets)")
except Exception as e:
    print(f"   Error: {e}")

# 4. Fetch markets directly with sport keywords
print("\n4. Fetching markets with cricket keyword...")
try:
    r = httpx.get(
        'https://gamma-api.polymarket.com/markets',
        params={'_q': 'cricket', 'active': True, 'closed': False, 'limit': 10},
        timeout=30
    )
    markets = r.json()
    print(f"   Found {len(markets)} markets")
    for m in markets[:5]:
        q = m.get('question', 'Unknown')
        print(f"   - {q[:70]}")
except Exception as e:
    print(f"   Error: {e}")

# 5. Check groupItemTitle structure
print("\n5. Checking event structure for sub-markets...")
try:
    r = httpx.get(
        'https://gamma-api.polymarket.com/events',
        params={'active': True, 'closed': False, 'limit': 50},
        timeout=30
    )
    events = r.json()
    
    # Find events with multiple markets (sub-markets)
    multi_market_events = [e for e in events if len(e.get('markets', [])) > 1]
    print(f"   Found {len(multi_market_events)} events with multiple sub-markets")
    
    for event in multi_market_events[:3]:
        title = event.get('title', 'Unknown')
        markets = event.get('markets', [])
        print(f"\n   EVENT: {title[:60]}")
        print(f"   Markets:")
        for m in markets[:6]:
            q = m.get('question', m.get('groupItemTitle', 'Unknown'))
            print(f"      - {q[:50]}")
except Exception as e:
    print(f"   Error: {e}")

print("\n" + "=" * 60)
print("TEST COMPLETE")
print("=" * 60)
