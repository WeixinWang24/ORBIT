#!/usr/bin/env python
"""Bootstrap OpenAI OAuth credentials for ORBIT local development.

Usage (choose one):

  # Option A — paste a full JSON credential blob
  python scripts/bootstrap_openai_auth.py --json '{"access_token":"sk-...","refresh_token":"...","expires_at_epoch_ms":9999999999000,"account_email":"you@example.com"}'

  # Option B — paste individual fields
  python scripts/bootstrap_openai_auth.py \
      --access-token  "sk-..." \
      --refresh-token "..." \
      --expires-at-ms 9999999999000 \
      --email         "you@example.com"

  # Option C — start PKCE browser flow (prints authorize URL; complete exchange manually)
  python scripts/bootstrap_openai_auth.py --pkce

The credential is written to:
  <repo>/.runtime/openai_oauth_credentials.json  (chmod 600)
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from orbit.runtime.auth.oauth.openai_handshake import persist_manual_oauth_credential, persist_manual_oauth_credential_from_json
from orbit.runtime.auth.oauth.openai_oauth_pkce import create_openai_oauth_pkce_session


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap ORBIT OpenAI OAuth credentials")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--json", metavar="JSON", help="Full credential JSON blob")
    group.add_argument("--access-token", metavar="TOKEN", help="OpenAI access token")
    group.add_argument("--pkce", action="store_true", help="Print PKCE authorize URL and exit")
    parser.add_argument("--refresh-token", metavar="TOKEN", default="", help="Refresh token (with --access-token)")
    parser.add_argument("--expires-at-ms", metavar="MS", type=int, default=0, help="Expiry epoch ms (with --access-token)")
    parser.add_argument("--email", metavar="EMAIL", default=None, help="Account email (optional)")
    args = parser.parse_args()

    if args.pkce:
        session = create_openai_oauth_pkce_session()
        print("\nOpen this URL in your browser to authorize ORBIT:\n")
        print(f"  {session.authorize_url}\n")
        print(f"code_verifier (keep secret): {session.code_verifier}")
        print(f"state:                       {session.state}")
        print("\nAfter authorizing, use --json or --access-token to save the resulting tokens.")
        return

    if args.json:
        result = persist_manual_oauth_credential_from_json(repo_root=REPO_ROOT, json_text=args.json)
    else:
        expires_ms = args.expires_at_ms or int((time.time() + 3600 * 24 * 30) * 1000)
        result = persist_manual_oauth_credential(
            repo_root=REPO_ROOT,
            access_token=args.access_token,
            refresh_token=args.refresh_token,
            expires_at_epoch_ms=expires_ms,
            account_email=args.email,
        )

    print(f"\nCredential saved to: {result.credential_path}")
    print(f"Account:             {result.account_email or '(not set)'}")
    ttl_hours = (result.expires_at_epoch_ms - int(time.time() * 1000)) / 3_600_000
    print(f"Expires in:          {ttl_hours:.1f} hours")


if __name__ == "__main__":
    main()
