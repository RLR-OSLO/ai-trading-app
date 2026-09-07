# AI Trading App

Automated, long-only Binance Spot trading with deterministic risk controls.

> Current status: the deployable service is a market/API monitor with live
> trading hard-disabled. Strategy execution and order activation require
> separate testing and explicit approval.

## Version 1 defaults

- Starting capital: NOK 6,000 equivalent
- Risk profile: Normal
- Trading universe: BTC, ETH, SOL, BNB, XRP
- Quote asset preference: USDC, with USDT fallback only when available
- Risk per trade: 0.50% of equity
- Daily loss limit: 2.00% of equity
- Hard drawdown pause: 8.00% from the equity high-water mark
- Maximum open positions: 3
- Starting reserve: 20% of equity
- Weekly profit lock: 25% of positive realized profit
- Spot only: no leverage, futures, margin, shorting, or withdrawals

## Bull-market behavior

The bot never closes an entire winning position merely because it reaches one
fixed profit target. It scales out part of the position, then lets the remaining
"runner" follow the trend with a volatility-adjusted trailing stop.

- Normal bull regime: realize 25% at 2R and 25% at 3R; trail the remaining 50%.
- Strong bull regime: realize 20% at 2R and 15% at 4R; trail the remaining 65%
  with more room.
- Exit the runner when the higher-timeframe trend fails or the trailing stop is
  hit.
- Locked profit remains in the stablecoin reserve and is excluded from new
  position sizing.

## Planned architecture

- `trader/`: Python trading and risk engine running continuously on a fixed-IP
  server.
- Binance Spot REST/WebSocket APIs for market data, orders, and reconciliation.
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
