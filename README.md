# Workspace AI — FastAPI Edition

Personal AI chatbot grounded in your live Gmail, Drive, and Calendar data.
Uses **Authlib** for OAuth (solves the "missing OAuth state" bug permanently),
**FastAPI** for async streaming, and **Gemini 2.5 Flash** for AI.

---

## Directory Structure

```
workspace_ai_fastapi/
├── main.py                ← FastAPI app + all routes
├── config.py              ← Pydantic settings (reads .env)
├── database.py            ← Async SQLAlchemy engine
├── models.py              ← User, Conversation, Message ORM models
├── oauth.py               ← Authlib Google OAuth + Fernet encryption
├── workspace_fetcher.py   ← Gmail / Drive / Calendar helpers
├── requirements.txt
├── .env.example
├── templates/
│   ├── login.html
│   └── chat.html
└── static/
    ├── css/main.css
    └── js/chat.js
```

---

## Deployment Sequence

### Step 1 — Google Cloud Console

1. Create project → enable **Gmail API**, **Drive API**, **Calendar API**, **People API**
2. OAuth consent screen → External → add your Gmail as test user
3. Add scopes: `gmail.readonly`, `drive.readonly`, `calendar.readonly`, `email`, `profile`, `openid`
4. Credentials → Create → **Web application**
   - Authorised redirect URI: `http://localhost:8000/auth/callback`
   - Copy Client ID and Client Secret

### Step 2 — Gemini API Key

Get from https://aistudio.google.com/app/apikey

### Step 3 — Local Setup

```bash
cd workspace_ai_fastapi

python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

pip install -r requirements.txt

# Generate Fernet key
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

cp .env.example .env
# Edit .env — fill in all 5 values
```

### Step 4 — Run

```bash
uvicorn main:app --reload
```

Open http://localhost:8000 → click **Continue with Google** → chat.

No `migrate` command needed — tables are created automatically on startup via `init_db()`.

---

## Why Authlib Fixes the OAuth State Bug

Django's `google-auth-oauthlib` requires you to manually save/read state from
the session, which breaks if the session doesn't flush before the redirect.

Authlib's `starlette_client` handles state internally:
- `authorize_redirect()` saves state to session and redirects
- `authorize_access_token()` reads and validates state automatically

You never touch the state manually — so it never goes missing.

---

## Key Files Explained

| File | Purpose |
|------|---------|
| `main.py` | All FastAPI routes. `/auth/google` → Google, `/auth/callback` ← Google, `/chat/{id}` renders UI, `/api/chat/send` streams Gemini |
| `oauth.py` | Authlib OAuth registry, Fernet encrypt/decrypt, `build_credentials()` |
| `workspace_fetcher.py` | Calls Gmail/Drive/Calendar APIs, returns plain-text context |
| `main.py` `stream_gemini()` | Async generator — yields Gemini tokens, saves reply when done |

---

## Production Checklist

- [ ] `DEBUG=False`, strong `APP_SECRET_KEY`
- [ ] Switch to PostgreSQL: `DATABASE_URL=postgresql+asyncpg://user:pass@host/db`
- [ ] Update `GOOGLE_REDIRECT_URI` to production domain
- [ ] Add production redirect URI in Google Cloud Console
- [ ] Run behind nginx + HTTPS
- [ ] Set `https_only=True` in `SessionMiddleware`
