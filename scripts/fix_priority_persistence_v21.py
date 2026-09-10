from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    p = Path(path)
    s = p.read_text(encoding="utf-8")
    if new in s:
        print(f"already: {label}")
        return
    if old not in s:
        raise SystemExit(f"missing marker: {label}")
    p.write_text(s.replace(old, new, 1), encoding="utf-8")
    print(f"patched: {label}")

# A priority directive must stay pending until it is actually executed,
# explicitly rejected by signal/settings validation, or cancelled by the user.
# Do not silently expire it after two minutes.
replace_once(
    "trader/reporting.py",
    '''    def get_pending_directive(self) -> dict[str, Any] | None:\n        self.expire_stale_directives()\n        query = urllib.parse.urlencode({\n            "user_id": f"eq.{self.user_id}",\n            "status": "eq.pending",\n            "expires_at": "gt.now()",\n            "select": "id,symbol,direction,mode,requested_notional,leverage,created_at,expires_at",\n            "order": "created_at.desc",\n            "limit": "1",\n        })\n''',
    '''    def get_pending_directive(self) -> dict[str, Any] | None:\n        query = urllib.parse.urlencode({\n            "user_id": f"eq.{self.user_id}",\n            "status": "eq.pending",\n            "select": "id,symbol,direction,mode,requested_notional,leverage,created_at,expires_at",\n            "order": "created_at.desc",\n            "limit": "1",\n        })\n''',
    "persistent priority directives",
)

# Clarify the dashboard note so the UI matches the new behavior.
replace_once(
    "app/trading-dashboard.tsx",
    '«Prioriter og gjennomfør» sender et kortvarig direktiv til boten',
    '«Prioriter og gjennomfør» sender et prioritert direktiv til boten som blir stående til det gjennomføres eller stoppes',
    "priority help text",
)

print("FIX_V21_OK")
