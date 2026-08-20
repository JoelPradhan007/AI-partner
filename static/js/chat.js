/* ═══════════════════════════════════════════════════
   Workspace AI (FastAPI) — chat.js
   ═══════════════════════════════════════════════════ */

const messagesEl    = document.getElementById('messages');
const msgInput      = document.getElementById('msgInput');
const sendBtn       = document.getElementById('sendBtn');
const newChatBtn    = document.getElementById('newChatBtn');
const chatTitle     = document.getElementById('chatTitle');
const sidebar       = document.getElementById('sidebar');
const sidebarToggle = document.getElementById('sidebarToggle');
const emptyState    = document.getElementById('emptyState');

// ── Utilities ──────────────────────────────────────
function scrollBottom() { messagesEl.scrollTop = messagesEl.scrollHeight; }

function escHtml(t) {
  return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
function nl2br(t) { return escHtml(t).replace(/\n/g,'<br>'); }

function appendMsg(role, html, streaming = false) {
  const wrap   = document.createElement('div');
  wrap.className = `msg msg--${role}${streaming ? ' msg--streaming' : ''}`;
  const bubble = document.createElement('div');
  bubble.className = 'msg__bubble';
  bubble.innerHTML = html;
  wrap.appendChild(bubble);
  messagesEl.appendChild(wrap);
  scrollBottom();
  return bubble;
}

function showThinking() {
  const wrap = document.createElement('div');
  wrap.className = 'msg msg--assistant';
  wrap.id = '_thinking';
  wrap.innerHTML = '<div class="msg__bubble thinking"><span></span><span></span><span></span></div>';
  messagesEl.appendChild(wrap);
  scrollBottom();
}
function removeThinking() { document.getElementById('_thinking')?.remove(); }

// ── Auto-grow textarea ─────────────────────────────
msgInput.addEventListener('input', () => {
  msgInput.style.height = 'auto';
  msgInput.style.height = Math.min(msgInput.scrollHeight, 140) + 'px';
  const has = msgInput.value.trim().length > 0;
  sendBtn.classList.toggle('active', has);
  sendBtn.disabled = !has;
});

// ── Send ───────────────────────────────────────────
async function sendMessage() {
  const text = msgInput.value.trim();
  if (!text) return;

  emptyState?.remove();
  appendMsg('user', nl2br(text));

  msgInput.value = '';
  msgInput.style.height = 'auto';
  sendBtn.classList.remove('active');
  sendBtn.disabled = true;
  msgInput.disabled = true;

  showThinking();

  let bubble = null;
  let buffer = '';

  try {
    const res = await fetch(SEND_URL, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ conversation_id: CONV_ID, message: text }),
    });

    if (!res.ok) throw new Error(`Server error ${res.status}`);

    const reader  = res.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      if (!bubble) {
        removeThinking();
        bubble = appendMsg('assistant', '', true);
      }
      bubble.innerHTML = nl2br(buffer);
      scrollBottom();
    }

    bubble?.closest('.msg')?.classList.remove('msg--streaming');

  } catch (err) {
    removeThinking();
    appendMsg('assistant', `⚠️ ${escHtml(err.message)}`);
  }

  msgInput.disabled = false;
  msgInput.focus();
}

// ── Key bindings ───────────────────────────────────
msgInput.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (!sendBtn.disabled) sendMessage(); }
});
sendBtn.addEventListener('click', sendMessage);

// ── Suggestion chips ───────────────────────────────
document.querySelectorAll('.chip').forEach(c => {
  c.addEventListener('click', () => {
    msgInput.value = c.dataset.text;
    msgInput.dispatchEvent(new Event('input'));
    msgInput.focus();
  });
});

// ── New conversation ───────────────────────────────
newChatBtn?.addEventListener('click', async () => {
  try {
    const res  = await fetch(NEW_URL, { method: 'POST' });
    const data = await res.json();
    window.location.href = `/chat/${data.id}`;
  } catch (e) { console.error(e); }
});

// ── Sidebar toggle (mobile) ────────────────────────
sidebarToggle?.addEventListener('click', () => sidebar.classList.toggle('sidebar--open'));
document.addEventListener('click', e => {
  if (!sidebar.contains(e.target) && !sidebarToggle?.contains(e.target))
    sidebar.classList.remove('sidebar--open');
});

scrollBottom();
