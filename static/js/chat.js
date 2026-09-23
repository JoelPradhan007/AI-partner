const messagesEl    = document.getElementById('messages');
const msgInput      = document.getElementById('msgInput');
const sendBtn       = document.getElementById('sendBtn');
const newChatBtn    = document.getElementById('newChatBtn');
const chatTitle     = document.getElementById('chatTitle');
const sidebar       = document.getElementById('sidebar');
const sidebarToggle = document.getElementById('sidebarToggle');
const emptyState    = document.getElementById('emptyState');
const backdropEl    = document.getElementById('sidebarBackdrop');

// ── Configure Marked Parser ────────────────────────
if (typeof marked !== 'undefined') {
  const renderer = new marked.Renderer();
  renderer.link = function({ href, title, text }) {
    const titleAttr = title ? ` title="${title}"` : '';
    return `<a href="${href}"${titleAttr} target="_blank" rel="noopener noreferrer">${text}</a>`;
  };
  marked.use({ renderer });
}

// ── Utilities ──────────────────────────────────────
function scrollBottom() { messagesEl.scrollTop = messagesEl.scrollHeight; }

function escHtml(t) {
  return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function renderMarkdown(t) {
  if (typeof marked !== 'undefined') {
    return marked.parse(t);
  }
  return escHtml(t).replace(/\n/g, '<br>');
}

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
  appendMsg('user', renderMarkdown(text));

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
      bubble.innerHTML = renderMarkdown(buffer);
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

// ── Delete Conversation ────────────────────────────
document.querySelectorAll('.conv-item__delete').forEach(btn => {
  btn.addEventListener('click', async (e) => {
    e.preventDefault();
    e.stopPropagation();

    const convId = btn.dataset.id;
    if (!convId) return;

    const confirmed = confirm("Are you sure you want to delete this chat?");
    if (!confirmed) return;

    try {
      const res = await fetch(`/api/conversations/${convId}`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' }
      });

      if (res.ok) {
        document.getElementById(`conv-item-${convId}`)?.remove();
        
        if (typeof CONV_ID !== 'undefined' && parseInt(convId, 10) === CONV_ID) {
          window.location.href = '/chat';
        }
      } else {
        alert("Failed to delete conversation.");
      }
    } catch (err) {
      console.error("Error deleting conversation:", err);
      alert("Error contacting server to delete chat.");
    }
  });
});

// ── Sidebar Toggle & Mobile Backdrop Logic ─────────
const appEl = document.querySelector('.app');

function closeMobileSidebar() {
  sidebar.classList.remove('sidebar--open');
  backdropEl?.classList.remove('active');
}

sidebarToggle?.addEventListener('click', () => {
  if (window.innerWidth <= 768) {
    const isOpen = sidebar.classList.toggle('sidebar--open');
    backdropEl?.classList.toggle('active', isOpen);
  } else {
    appEl.classList.toggle('sidebar-collapsed');
  }
});

backdropEl?.addEventListener('click', closeMobileSidebar);

document.querySelectorAll('.conv-item__link').forEach(link => {
  link.addEventListener('click', () => {
    if (window.innerWidth <= 768) closeMobileSidebar();
  });
});

scrollBottom();
