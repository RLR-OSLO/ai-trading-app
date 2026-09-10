from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"marker missing in {path}: {old[:140]!r}")
    p.write_text(text.replace(old, new, 1))
    print(f"patched {path}")

# Extreme should be active without weakening hard risk controls.
replace_once(
    "trader/portfolio_live.py",
    '    "extreme": (48, 60, 5),',
    '    "extreme": (100, 30, 5),'
)

# Expire stale directives server-side so UI never shows an already-dead priority forever.
replace_once(
    "trader/reporting.py",
    '    def get_pending_directive(self) -> dict[str, Any] | None:\n        query = urllib.parse.urlencode({',
    '''    def expire_stale_directives(self) -> None:\n        query = urllib.parse.urlencode({\n            "user_id": f"eq.{self.user_id}",\n            "status": "eq.pending",\n            "expires_at": "lte.now()",\n        })\n        body = json.dumps({"status": "expired", "result": "Directive expired before execution"}).encode("utf-8")\n        request = urllib.request.Request(\n            f"{self.url}/rest/v1/trade_directives?{query}", data=body, method="PATCH",\n            headers={"apikey": self.service_role_key, "Authorization": f"Bearer {self.service_role_key}", "Content-Type": "application/json", "Prefer": "return=minimal"},\n        )\n        try:\n            with urllib.request.urlopen(request, timeout=10):\n                return\n        except urllib.error.HTTPError as exc:\n            detail = exc.read().decode("utf-8", errors="replace")\n            raise RuntimeError(f"Supabase stale directive expiry failed ({exc.code}): {detail}") from exc\n\n    def get_pending_directive(self) -> dict[str, Any] | None:\n        self.expire_stale_directives()\n        query = urllib.parse.urlencode({'''
)

# Persist trading-cycle failures in Supabase as well as journalctl, so failures are visible remotely.
replace_once(
    "trader/worker.py",
    '        except Exception:\n            LOG.exception("trading cycle failed; no new order will be submitted")',
    '''        except Exception as exc:\n            LOG.exception("trading cycle failed; no new order will be submitted")\n            if reporter:\n                try:\n                    reporter.record_event("trading_cycle_error", f"{type(exc).__name__}: {exc}", "error")\n                except Exception:\n                    LOG.exception("could not report trading cycle error")'''
)

# UI only considers a priority active while it is pending AND unexpired.
# Match either common select shape from v11.
p = Path("app/trading-dashboard.tsx")
text = p.read_text()
old = '.eq("status", "pending").order("created_at", { ascending: false }).limit(1)'
new = '.eq("status", "pending").gt("expires_at", new Date().toISOString()).order("created_at", { ascending: false }).limit(1)'
if old in text:
    p.write_text(text.replace(old, new, 1))
    print("patched app/trading-dashboard.tsx")
elif '.gt("expires_at", new Date().toISOString())' in text:
    print("app/trading-dashboard.tsx already filters expired priorities")
else:
    print("warning: active-priority query marker not found; backend expiry still guarantees cleanup")

print("UPGRADE_EXECUTION_QC_V12_OK")
