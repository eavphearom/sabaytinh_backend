"""Google OIDC authorization-code login. Never persist Google tokens."""
import base64
import hashlib
import hmac
import secrets
from urllib.parse import urlencode, urlsplit

import requests
from flask import current_app
from google.auth.exceptions import GoogleAuthError, TransportError
from google.auth.transport.requests import Request
from google.oauth2 import id_token
from itsdangerous import URLSafeTimedSerializer, BadData
from marshmallow import ValidationError, fields

from app.exceptions.api_exception import ApiException, UnauthorizedException


class GoogleAuthStrategy:
    provider = "GOOGLE"

    @staticmethod
    def profile_picture(value):
        """Accept bounded Google-hosted HTTPS images from verified claims only."""
        if not isinstance(value, str) or not value or len(value) > 500 or any(c.isspace() or ord(c) < 32 for c in value):
            return None
        try:
            url = urlsplit(value)
            host = url.hostname or ""
            if (url.scheme == "https" and not url.username and not url.password
                    and url.port in (None, 443) and not url.fragment
                    and any(host == domain or host.endswith("." + domain)
                            for domain in ("googleusercontent.com", "ggpht.com"))):
                return value
        except ValueError:
            pass
        return None

    def configuration(self):
        config = current_app.config
        client, secret, redirect = (config.get(key) for key in
            ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI"))
        signing_key = config.get("SECRET_KEY")
        missing = [key for key, value in (
            ("GOOGLE_CLIENT_ID", client), ("GOOGLE_CLIENT_SECRET", secret),
            ("GOOGLE_REDIRECT_URI", redirect), ("SECRET_KEY", signing_key),
        ) if not isinstance(value, str) or not value.strip()]
        if missing:
            # Names only: never include values, token responses or request payloads.
            current_app.logger.error("Google login configuration missing: %s", ", ".join(missing))
            raise ApiException("Google login is not configured: missing " + ", ".join(missing),
                               503, "Service Unavailable")
        try:
            url = urlsplit(redirect)
            invalid = (redirect != redirect.strip() or any(c.isspace() for c in redirect)
                or not url.hostname or url.username or url.password or url.query or url.fragment
                or url.port == 0
                or (url.scheme != "https" and not (url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1"))))
        except ValueError:
            invalid = True
        if invalid:
            current_app.logger.error("Google login configuration invalid: GOOGLE_REDIRECT_URI")
            raise ApiException("Google login is not configured: invalid GOOGLE_REDIRECT_URI",
                               503, "Service Unavailable")
        return client, secret, redirect, URLSafeTimedSerializer(signing_key, salt="google-login-v1")

    def start(self, challenge):
        client, _, redirect, signer = self.configuration()
        nonce = secrets.token_urlsafe(32)
        state = signer.dumps(dict(nonce=nonce, challenge=challenge, redirect=redirect))
        return dict(state=state, authorization_url="https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
            "client_id": client, "redirect_uri": redirect, "response_type": "code",
            "scope": "openid email profile", "state": state, "nonce": nonce,
            "code_challenge": challenge, "code_challenge_method": "S256", "prompt": "select_account",
        }))

    def verify(self, data):
        client, secret, redirect, signer = self.configuration()
        try:
            state = signer.loads(data["state"], max_age=600)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(data["code_verifier"].encode("ascii")).digest()).rstrip(b"=").decode()
            if (not isinstance(state, dict) or state.get("redirect") != redirect
                    or not hmac.compare_digest(state.get("challenge", ""), challenge)):
                raise ValueError()
        except (BadData, ValueError, TypeError, KeyError, UnicodeError):
            raise UnauthorizedException("Google login expired or invalid; please start again") from None
        try:
            response = requests.post("https://oauth2.googleapis.com/token", data={
                "client_id": client, "client_secret": secret, "redirect_uri": redirect,
                "code": data["code"], "code_verifier": data["code_verifier"],
                "grant_type": "authorization_code",
            }, timeout=(3, 10), allow_redirects=False)
            if response.status_code in (429, 500, 502, 503, 504):
                raise ApiException("Google login temporarily unavailable; please try again", 503, "Service Unavailable")
            if response.status_code != 200:
                raise UnauthorizedException("Google authorization failed; please start again")
            token = response.json().get("id_token")
            if not isinstance(token, str) or not token or len(token) > 16384:
                raise ValueError()
            with requests.Session() as session:
                transport = Request(session=session)
                def bounded_request(*args, **kwargs):
                    kwargs["timeout"] = (3, 10)
                    return transport(*args, **kwargs)
                claims = id_token.verify_oauth2_token(token, bounded_request, audience=client)
            if (claims.get("email_verified") is not True
                    or not isinstance(claims.get("sub"), str) or not 1 <= len(claims["sub"]) <= 255
                    or not isinstance(claims.get("nonce"), str)
                    or not hmac.compare_digest(claims["nonce"], state["nonce"])
                    or claims.get("azp", client) != client):
                raise ValueError()
            email = fields.Email(required=True).deserialize(claims.get("email")).strip().lower()
            if len(email) > 150:
                raise ValueError()
            name = claims.get("name")
            name = name.strip() if isinstance(name, str) else ""
            return dict(provider=self.provider, subject=claims["sub"], email=email,
                        name=(name or email.split("@")[0])[:100],
                        profile=self.profile_picture(claims.get("picture")))
        except (requests.RequestException, TransportError):
            raise ApiException("Google login temporarily unavailable; please try again", 503, "Service Unavailable") from None
        except (ValueError, TypeError, KeyError, AttributeError, ValidationError, GoogleAuthError):
            raise UnauthorizedException("Google identity could not be verified") from None
