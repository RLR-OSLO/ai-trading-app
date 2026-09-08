# AI Trading App

Automated, long-only Binance Spot trading with deterministic risk controls.

> Current status: the service supports explicitly enabled live trading with a
> hard 100 USDC capital ceiling and server-side safety controls.

## Live defaults

- Maximum bot capital: 100 USDC
- Order size: 25 USDC
- Risk profile: Normal
- Trading universe: BTC, ETH, SOL, BNB, XRP
- Quote asset: USDC or USDT, selected from the dashboard
- Stop loss: 1%
- Take profit: 2%
- Daily realized loss pause: 2 USDC
- Maximum open positions: 1
- Risk-profile cadence: Low 6 actions/day + 30 min cooldown, Normal 8 + 15 min, High 12 + 5 min
- Worker interval: 30 seconds
- Spot only: no leverage, futures, margin, shorting, or withdrawals

## Market analysis

New positions require an aligned multi-factor score rather than a single price
signal. The engine evaluates 15-minute, 1-hour and 4-hour trends, EMA alignment,
RSI, MACD direction, volume confirmation and ATR volatility. Bitcoin regime is
still calculated and logged as market context, but it no longer blocks altcoin
trades. Risk profile now directly controls the entry threshold: Low requires
7/9, Normal 6/9 and High 5/9. A hard technical risk veto and strongly negative
fresh news can still block new entries. News can never create a buy signal by
itself.

## Runtime safety

Pausing the dashboard stops new entries only. Any already-open position remains
under stop-loss/take-profit monitoring so the bot can still exit it. Daily-loss
and trade-count limits likewise block new entries, not emergency management of
an existing position.

## Architecture

- `trader/`: Python trading and risk engine running continuously on a fixed-IP
  server.
- Binance Spot REST APIs for market data and orders.
- Next.js dashboard for configuration and reporting.
- Supabase Auth and Postgres for users, TOTP MFA, settings, trades, events and
  row-isolated account data.
- Each user has their own Binance connection and TOTP factor. Binance secrets
  are never sent to the browser and withdrawal permission is forbidden.

## Safety boundary

The trading engine can execute only inside the configured allowlist and limits.
AI-generated analysis cannot override withdrawal restrictions, risk limits,
the asset allowlist, or the emergency stop.

## Server installation/update

On the Ubuntu trading server, run as root:

```bash
curl -fsSL https://raw.githubusercontent.com/RLR-OSLO/ai-trading-app/main/deploy/install.sh | bash
```

Successful installation prints `AI_TRADING_MONITOR_READY`. Existing server-only
API credentials are preserved because the installer does not overwrite an
existing `/etc/ai-trading-app.env` file.
