# Poly_Trade Development Session Log

## Project Overview
- **Project**: Polymarket Telegram Trading Bot (`poly_trade`)
- **Path**: `c:\Users\acer\projects\poly_trade\`
- **GitHub**: `Geetha4426/pos_manager`
- **Deployed on**: Railway (auto-deploys from GitHub push)
- **Relay**: Cloudflare Worker at `https://poly-relay.justhappy4426.workers.dev` (geo-block bypass)

## Wallet Configuration (WORKING as of Feb 26, 2026)
- **EOA Signer**: `0x871faC3EEE45e620606c1d8e228984d2d322244F`
- **Proxy Wallet (Funder)**: `0x4f9fBe936a35D556894737235dF49cFcD5d5CFC4`
- **SIGNATURE_TYPE**: `2` (GnosisSafe) — **THIS IS CRITICAL, do NOT change**
- **Proxy wallet balance**: ~$3.39 USDC.e
- **Railway env vars**: SIGNATURE_TYPE=2, FUNDER_ADDRESS=proxy wallet

## Architecture
- **Global ClobClient**: Uses env vars (SIGNATURE_TYPE, FUNDER_ADDRESS) for browsing only
- **Per-user ClobClient**: Created during `/unlock` from encrypted DB, used for ALL trades
- `/connect` → encrypts private key with AES-256-GCM → stored in SQLite
- `/unlock` → decrypts key → creates ClobClient with sig_type + funder from DB
- `require_auth()` → `get_user_client()` → clones shared client with user's ClobClient

## Key Files
- `config.py` — All env var config, SIGNATURE_TYPE default=2
- `core/polymarket_client.py` (~2975 lines) — Main client, buy/sell/positions/balance
- `core/user_manager.py` (~409 lines) — Multi-user encrypted key storage, sessions
- `bot/handlers/auth.py` — /connect, /unlock, /disconnect, /lock flows
- `bot/handlers/wallet.py` — /balance, /debug_wallet, /test_sign diagnostics
- `bot/handlers/trading.py` — /buy, /sell handlers
- `bot/handlers/positions.py` — /positions handler
- `bot/handlers/search.py` — /search for markets
- `relay/cloudflare_worker.js` — Geo-block bypass relay

## Bug Fix History (Chronological)

### Phase 1: UI/Parsing Fixes
- Token parsing for cricket markets (clobTokenIds JSON string)
- Search keyword validation (min length, special chars)
- Team names in keyboards (outcome_yes/outcome_no instead of Yes/No)
- 409 Conflict fix (delete webhook before polling)
- BookParams fix (pass token_id correctly)
- OrderSummary not subscriptable (handle object attrs)

### Phase 2: Signature Debugging (THE BIG ONE)
**Problem**: Buy orders failed with `400 "invalid signature"` from Polymarket CLOB API.

**Timeline**:
1. Discovered dual ClobClient architecture (global vs per-user)
2. Found `sig_type` lives at `clob_client.builder.sig_type` (not direct attr)
3. Added `/debug_wallet` and `/test_sign` diagnostic commands
4. Auto-detect sig_type in `/connect` flow
5. Fixed sig_type env var leaking into buy flow (3 places)
6. Fixed HTML crash in test_sign (EIP712 objects have `<>` in repr)
7. Enhanced test_sign with raw httpx POST + full request/response dump
8. **Confirmed**: sig_type=1 → "invalid signature", sig_type=0 → "not enough balance"

**Research**: Studied `foruse959/5min_trade` reference repo:
- They default to sig_type=0 (EOA)
- Same order submission: `create_order()` → `post_order()`
- They call `update_balance_allowance` before trades
- They call conditional token allowance before sells

**Root Cause Found**: 
- sig_type=1 (PolyProxy) requires on-chain `isApprovedForAll` operator approval
- User's EOA is NOT approved as operator for proxy wallet (confirmed on-chain)
- sig_type=2 (GnosisSafe) uses different verification → WORKS without approval
- The WORKING commit `b71ecd4` had SIGNATURE_TYPE=2 in Railway

**Fix**: Changed `/connect` to use sig_type=2 (was 1) when funder provided.

### Phase 3: Allowance Improvements
- Added `update_balance_allowance` before buy orders (syncs on-chain USDC)
- Added conditional token allowance before sell orders (proxy wallet fix)
- Added on-chain diagnostics to /test_sign:
  - USDC.e balance check (EOA + funder)
  - Operator approval check (isApprovedForAll on CTF + NegRisk exchanges)
  - CLOB balance/allowance query

## Git Commits (Latest First)
```
7b1ce7c Fix sig_type: use 2 (GnosisSafe) for proxy wallets, not 1
1838182 Add on-chain diagnostics + allowance sync from 5min_trade research
20db913 Enhanced /test_sign: raw httpx POST with full request/response dump
e69a2dd Fix test_sign HTML crash: escape EIP712 struct fields
eb5a4cb Fix sig_type leaks: show per-user config, remove pre-buy creds refresh
66dac8f Fix sig_type discovery (builder.sig_type), add /test_sign
a2956d0 Fix signature diagnostics, auto-detect sig_type
08b6672 Fix OrderSummary not subscriptable
21a1e4c Fix BookParams bug, add /debug_wallet command
9dd93ad Fix syntax error: split merged line in main.py
6677bc9 Fix 409 Conflict: delete webhook before polling
1212f40 Fix team-name outcomes, search validation, UI improvements
802afce Major improvements: Data API positions, FAK orders, outcomePrices
0180c73 Multi-user auth + fix position filter
b71ecd4 Add CLOB relay for geo-block bypass + fix MarketOrderArgs (WORKING STATE)
```

## Current Status (Feb 27, 2026)
- ✅ All buy/sell orders working (sig_type=2, confirmed via /test_sign POST 200)
- ✅ On-chain diagnostics in /test_sign
- ✅ Allowance sync before buy/sell
- ✅ Multi-user encrypted wallet management
- ✅ CLOB relay for geo-block bypass
- ✅ Deployed on Railway
- ✅ Permanent sessions (no 30min timeout)
- ✅ Auto-unlock bot owner from env vars (no /connect or /unlock needed)
- ✅ Sell buttons: 25%, 50%, 75%, 100%, Custom
- ✅ Stop Loss / Take Profit buttons on position detail
- ✅ Auto-sell execution when SL/TP triggers via WS price monitor
- ✅ Fixed dual post_init bug (init code was being overwritten)

## Known Limitations
- Railway redeploy clears SQLite DB (encrypted keys) for non-owner users
  - Workaround: Owner auto-unlocks from env vars (POLYGON_PRIVATE_KEY + TELEGRAM_CHAT_ID)
  - Other users need to /connect again after redeploy
  - For persistence: use Railway Volume mount for data/ directory
- Operator approval (isApprovedForAll) NOT set → sig_type=1 won't work
- USDC only on proxy wallet ($3.39), EOA has $0
- SL/TP auto-execution requires WS price feed to be connected and session unlocked

## Polymarket Technical Notes
- py-clob-client v0.34.6
- Chain: Polygon (137)
- USDC.e: `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174` (6 decimals)
- CTF Exchange: `0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E`
- NegRisk Exchange: `0xC5d563A36AE78145C45a50134d48A1215220f80a`
- Signature types: 0=EOA, 1=PolyProxy (needs operator approval), 2=GnosisSafe (works with browser proxy wallets)
- Order types: FOK (all-or-nothing), FAK (partial fills), GTC (limit order)
- GTC minimum: 5 shares. FOK/FAK minimum: 1 share / $1
- Taker fee: ~1.56% dynamic (peaks at 50% probability)
