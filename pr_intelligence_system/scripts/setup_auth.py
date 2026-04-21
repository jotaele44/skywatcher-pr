"""
setup_auth.py — One-time OIDC authentication for the Copernicus openEO endpoint.

Run this once before using --fetch-satellite. It opens a browser window for
login and caches the token at ~/.config/openeo/ for all future sessions.

Usage:
    python scripts/setup_auth.py
"""

import os
import sys

ENDPOINT = "https://openeo.dataspace.copernicus.eu"
REGISTER_URL = "https://dataspace.copernicus.eu"
TOKEN_CACHE = os.path.expanduser("~/.config/openeo")


def main() -> None:
    print("openEO / Copernicus Authentication Setup")
    print("=" * 42)

    # 1. Check openeo is installed
    try:
        import openeo
    except ImportError:
        print("\nERROR: openeo package not found.")
        print("Install it with:  pip install openeo")
        sys.exit(1)

    print(f"openeo version: {openeo.__version__}")

    # 2. Remind user to have a Copernicus account
    print(f"\nYou need a free Copernicus Data Space account.")
    print(f"Register at: {REGISTER_URL}")
    input("\nPress Enter when your account is ready, or Ctrl+C to cancel...")

    # 3. Connect and authenticate (triggers browser popup)
    print(f"\nConnecting to {ENDPOINT} ...")
    try:
        connection = openeo.connect(ENDPOINT)
    except Exception as exc:
        print(f"ERROR: Could not connect: {exc}")
        sys.exit(1)

    print("A browser window will open for login. Complete the login there.")
    try:
        connection.authenticate_oidc()
    except Exception as exc:
        print(f"ERROR: Authentication failed: {exc}")
        sys.exit(1)

    # 4. Confirm token cached
    print(f"\nAuthentication successful.")
    print(f"Token cached at: {TOKEN_CACHE}")

    # 5. Verify connection with a lightweight API call
    print("\nVerifying connection...")
    try:
        ids = connection.list_collection_ids()
        target = {"SENTINEL2_L2A", "COPERNICUS_30"}
        found = target & set(ids)
        missing = target - set(ids)
        print(f"  Collections available: {len(ids)} total")
        print(f"  Required collections found: {sorted(found)}")
        if missing:
            print(f"  WARNING — not found: {sorted(missing)}")
    except Exception as exc:
        print(f"  WARNING: Could not list collections: {exc}")

    print("\nSetup complete. You can now use --fetch-satellite in main_query.py.")


if __name__ == "__main__":
    main()
