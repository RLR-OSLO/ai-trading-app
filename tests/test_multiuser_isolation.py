from pathlib import Path

import trader.manager as manager


def test_nonlegacy_user_gets_separate_spot_and_derivatives_state(monkeypatch, tmp_path):
    account = manager.Account('user-a', 'k', 's', legacy=False)
    original = manager.Path

    class FakePath(type(Path())):
        def __new__(cls, *args, **kwargs):
            value = original(*args, **kwargs)
            if str(value).startswith('/var/lib/ai-trading-app/users'):
                value = original(str(value).replace('/var/lib/ai-trading-app/users', str(tmp_path)))
            return value

    monkeypatch.setattr(manager, 'Path', FakePath)
    env = manager._child_env(account)
    assert env['LIVE_STATE_PATH'] != env['DERIVATIVES_STATE_PATH']
    assert 'user-a' in env['LIVE_STATE_PATH']
    assert 'user-a' in env['DERIVATIVES_STATE_PATH']
