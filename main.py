import asyncio
import contextvars
import json
import logging
import re
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.sessions import SessionMiddleware

from google import genai
from google.genai import types as genai_types

from config import get_settings
from database import init_db, get_db
from models import User, Conversation, Message
from oauth import (
    oauth, get_google_auth_url, handle_google_callback,
    encrypt_token, build_credentials,
)
from workspace_fetcher import build_workspace_context

settings = get_settings()

# Directory for user workspace data / chat history
USER_DATA_DIR = Path("user_data")
USER_DATA_DIR.mkdir(exist_ok=True)

# Directory for live runtime server logs per user
INFO_HISTORY_DIR = Path("info_history")
INFO_HISTORY_DIR.mkdir(exist_ok=True)

current_user_email: contextvars.ContextVar[str] = contextvars.ContextVar("current_user_email", default="")
last_known_user_email: str = ""


class UserLogFileHandler(logging.Handler):
    """
    Directs live runtime server logs directly into info_history/<user_email>.txt.
    Never creates server.log.
    """
    def __init__(self, base_dir: Path):
        super().__init__()
        self.base_dir = base_dir
        self.base_dir.mkdir(exist_ok=True)

    def emit(self, record: logging.LogRecord):
        try:
            global last_known_user_email
            email = current_user_email.get() or last_known_user_email
            if not email:
                return  # Never create server.log

            msg = self.format(record)
            safe_name = re.sub(r'[^a-zA-Z0-9_.@-]', '_', email)
            log_file = self.base_dir / f"{safe_name}.txt"

            with open(log_file, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except Exception:
            self.handleError(record)


log_formatter = logging.Formatter(
    "[%(asctime)s UTC] [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
file_handler = UserLogFileHandler(INFO_HISTORY_DIR)
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.INFO)

root_logger = logging.getLogger()
root_logger.addHandler(file_handler)

logger = logging.getLogger(__name__)


# Track last logged workspace snapshot per user to avoid duplicate dumps
_last_logged_workspace_snapshots: dict[str, str] = {}


def log_user_data(user: User, workspace_context: str = "", user_text: str = "", assistant_text: str = ""):
    """Save clean chat interactions and updated workspace data to user_data/<email>.txt"""
    try:
        identifier = user.email or f"user_{user.id}"
        safe_name = re.sub(r'[^a-zA-Z0-9_.@-]', '_', identifier)
        file_path = USER_DATA_DIR / f"{safe_name}.txt"

        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        entry = [
            f"\n{'='*70}",
            f"TIMESTAMP: {timestamp}",
            f"USER: {user.display_name or 'User'} ({user.email})",
        ]

        # Only log workspace snapshot when it is new or changed, avoiding repeating 60+ lines on every message
        if workspace_context and workspace_context != "(Google account not linked)":
            prev_snapshot = _last_logged_workspace_snapshots.get(identifier)
            if prev_snapshot != workspace_context:
                _last_logged_workspace_snapshots[identifier] = workspace_context
                entry.append(f"\n[WORKSPACE DATA SNAPSHOT (UPDATED)]:\n{workspace_context}")

        if user_text:
            entry.append(f"\n[USER QUESTION]:\n{user_text}")
        if assistant_text:
            entry.append(f"\n[AI RESPONSE]:\n{assistant_text}")
        entry.append(f"{'='*70}\n")

        with open(file_path, "a", encoding="utf-8") as f:
            f.write("\n".join(entry))
    except Exception as e:
        logger.warning("Failed to save user data file: %s", e)


# ── Startup / shutdown ────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    server_log = INFO_HISTORY_DIR / "server.log"
    if server_log.exists():
        try:
            server_log.unlink()
        except Exception:
            pass
    logger.info("Database ready.")
    yield

app = FastAPI(title="Workspace AI", lifespan=lifespan)

# Normalize 127.0.0.1 to localhost so OAuth matches the callback domain
@app.middleware("http")
async def normalize_domain_middleware(request: Request, call_next):
    host = request.url.hostname
    if host == "127.0.0.1" and "localhost" in settings.google_redirect_uri:
        normalized_url = request.url.replace(hostname="localhost")
        return RedirectResponse(str(normalized_url), status_code=status.HTTP_302_FOUND)
    return await call_next(request)

# Set user context for live log routing to info_history/<email>.txt
@app.middleware("http")
async def user_logging_context_middleware(request: Request, call_next):
    global last_known_user_email
    email = request.session.get("user_email", "")
    if email:
        last_known_user_email = email
    token = current_user_email.set(email)
    try:
        response = await call_next(request)
        return response
    finally:
        current_user_email.reset(token)

# Session middleware — Authlib needs this to store OAuth state
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.app_secret_key,
    same_site="lax",
    https_only=False, 
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# ── Auth helpers ──────────────────────────────────────────────────

async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    global last_known_user_email
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    result = await db.execute(select(User).where(User.id == user_id))
    user   = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if user.email:
        request.session["user_email"] = user.email
        last_known_user_email = user.email
        current_user_email.set(user.email)
    return user


# ── Pages ─────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/chat", status_code=status.HTTP_302_FOUND)
    return RedirectResponse("/login", status_code=status.HTTP_302_FOUND)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


# ── Google OAuth ──────────────────────────────────────────────────

@app.get("/auth/google")
async def auth_google(request: Request):
    """
    Redirect to Google consent screen.
    Authlib automatically saves the state into request.session.
    """
    redirect_uri = settings.google_redirect_uri
    return await oauth.google.authorize_redirect(request, redirect_uri)


@app.get("/auth/callback")
async def auth_callback(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Google redirects here after consent.
    Authlib validates the state from session automatically — no manual check needed.
    """
    try:
        token    = await oauth.google.authorize_access_token(request)
        userinfo = token.get("userinfo")
        if not userinfo:
            userinfo = await oauth.google.userinfo(token=token)
    except Exception as exc:
        logger.exception("OAuth callback failed: %s", exc)
        return RedirectResponse("/login?error=oauth_failed", status_code=status.HTTP_302_FOUND)

    google_id    = userinfo["sub"]
    email        = userinfo["email"]
    display_name = userinfo.get("name", "")
    avatar_url   = userinfo.get("picture", "")
    encrypted    = encrypt_token(token)

    # Upsert user
    result = await db.execute(select(User).where(User.google_id == google_id))
    user   = result.scalar_one_or_none()

    if user:
        user.email                 = email
        user.display_name          = display_name
        user.avatar_url            = avatar_url
        user.encrypted_credentials = encrypted
        user.updated_at            = datetime.now(timezone.utc)
    else:
        user = User(
            google_id=google_id,
            email=email,
            display_name=display_name,
            avatar_url=avatar_url,
            encrypted_credentials=encrypted,
        )
        db.add(user)

    await db.refresh(user)

    global last_known_user_email
    request.session["user_id"] = user.id
    request.session["user_email"] = user.email
    last_known_user_email = user.email
    current_user_email.set(user.email)
    logger.info("User %s logged in.", email)
    return RedirectResponse("/chat", status_code=status.HTTP_302_FOUND)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=status.HTTP_302_FOUND)


# ── Chat UI ───────────────────────────────────────────────────────

@app.get("/chat", response_class=HTMLResponse)
async def chat_index(request: Request, db: AsyncSession = Depends(get_db),
                     user: User = Depends(get_current_user)):
    # Get or create first conversation
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(desc(Conversation.updated_at))
        .limit(1)
    )
    conv = result.scalar_one_or_none()
    if not conv:
        conv = Conversation(user_id=user.id, title="My Workspace")
        db.add(conv)
        await db.commit()
        await db.refresh(conv)
    return RedirectResponse(f"/chat/{conv.id}", status_code=status.HTTP_302_FOUND)


@app.get("/chat/{conv_id}", response_class=HTMLResponse)
async def chat_conversation(
    request: Request, conv_id: int,
    db: AsyncSession = Depends(get_db),
    user: User       = Depends(get_current_user),
):
    result = await db.execute(
        select(Conversation).where(Conversation.id == conv_id, Conversation.user_id == user.id)
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    convs_result = await db.execute(
        select(Conversation).where(Conversation.user_id == user.id)
        .order_by(desc(Conversation.updated_at)).limit(20)
    )
    conversations = convs_result.scalars().all()

    msgs_result = await db.execute(
        select(Message).where(Message.conversation_id == conv_id)
        .order_by(Message.created_at)
    )
    messages = msgs_result.scalars().all()

    return templates.TemplateResponse("chat.html", {
        "request":       request,
        "user":          user,
        "conversation":  conv,
        "conversations": conversations,
        "messages":      messages,
    })


# ── API endpoints ─────────────────────────────────────────────────

@app.post("/api/conversations")
async def new_conversation(
    db:   AsyncSession = Depends(get_db),
    user: User         = Depends(get_current_user),
):
    conv = Conversation(user_id=user.id, title="New Conversation")
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return {"id": conv.id, "title": conv.title}




class SendMessageRequest(BaseModel):
    conversation_id: int
    message: str


@app.post("/api/chat/send")
async def send_message(
    body: SendMessageRequest,
    request: Request,
    db:   AsyncSession = Depends(get_db),
    user: User         = Depends(get_current_user),
):
    # Validate conversation belongs to user
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == body.conversation_id,
            Conversation.user_id == user.id,
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404)

    user_text = body.message.strip()
    if not user_text:
        raise HTTPException(status_code=400, detail="Empty message")

    # Save user message
    user_msg = Message(conversation_id=conv.id, role="user", content=user_text)
    db.add(user_msg)

    # Auto-title from first message
    msgs_count = await db.execute(
        select(Message).where(Message.conversation_id == conv.id)
    )
    if len(msgs_count.scalars().all()) == 1:
        conv.title = user_text[:60]

    await db.commit()

    # Build Gemini history
    history_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv.id, Message.role != "user")
        .order_by(Message.created_at)
    )
    # Actually get all prior messages for history
    all_msgs_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at)
    )
    all_msgs = all_msgs_result.scalars().all()[:-1]  # exclude the one we just saved

    history = [
        genai_types.Content(
            role="user" if m.role == "user" else "model",
            parts=[genai_types.Part(text=m.content)],
        )
        for m in all_msgs
    ]

    # Fetch workspace context
    workspace_context = "(Google account not linked)"
    try:
        creds = build_credentials(user)
        # Persist refreshed token if needed
        await db.commit()
        workspace_context = await asyncio.to_thread(build_workspace_context, creds)
    except Exception as exc:
        logger.warning("Workspace fetch failed: %s", exc)

    system_prompt = f"""You are a personal AI assistant for {user.display_name or user.email}.
You have live access to their Google Workspace data. Use it to give grounded, specific answers.

--- LIVE WORKSPACE DATA ---
{workspace_context}
--- END ---

Current UTC time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}
"""

    async def stream_gemini():
        full_reply = []
        try:
            client = genai.Client(api_key=settings.gemini_api_key)
            chat   = client.chats.create(
                model=settings.gemini_model,
                config=genai_types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.7,
                ),
                history=history,
            )
            # Run blocking stream in thread pool
            loop = asyncio.get_event_loop()
            stream = await loop.run_in_executor(
                None, lambda: chat.send_message_stream(user_text)
            )
            for chunk in stream:
                token = chunk.text or ""
                full_reply.append(token)
                yield token

        except Exception as exc:
            logger.exception("Gemini error: %s", exc)
            error_msg = f"\n\n⚠️ AI error: {exc}"
            full_reply.append(error_msg)
            yield error_msg

        # Persist assistant reply
        complete = "".join(full_reply)
        async with AsyncSession(db.bind) as save_session:
            save_session.add(Message(
                conversation_id=conv.id, role="assistant", content=complete
            ))
            conv_update = await save_session.get(Conversation, conv.id)
            if conv_update:
                conv_update.updated_at = datetime.now(timezone.utc)
            await save_session.commit()

        # Log workspace context and conversation to user file
        log_user_data(user, workspace_context=workspace_context, user_text=user_text, assistant_text=complete)

    return StreamingResponse(stream_gemini(), media_type="text/plain; charset=utf-8")
