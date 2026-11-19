import base64
import hashlib
import os
import time
import unittest
from datetime import timedelta
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import requests
import sqlalchemy as sa
from flask import Flask
from app.exceptions.api_exception import ApiException, UnauthorizedException
from app.services.auth.strategies.google_auth_strategy import GoogleAuthStrategy
from app.extensions import db
from app.models import User, UserAuthProvider, RefreshSession
from tests import test_auth_me as fixture


CONFIG = dict(SECRET_KEY="test-oauth-state-key-not-real", GOOGLE_CLIENT_ID="test-client",
              GOOGLE_CLIENT_SECRET="test-secret", GOOGLE_REDIRECT_URI="http://localhost:5173/auth/google/callback")
VERIFIER = "a" * 43
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()
MODULE = "app.services.auth.strategies.google_auth_strategy"


class GoogleStrategyTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(CONFIG)
        self.ctx = self.app.app_context(); self.ctx.push()
        self.strategy = GoogleAuthStrategy()
        start = self.strategy.start(CHALLENGE)
        self.params = parse_qs(urlsplit(start["authorization_url"]).query)
        self.payload = dict(code="fake-code", state=start["state"], code_verifier=VERIFIER)
        self.claims = dict(sub="google-subject", email="new@example.com", email_verified=True,
                           name="New User", nonce=self.params["nonce"][0])

    def tearDown(self):
        self.ctx.pop()

    def test_authorization_and_verified_identity(self):
        self.assertEqual(self.params["code_challenge_method"], ["S256"])
        self.assertNotIn("client_secret", self.params)
        with patch(MODULE + ".requests.post", return_value=Mock(status_code=200, json=lambda: {"id_token": "token"})) as post, patch(MODULE + ".id_token.verify_oauth2_token", return_value=self.claims) as verify:
            self.assertEqual(self.strategy.verify(self.payload)["subject"], "google-subject")
            self.assertEqual(verify.call_args.kwargs["audience"], "test-client")
            self.assertEqual(post.call_args.kwargs["data"]["code_verifier"], VERIFIER)
            self.assertFalse(post.call_args.kwargs["allow_redirects"])

    def test_verified_picture_is_returned_and_unsafe_optional_pictures_ignored(self):
        photo = "https://lh3.googleusercontent.com/a/test-photo=s96-c"
        with patch(MODULE + ".requests.post", return_value=Mock(status_code=200, json=lambda: {"id_token": "token"})), patch(MODULE + ".id_token.verify_oauth2_token", return_value=self.claims | {"picture": photo}):
            self.assertEqual(self.strategy.verify(self.payload)["profile"], photo)
        for value in (None, "", 123, "javascript:alert(1)", "http://lh3.googleusercontent.com/a",
                      "https://googleusercontent.com.attacker.invalid/a", "https://user@lh3.googleusercontent.com/a",
                      "https://lh3.googleusercontent.com:bad/a", "https://lh3.googleusercontent.com/" + "x" * 500):
            self.assertIsNone(self.strategy.profile_picture(value))

    def test_state_and_pkce_rejected_before_network(self):
        with patch(MODULE + ".requests.post") as post:
            for update in ({"state": "invalid"}, {"code_verifier": "b" * 43}):
                with self.assertRaises(UnauthorizedException): self.strategy.verify(self.payload | update)
            with patch("itsdangerous.timed.time.time", return_value=time.time() + 601):
                with self.assertRaises(UnauthorizedException): self.strategy.verify(self.payload)
            post.assert_not_called()

    def test_claims_and_invalid_tokens(self):
        with patch(MODULE + ".requests.post", return_value=Mock(status_code=200, json=lambda: {"id_token": "token"})):
            for change in ({"nonce": "wrong"}, {"email_verified": False}, {"sub": ""}, {"email": "bad"}, {"azp": "other"}):
                with self.subTest(change=change), patch(MODULE + ".id_token.verify_oauth2_token", return_value=self.claims | change):
                    with self.assertRaises(UnauthorizedException): self.strategy.verify(self.payload)
            with patch(MODULE + ".id_token.verify_oauth2_token", side_effect=ValueError("invalid signature/audience/expiry")):
                with self.assertRaises(UnauthorizedException): self.strategy.verify(self.payload)

    def test_network_and_configuration_fail_closed(self):
        with patch(MODULE + ".requests.post", side_effect=requests.Timeout("private")):
            with self.assertRaises(ApiException) as error: self.strategy.verify(self.payload)
            self.assertEqual(error.exception.status_code, 503)
            self.assertNotIn("private", str(error.exception))
        self.app.config["GOOGLE_CLIENT_SECRET"] = ""
        with self.assertRaises(ApiException): self.strategy.start(CHALLENGE)

    def test_rejected_exchange_never_validates_identity(self):
        for status in (400, 401, 302, 429, 503):
            with patch(MODULE + ".requests.post", return_value=Mock(status_code=status)), patch(MODULE + ".id_token.verify_oauth2_token") as verify:
                with self.assertRaises(ApiException): self.strategy.verify(self.payload)
                verify.assert_not_called()

    def test_real_signature_audience_issuer_and_expiry_validation(self):
        import json
        import jwt
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        claims = self.claims | dict(iss="https://accounts.google.com", aud="test-client", iat=int(time.time()), exp=int(time.time()) + 300)
        cert_response = Mock(status=200, data=json.dumps({"test-key": public}).encode())
        for change in ({}, {"aud": "attacker"}, {"iss": "https://attacker.invalid"}, {"exp": int(time.time()) - 10}):
            token = jwt.encode(claims | change, key, algorithm="RS256", headers={"kid": "test-key"})
            with self.subTest(change=change), patch(MODULE + ".requests.post", return_value=Mock(status_code=200, json=lambda: {"id_token": token})), patch(MODULE + ".Request", return_value=Mock(return_value=cert_response)):
                if change:
                    with self.assertRaises(UnauthorizedException): self.strategy.verify(self.payload)
                else:
                    self.assertEqual(self.strategy.verify(self.payload)["subject"], "google-subject")


@unittest.skipUnless(os.getenv("CHECKOUT_TEST_DATABASE_URL"), "Temporary PostgreSQL required")
class GoogleLoginTests(unittest.TestCase):
    setUpClass = classmethod(fixture.AuthMeTests.setUpClass.__func__)
    tearDownClass = classmethod(fixture.AuthMeTests.tearDownClass.__func__)
    tearDown = fixture.AuthMeTests.tearDown
    add_order = fixture.AuthMeTests.add_order

    def setUp(self):
        fixture.AuthMeTests.setUp(self)
        self.app.config.update(CONFIG, JWT_REFRESH_TOKEN_EXPIRES=timedelta(days=7))
        # Fixture inserts explicit user IDs; advance its isolated identity sequence.
        with db.engine.begin() as conn:
            conn.execute(sa.text(f'ALTER TABLE "{self.schema}".users ALTER COLUMN id RESTART WITH 10'))
        self.identity = dict(provider="GOOGLE", subject="subject", email="google@example.com", name="Google User")
        self.payload = dict(code="code", state="state", code_verifier=VERIFIER)

    def login(self):
        with patch.object(GoogleAuthStrategy, "verify", return_value=self.identity):
            return self.client.post("/api/v1/auth/google/login", json=self.payload, headers={"Origin": "http://localhost:5173"})

    def test_new_returning_profile_refresh_logout(self):
        result = self.login()
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.headers["Cache-Control"], "no-store")
        data = result.json["data"]
        self.assertEqual(data["role"], "USER")
        self.assertNotIn("password", data)
        user = db.session.get(User, data["id"])
        self.assertTrue(user.password)
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(UserAuthProvider)), 1)
        again = self.login().json["data"]
        self.assertEqual(again["id"], data["id"])
        headers = {"Authorization": "Bearer " + data["access_token"]}
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=headers).status_code, 200)
        refreshed = self.client.post("/api/v1/auth/refresh", json={"refresh_token": data["refresh_token"]})
        self.assertEqual(refreshed.status_code, 200)
        self.assertEqual(self.client.post("/api/v1/auth/refresh", json={"refresh_token": data["refresh_token"]}).status_code, 401)
        self.assertEqual(self.client.post("/api/v1/auth/logout", headers=headers).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=headers).status_code, 401)

    def test_no_automatic_email_linking(self):
        self.identity["email"] = db.session.get(User, 1).email
        self.assertEqual(self.login().status_code, 409)
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(UserAuthProvider)), 0)

    def test_google_photo_saved_backfilled_and_custom_upload_preserved(self):
        photo = "https://lh3.googleusercontent.com/a/test-photo=s96-c"
        self.identity["profile"] = photo
        data = self.login().json["data"]
        headers = {"Authorization": "Bearer " + data["access_token"]}
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=headers).json["data"]["profile"], photo)
        user = db.session.get(User, data["id"])
        user.profile = None
        db.session.commit()
        self.login()
        self.assertEqual(db.session.get(User, data["id"]).profile, photo)
        user.profile = "/uploads/profiles/custom.png"
        db.session.commit()
        self.login()
        self.assertEqual(db.session.get(User, data["id"]).profile, "/uploads/profiles/custom.png")
        self.assertTrue(self.client.get("/api/v1/auth/me", headers=headers).json["data"]["profile"].endswith("/uploads/profiles/custom.png"))

    def test_disabled_and_deleted_accounts(self):
        data = self.login().json["data"]
        user = db.session.get(User, data["id"])
        for field, value in (("status", "INACTIVE"), ("is_deleted", True)):
            old = getattr(user, field); setattr(user, field, value); db.session.commit()
            self.assertEqual(self.login().status_code, 401)
            setattr(user, field, old); db.session.commit()
        user.role.is_active = False; db.session.commit()
        self.assertEqual(self.login().status_code, 401)

    def test_origin_payload_and_size_validation(self):
        path = "/api/v1/auth/google/login"
        with patch.object(GoogleAuthStrategy, "verify") as verify:
            self.assertEqual(self.client.post(path, json=self.payload).status_code, 403)
            self.assertEqual(self.client.post(path, json=self.payload, headers={"Origin": "https://attacker.invalid"}).status_code, 403)
            headers = {"Origin": "http://localhost:5173"}
            self.assertEqual(self.client.post(path, json=self.payload | {"role": "ADMIN"}, headers=headers).status_code, 400)
            self.assertEqual(self.client.post(path, data="{", content_type="application/json", headers=headers).status_code, 400)
            self.assertEqual(self.client.post(path, json={"code": "x" * 20000}, headers=headers).status_code, 413)
            verify.assert_not_called()
