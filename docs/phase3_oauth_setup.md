# Phase 3 — OAuth setup guide (Meta + Google)

This is a step-by-step guide to set up the credentials needed for self-serve
onboarding: friends sign in with Google and authorize their Meta/Google ad
accounts. We stay in **development / testing mode** the whole time, so there is
**no App Review and no Google verification** — you just add friends as testers.

> Security: never paste secrets into chat or commit them. Put the values into
> your local `.env` (it is gitignored). When you finish, just say "done".

We will use these local redirect URLs (the app runs on `http://localhost:8765`):

- Meta callback:  `http://localhost:8765/oauth/meta/callback`
- Google callback: `http://localhost:8765/oauth/google/callback`

You can add the Cloud Run production URL later; multiple redirect URLs are fine.

---

## Part 1 — Meta (Facebook) app

You already have a Meta app (`META_APP_ID` is set). We just add login + ads
permission and register the redirect URL.

1. Go to <https://developers.facebook.com/apps> and open your app (the one whose
   App ID is in your `.env`). Top bar should say **"In development"** — keep it
   that way.
2. **Add Facebook Login**: left menu → "Add product" → **Facebook Login** → set
   up → choose **Web**. You can skip the quickstart code steps.
3. Left menu → **Facebook Login → Settings**:
   - **Client OAuth Login**: ON
   - **Web OAuth Login**: ON
   - **Valid OAuth Redirect URIs**: in **development mode you do NOT need to add
     `http://localhost` here** — Meta allows localhost redirects automatically
     while the app is in development. (You can leave this field empty.) You will
     add the real production URL here later when the app goes live on Cloud Run.
     Note: Google is different — see Part 2B, where the localhost redirect URI
     **must** be added explicitly.
   - Save changes.
4. **Add Marketing API**: left menu → "Add product" → **Marketing API** (this is
   what allows reading ad accounts/insights via `ads_read`).
5. **Add your friends as testers**: left menu → **App roles → Roles** (or
   "Test Users"/"Roles" depending on the UI) → **Add Testers** → enter each
   friend's Facebook account. They'll get a request to accept. In development
   mode, testers can grant `ads_read` **without App Review**.
6. **Confirm your app credentials**: Settings → Basic → note **App ID** and
   **App Secret**. These should already match your `.env`
   (`META_APP_ID`, `META_APP_SECRET`). If not, copy them into `.env`.

**What this gives us:** friends click "Connect Meta", a Facebook popup asks them
to grant `ads_read`, and we receive a token to list/sync their ad accounts.

---

## Part 2 — Google (sign-in + Google Ads)

We need a **Web** OAuth client. Note: your existing `GOOGLE_ADS_CLIENT_ID` was
likely a "Desktop" client used once to mint a refresh token. Leave it alone — we
create a **new Web client** so the existing pipeline keeps working.

### 2A. OAuth consent screen (who can log in)

> UI note: Google renamed this area to **"Google Auth Platform"**. The old single
> "OAuth consent screen / User type: External" page is now split across left-nav
> tabs: **Branding**, **Audience**, **Clients**, **Data Access**. Open it via
> <https://console.cloud.google.com/auth/overview> (project `oudseed`), or
> APIs & Services → OAuth consent screen (it redirects to the new UI).

1. Select the **`oudseed`** project (top-left project picker). If the screen
   shows a "Get started" button, click it and fill App name + choose audience
   **External** + contact email.
2. **Audience** tab:
   - **User type = External**
   - **Publishing status = Testing** (no verification needed for test users)
   - **Test users**: add your own Google email and each friend's Google email.
3. **Branding** tab: set App name (e.g. "OudSeed"), user support email, developer
   contact email (if not already set during Get started).
4. **Data Access** tab → "Add or remove scopes", add:
   - `openid`
   - `.../auth/userinfo.email`
   - `.../auth/userinfo.profile`
   - `https://www.googleapis.com/auth/adwords`  (for Google Ads)
   Save.

### 2B. Web OAuth client (the login button)

1. In the **Google Auth Platform → Clients** tab (or APIs & Services →
   Credentials). Direct link: <https://console.cloud.google.com/auth/clients>.
2. **Create client** (or "Create credentials → OAuth client ID").
3. **Application type: Web application**. Name it e.g. "OudSeed Web".
4. **Authorized redirect URIs** → Add:
   `http://localhost:8765/oauth/google/callback`
5. Create. Copy the **Client ID** and **Client Secret** into `.env` as:
   - `GOOGLE_OAUTH_CLIENT_ID`
   - `GOOGLE_OAUTH_CLIENT_SECRET`

### 2C. Enable the Google Ads API

1. Left menu → **APIs & Services → Library** → search **"Google Ads API"** →
   **Enable** (for the `oudseed` project).

### 2D. Google Ads developer token (you likely already have this)

Your `.env` has `GOOGLE_ADS_DEVELOPER_TOKEN`, and the current pipeline already
pulls real Google Ads data — so it almost certainly has at least **Basic
access**, which is enough. If you want to confirm: Google Ads UI → **Tools →
Setup → API Center** shows the token's access level.

**What this gives us:** friends click "Sign in with Google" to enter the app,
and "Connect Google Ads" to authorize reading their Google Ads data.

---

## Checklist — what to put in `.env`

```bash
# Meta (you already have these)
META_APP_ID=...
META_APP_SECRET=...
META_OAUTH_REDIRECT_URI=http://localhost:8765/oauth/meta/callback

# Google sign-in + Google Ads OAuth (NEW web client from Part 2B)
GOOGLE_OAUTH_CLIENT_ID=...
GOOGLE_OAUTH_CLIENT_SECRET=...
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:8765/oauth/google/callback

# Already set in earlier phases
GOOGLE_ADS_DEVELOPER_TOKEN=...   # existing, keep
TOKEN_ENCRYPTION_KEY=...         # encrypts stored tokens (generate if missing)
APP_BASE_URL=http://localhost:8765
```

Generate the token-encryption key if you don't have one yet:

```bash
.venv/bin/python -c "from src.storage.crypto import generate_key; print(generate_key())"
```

When all of the above are filled in, tell me **"done"** and I'll build the OAuth
connect flow and Google sign-in against these settings.

---

## FAQ

- **Do I need to pay or wait for review?** No. Development/testing mode + adding
  friends as testers/test-users avoids both Meta App Review and Google
  verification, for a small number of known users.
- **Is this safe to share with friends?** Yes — they only grant read access to
  their own ad data, and only people you explicitly add as testers can connect.
- **Will this break the current pipeline?** No. We add a new Google *Web* client
  and reuse the Meta app; existing `GOOGLE_ADS_*` values stay untouched.
