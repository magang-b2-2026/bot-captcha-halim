"""
deploy/verify_egress.py
Validates that egress from the current machine routes through the specified proxy
and outputs the detected public IP and ISP.
"""
from __future__ import annotations

import sys
import httpx


def test_egress(proxy_url: str | None = None) -> None:
    print(f"Testing egress via proxy: {proxy_url or 'DIRECT (NO PROXY)'}")
    proxies = {"all://": proxy_url} if proxy_url else None

    try:
        with httpx.Client(proxy=proxy_url, timeout=15.0) as client:
            resp = client.get("https://ipinfo.io/json")
            if resp.status_code == 200:
                data = resp.json()
                print("--- Egress Diagnostic ---")
                print(f"IP:      {data.get('ip')}")
                print(f"City:    {data.get('city')}")
                print(f"Region:  {data.get('region')}")
                print(f"Country: {data.get('country')}")
                print(f"Org/ISP: {data.get('org')}")
                print("-------------------------")
            else:
                print(f"Error: HTTP {resp.status_code} - {resp.text}")
    except Exception as exc:
        print(f"Failed to connect via proxy: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    proxy = sys.argv[1] if len(sys.argv) > 1 else None
    test_egress(proxy)
