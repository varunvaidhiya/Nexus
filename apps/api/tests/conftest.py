import os
import secrets

# Throwaway credentials so crypto and auth work in tests. Set before
# nexus_api modules read settings.
os.environ.setdefault("NEXUS_MASTER_KEY", secrets.token_hex(32))
os.environ.setdefault("NEXUS_AUTH_TOKEN", secrets.token_urlsafe(32))
