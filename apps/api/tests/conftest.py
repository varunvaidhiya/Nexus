import os
import secrets

# A throwaway master key so crypto works in tests. Set before nexus_api
# modules read settings.
os.environ.setdefault("NEXUS_MASTER_KEY", secrets.token_hex(32))
