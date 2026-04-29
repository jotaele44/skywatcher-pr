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

    print("\nopenEO setup complete. You can now use --fetch-satellite in main_query.py.")

    # -----------------------------------------------------------------------
    # Section 2: ODP / Sentinel-1 SAR credentials
    # -----------------------------------------------------------------------
    print("\n" + "=" * 42)
    print("ODP / Sentinel-1 SAR Setup (for --fetch-sar)")
    print("=" * 42)
    print(
        "\nSentinel-1 CARD-BS backscatter data is fetched via the Copernicus ODP REST API\n"
        "using the same Copernicus account credentials (username + password).\n"
        "Unlike openEO, ODP uses a password token — no browser popup needed.\n"
    )
    print("Set these environment variables before running --fetch-sar:")
    print("  export CDSE_USER='your-copernicus-email'")
    print("  export CDSE_PASSWORD='your-copernicus-password'")

    # Verify token acquisition if credentials are available
    import os
    cdse_user = os.environ.get("CDSE_USER", "")
    cdse_pass = os.environ.get("CDSE_PASSWORD", "")
    if cdse_user and cdse_pass:
        print("\nCDSE_USER / CDSE_PASSWORD found — verifying ODP token...")
        try:
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from core.ingest.loaders.odp_loader import get_token
            token = get_token(cdse_user, cdse_pass)
            print("  ODP token acquired successfully.")
        except Exception as exc:
            print(f"  WARNING: ODP token acquisition failed: {exc}")
    else:
        print("\n  (CDSE_USER / CDSE_PASSWORD not set — skipping ODP token test)")

    # -----------------------------------------------------------------------
    # Section 3: Felt API key
    # -----------------------------------------------------------------------
    print("\n" + "=" * 42)
    print("Felt Map Publishing Setup (for --publish-felt)")
    print("=" * 42)
    print(
        "\nTo publish ILAP results to an interactive Felt web map, set:\n"
        "  export FELT_API_KEY='felt_pat_...'\n"
        "\nGenerate a key at: https://felt.com/account/api-keys"
    )
    felt_key = os.environ.get("FELT_API_KEY", "")
    if felt_key:
        print(f"\n  FELT_API_KEY found ({felt_key[:12]}...).")
    else:
        print("\n  (FELT_API_KEY not set)")

    print("\nAll setup complete.")


if __name__ == "__main__":
    main()
