# Google login setup and validation

## Configuration

The Google client must be a **Web application** client. Configure the consent
screen and add your test Google account under Audience/Test users if applicable.
In Google Cloud > Google Auth Platform > Clients > your Web client, register the
exact website callback as an **Authorized redirect URI**:

```text
http://localhost:5173/auth/google/callback
https://<your-website-domain>/auth/google/callback
```

Use your actual Vite port; localhost and 127.0.0.1 are different origins. The
callback is a React page, not a Flask endpoint. Register the actual production
website domain separately. No JavaScript client secret or VITE_GOOGLE_SECRET is
needed. This redirect-code integration does not use the Google popup library.

Backend environment (placeholders only):

```dotenv
GOOGLE_CLIENT_ID=<web-client-id>
GOOGLE_CLIENT_SECRET=<web-client-secret>
GOOGLE_REDIRECT_URI=http://localhost:5173/auth/google/callback
SECRET_KEY=<existing-stable-strong-flask-secret>
```

Keep the existing SECRET_KEY; all backend workers must share it. Set the production
GOOGLE_REDIRECT_URI to the production website URL in Vercel. Each backend environment
accepts one website origin for Google login. Do not point local Google login to a
production backend configured for a different origin. Existing frontend
VITE_AUTH_API_BASE_URL (or VITE_API_BASE_URL fallback) must target the intended backend.

```powershell
# Backend
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# Start/restart Flask using your existing development command.

# Website
cd 'D:\Y4s2\python\Go Shoes\website'
npm.cmd run dev
```

No schema migration is needed. Use a development database for initial account
creation. The implementation does not seed roles; an active USER role must exist.

## Flow and safeguards

1. Website creates a cryptographically random PKCE verifier in tab sessionStorage.
2. POST `/api/v1/auth/google/start` with `code_challenge` returns a Google URL and
   signed, ten-minute state binding nonce, challenge, and configured redirect URI.
3. Google redirects to the website callback. The page checks tab-local state,
   consumes the attempt once, removes the URL query, and POSTs `code`, `state`, and
   `code_verifier` to `/api/v1/auth/google/login`.
4. Flask checks exact Origin, JSON shape/body limit, signed state age and PKCE;
   exchanges the code server-side using a fixed Google HTTPS endpoint and bounded
   timeouts. Google authorization codes are single-use. Network failures require
   restarting login, not replaying the callback.
5. Google's official library checks ID-token signature, issuer, audience and expiry;
   application checks nonce, authorized party, stable subject and verified email.
6. New accounts get the USER role and an unknown random password hash. They get
   only a GOOGLE provider link. Returning accounts are located by Google subject,
   not email, and retain their current role. Deleted/disabled users or roles fail.
7. Existing unlinked email matches return 409. No automatic linking or restoration
   of deleted accounts. Sign in through the existing method; authenticated account
   linking is a separate future feature. Google tokens are never persisted.
8. The existing JWT access-token/rotating refresh-session flow is reused. Auth
   responses use no-store. No app tokens appear in redirect URLs. Local registration
   and Google creation share a transaction-scoped PostgreSQL email lock; unique
   provider indexes also enforce identity uniqueness. No hard-coded credentials.

Local password login, Admin login, payment processing and readiness flags are
unchanged. The existing application's browser token-storage policy remains in use.
Facebook is not enabled: add a verified provider strategy to the registry later.

## Manual browser acceptance test

- Set/register the exact callback, restart backend, open website `/login`, choose
  Google, and consent using a test account not already registered locally.
- Confirm redirect to account (or original checkout), profile from `/auth/me`,
  persisted app session, and USER access only for a new account.
- Logout, return with the same Google account, and confirm the same user ID and
  single provider link. Check refresh/logout through existing behavior.
- Cancel Google consent: return to login without an authenticated session.
- Test an email belonging to an existing local account: expect 409 and no link.
- Repeat in deployed website after setting production callback and redeploying both
  projects. Never place the Google secret in frontend env variables.

Real Google consent/login is **not yet verified**. No real accounts or Google
requests were created during automated testing.

## Automated validation and changed files

Google tests cover state/PKCE, expiry, nonce, verified email, authorized party,
real locally signed RSA tokens with audience/issuer/expiry checks, rejected token
exchange, network failure, configuration, origin/body limits, account collision,
disabled accounts, returning identity, profile, refresh rotation and logout.
PostgreSQL integration tests use an isolated disposable local database.
Frontend tests cover PKCE, callback consumption, state rejection, cancellation,
expiry and provider URL validation, alongside existing session tests.

Backend: `.env.example`, `requirements.txt`, `app/config.py`,
`app/routes/v1/auth.py`, `app/services/auth/auth_service.py`,
`app/services/auth/oauth_service.py`,
`app/services/auth/strategies/google_auth_strategy.py`,
`app/repositories/auth_identity_repository.py`, `app/schemas/oauth_schema.py`,
`tests/test_google_auth.py`, and this document.

Website: `index.html`, `src/services/authService.js`,
`src/services/googleLogin.js`, `src/context/AuthProvider.jsx`,
`src/pages/Auth/LoginPage.jsx`, `src/pages/Auth/RegisterPage.jsx`,
`src/pages/Auth/GoogleCallbackPage.jsx`, `src/routes/AppRoutes.jsx`,
`tests/google-login.test.mjs`.

References:
- https://developers.google.com/identity/openid-connect/openid-connect
- https://developers.google.com/identity/protocols/oauth2/web-server
- https://developers.google.com/identity/gsi/web/guides/verify-google-id-token
