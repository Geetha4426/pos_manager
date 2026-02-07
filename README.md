# Polymarket Telegram Sniper Bot

A lightning-fast Telegram trading bot for Polymarket with instant buy/sell, position management, and favorites.

## Features

- ⚡ **Instant Trading** - Market orders for lightning-fast execution
- 📊 **Position Manager** - View positions, P&L, partial sells
- 🔍 **Smart Search** - Category browsing & quick search
- ⭐ **Favorites** - Save markets for quick access
- 💰 **Wallet View** - Balance and holdings display

## Setup

1. **Clone and install**:
```bash
pip install -r requirements.txt
```

2. **Configure `.env`**:
```bash
cp .env.example .env
# Edit .env with your keys
```

3. **Run**:
```bash
python -m bot.main
```

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome & setup |
| `/balance` | Wallet balance |
| `/positions` | Active positions |
| `/buy` | Buy flow wizard |
| `/search <query>` | Search markets |
| `/favorites` | Saved markets |
| `/help` | All commands |

## Deployment (Railway)

```bash
railway up
```

## Environment Variables

See `.env.example` for all required variables.
