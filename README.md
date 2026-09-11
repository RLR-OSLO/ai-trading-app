# AI Trading App

Automated Binance Spot and controlled short trading with deterministic risk controls.

> Current status: the service supports explicitly enabled live trading with a
> hard 100 USDC capital ceiling and server-side safety controls.

## Live defaults

- Maximum bot capital: 100 USDC
- Order size: 25 USDC
- Risk profile: Normal
- Trading universe: the five most liquid approved markets from BTC, ETH, SOL, BNB, XRP and selected large-cap pairs
- Quote asset: USDC or USDT, selected from the dashboard
- Spot defaults: 1% hard stop with trailing profit protection
- Short defaults: at least 1.5% hard stop, at least 3% target, profit trail after a 1% favorable move
- Daily realized loss pause: 2 USDC by default
- One short position at a time; automated futures leverage is capped at 2x
- Worker interval: 15–30 seconds depending on risk profile
- Spot and short positions are protected by exchange-side orders plus local monitoring
- Withdrawals remain disabled

## Market analysis

New positions require an aligned multi-factor score rather than a single price
signal. The engine evaluates 15-minute, 1-hour and 4-hour trends, EMA alignment,
RSI, MACD direction, volume confirmation and ATR volatility. Bitcoin regime is calculated and logged as market context. Long entries remain
scored per market, while short entries require a non-bullish BTC regime and a
stronger bearish confirmation. Risk profile now directly controls the entry threshold: Low requires
7/9, Normal 6/9 and High 5/9. A hard technical risk veto and strongly negative
fresh news can still block new entries. News can never create a buy signal by
itself.

## Runtime safety

Pausing the dashboard stops new entries only. Any already-open position remains
protected and monitored. After a market buy, the engine attempts to place a
Binance Spot OCO sell pair with a LIMIT_MAKER take-profit leg and STOP_LOSS leg,
so protection can remain at the exchange even if the Linux worker is offline.
The worker tracks the order list and records the realized exit when one leg
fills. If OCO placement is temporarily unavailable, server-side stop/target
monitoring remains as a fallback. Daily-loss and trade-count limits block new
entries, not emergency management of an existing position.

Interrupted BUY/SELL requests use deterministic Binance client order IDs. After
a restart the worker queries Binance and reconciles an order that may have been
submitted before the process stopped, instead of blindly sending a duplicate.

## Architecture

- `trader/`: Python trading and risk engine running continuously on a fixed-IP
  server.
- Binance Spot REST APIs for market data, orders and OCO protection.
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
