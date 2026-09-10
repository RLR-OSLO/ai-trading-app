import os

from trader.binance import BinanceCredentials
from trader.derivatives import capability_snapshot


credentials = BinanceCredentials(
    os.environ.get("BINANCE_API_KEY", ""),
    os.environ.get("BINANCE_SECRET_KEY", ""),
)
credentials.validate()
status = capability_snapshot(credentials)
print(
    "DERIVATIVES_CAPABILITY "
    f"margin_ready={status.margin_ready} "
    f"futures_ready={status.futures_ready} "
    f"withdrawals_enabled={status.withdrawals_enabled} "
    f"ip_restricted={status.ip_restricted}"
)
