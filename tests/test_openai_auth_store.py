from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from orbit.runtime.auth.storage.openai import OpenAIOAuthCredential
from orbit.runtime.auth.storage.openai_store import OpenAIAuthStore


class OpenAIAuthStoreTests(unittest.TestCase):
    def test_prefers_orbit_shared_repo_root_for_file_path(self) -> None:
        with tempfile.TemporaryDirectory() as repo_tmp, tempfile.TemporaryDirectory() as shared_tmp:
            repo_root = Path(repo_tmp)
            shared_root = Path(shared_tmp)
            cred_path = shared_root / '.runtime' / 'openai_oauth_credentials.json'
            cred_path.parent.mkdir(parents=True, exist_ok=True)
            cred_path.write_text(
                json.dumps(
                    {
                        'access_token': 'token-123',
                        'refresh_token': 'refresh-123',
                        'expires_at_epoch_ms': 4102444800000,
                        'account_email': 'orbit@example.com',
                    }
                ),
                encoding='utf-8',
            )

            previous = os.environ.get('ORBIT_SHARED_REPO_ROOT')
            os.environ['ORBIT_SHARED_REPO_ROOT'] = str(shared_root)
            try:
                store = OpenAIAuthStore(repo_root=repo_root)
                credential = store.load()
            finally:
                if previous is None:
                    os.environ.pop('ORBIT_SHARED_REPO_ROOT', None)
                else:
                    os.environ['ORBIT_SHARED_REPO_ROOT'] = previous

            self.assertEqual(store.file_path.resolve(), cred_path.resolve())
            self.assertEqual(credential.access_token, 'token-123')
            self.assertEqual(credential.refresh_token, 'refresh-123')
            self.assertEqual(credential.account_email, 'orbit@example.com')

    def test_defaults_to_repo_root_when_shared_repo_root_unset(self) -> None:
        with tempfile.TemporaryDirectory() as repo_tmp:
            repo_root = Path(repo_tmp)
            credential = OpenAIOAuthCredential(
                access_token='token-abc',
                refresh_token='refresh-abc',
                expires_at_epoch_ms=4102444800000,
                account_email='orbit@example.com',
            )
            previous = os.environ.pop('ORBIT_SHARED_REPO_ROOT', None)
            try:
                store = OpenAIAuthStore(repo_root=repo_root)
                written = store.save(credential)
            finally:
                if previous is not None:
                    os.environ['ORBIT_SHARED_REPO_ROOT'] = previous

            self.assertEqual(written, repo_root / '.runtime' / 'openai_oauth_credentials.json')
            self.assertTrue(written.exists())


if __name__ == '__main__':
    unittest.main()
