import os

# Keep the test suite deterministic regardless of production environment variables
# loaded in the shell/systemd environment on the server.
os.environ.pop("EXCHANGE_PROTECTION_ENABLED", None)
