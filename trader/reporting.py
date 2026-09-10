from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SupabaseReporter:
    url: str
    service_role_key: str
    user_id: str

    @classmethod
    def from_env(cls) -> "SupabaseReporter | None":
        url = os.getenv("SUPABASE_URL", "").rstrip("/")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        user_id = os.getenv("APP_USER_ID", "")
        if not (url and key and user_id):
            return None
        return cls(url, key, user_id)

    def _insert(self, table: str, payload: dict[str, Any]) -> None:
        body = json.dumps({**payload, "user_id": self.user_id}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.url}/rest/v1/{table}", data=body, method="POST",
            headers={"apikey": self.service_role_key, "Authorization": f"Bearer {self.service_role_key}", "Content-Type": "application/json", "Prefer": "return=minimal"},
        )
        try:
            with urllib.request.urlopen(request, timeout=10):
                return
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Supabase reporting failed ({exc.code}): {detail}") from exc

    def get_settings(self) -> dict[str, Any] | None:
        query = urllib.parse.urlencode({
            "user_id": f"eq.{self.user_id}",
            "select": "bot_enabled,live_trading_enabled,risk_profile,quote_asset,trade_cap_usdc,order_size_usdc,stop_loss_percent,take_profit_percent,max_daily_loss_usdc,short_enabled,futures_enabled,leverage,daily_loss_reset_at",
            "limit": "1",
        })
        request = urllib.request.Request(
            f"{self.url}/rest/v1/bot_settings?{query}",
            headers={"apikey": self.service_role_key, "Authorization": f"Bearer {self.service_role_key}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                rows = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Supabase settings read failed ({exc.code}): {detail}") from exc
        return rows[0] if rows else None

    def get_recent_trades(self, limit: int = 1000) -> list[dict[str, Any]]:
        query = urllib.parse.urlencode({
            "user_id": f"eq.{self.user_id}",
            "mode": "eq.live",
            "select": "symbol,side,quantity,entry_price,created_at",
            "order": "created_at.asc",
            "limit": str(limit),
        })
        request = urllib.request.Request(
            f"{self.url}/rest/v1/trades?{query}",
            headers={"apikey": self.service_role_key, "Authorization": f"Bearer {self.service_role_key}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Supabase trades read failed ({exc.code}): {detail}") from exc

    def record_trade(self, payload: dict[str, Any]) -> None:
        clean = dict(payload)
        mode = str(clean.pop("mode", "live"))
        if mode not in {"paper", "live", "margin", "futures"}:
            raise ValueError(f"Unsupported trade mode: {mode}")
        self._insert("trades", {**clean, "mode": mode})

    def record_event(self, event_type: str, message: str, level: str = "info") -> None:
        self._insert("bot_events", {"level": level, "event_type": event_type, "message": message})
