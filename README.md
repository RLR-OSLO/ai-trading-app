# AI Trading App

Automated, long-only Binance Spot trading with deterministic risk controls.

> Current status: the service supports explicitly enabled live trading with a
> hard 100 USDC capital ceiling and server-side safety controls.

## Live defaults

- Maximum bot capital: 100 USDC
- Order size: 25 USDC
- Risk profile: Normal
- Trading universe: BTC, ETH, SOL, BNB, XRP
- Quote asset preference: USDC, with USDT fallback only when available
- Stop loss: 1%
- Take profit: 2%
- Daily realized loss pause: 2 USDC
- Maximum open positions: 1
- Maximum order actions per day: 6
- Spot only: no leverage, futures, margin, shorting, or withdrawals

## Market analysis

New positions require an aligned multi-factor score rather than a single price
signal. The engine evaluates 15-minute, 1-hour and 4-hour trends, EMA alignment,
RSI, MACD direction, volume confirmation and ATR volatility. Altcoin entries
also require a bullish Bitcoin regime. Fresh headlines from several crypto news
feeds can block entries during broadly negative events, but news can never
create a buy signal by itself. Missing news data is logged and treated as
neutral.

## Planned architecture

- `trader/`: Python trading and risk engine running continuously on a fixed-IP
  server.
- Binance Spot REST APIs for market data, orders, and reconciliation.
- Next.js dashboard for configuration and reporting.
- Supabase Auth and Postgres for users, TOTP MFA, audit logs, and row-isolated
  account data.
- Each user has their own Binance connection and TOTP factor. Binance secrets
  are never sent to the browser and withdrawal permission is forbidden.

## Safety boundary

The trading engine can execute only inside the configured allowlist and limits.
AI-generated analysis cannot override withdrawal restrictions, risk limits,
the asset allowlist, or the emergency stop.

## Server installation

On a fresh Ubuntu Droplet, run as root:

```bash
curl -fsSL https://raw.githubusercontent.com/RLR-OSLO/ai-trading-app/main/deploy/install.sh | bash
```

Successful installation prints `AI_TRADING_MONITOR_READY`. The installer never
adds API credentials and leaves `LIVE_TRADING_ENABLED=false`.
