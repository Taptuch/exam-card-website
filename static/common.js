/* Shared front-end helpers: translations, API calls, DOM builder, top bar (status, language),
   settings dialog, online bookmark. */
(() => {
  'use strict';

  const csrf = document.querySelector('meta[name="csrf"]')?.content || '';
  const $ = (sel, root = document) => root.querySelector(sel);

  // ----------------------------------------------------------------- i18n
  let strings = {};
  try { strings = JSON.parse($('#i18n-data')?.textContent || '{}'); } catch { /* use keys as text */ }
  const lang = document.documentElement.lang || 'en';

  function t(key, vars) {
    let s = strings[key] ?? key;
    if (vars) s = s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? vars[k] : m));
    return s;
  }
  // plural: tn('n.card', 3) -> picks n.card.one / .few (2-4) / .many
  function tn(base, n) {
    const form = n === 1 ? 'one' : (n >= 2 && n <= 4 ? 'few' : 'many');
    return t(`${base}.${form}`, { n });
  }

  // ------------------------------------------------------------------ API
  class ApiError extends Error {
    constructor(message, status, data) { super(message); this.status = status; this.data = data; }
  }

  async function api(path, { method = 'GET', body, form } = {}) {
    const opts = { method, headers: { 'X-CSRF-Token': csrf }, credentials: 'same-origin' };
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    } else if (form) {
      opts.body = form;
    }
    const res = await fetch('/api' + path, opts);
    let data = null;
    try { data = await res.json(); } catch { /* empty body */ }
    if (res.status === 401) { location.href = '/login'; throw new ApiError('Not signed in', 401, data); }
    if (res.status === 403 && data?.error === 'password_change_required') {
      location.href = '/change-password';
      throw new ApiError('Password change required', 403, data);
    }
    if (!res.ok) throw new ApiError(data?.error || res.statusText || 'Request failed', res.status, data);
    return data;
  }

  // ------------------------------------------------------------ DOM helper
  // h('div', {class: 'x', onclick: fn}, 'text', childEl) - text is always inserted as text, never as HTML.
  function h(tag, attrs, ...children) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else if (v === true) el.setAttribute(k, '');
      else el.setAttribute(k, v);
    }
    for (const c of children.flat(Infinity)) {
      if (c == null || c === false) continue;
      el.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return el;
  }

  function fillAvatar(el, name, url) {
    el.replaceChildren();
    if (url) el.append(h('img', { src: url, alt: '' }));
    else el.textContent = (name || '?').trim().charAt(0).toUpperCase() || '?';
  }

  function avatar(name, url, extra = '') {
    const el = h('span', { class: ('avatar ' + extra).trim() });
    fillAvatar(el, name, url);
    return el;
  }

  // avatar with a Discord-style status dot
  function avatarWithDot(name, url, status, extra = '') {
    return h('span', { class: 'avatar-wrap' }, avatar(name, url, extra), h('span', { class: 'sdot ' + status }));
  }

  function timeAgo(when) {
    const ts = typeof when === 'number' ? when * 1000 : Date.parse(when);
    const s = Math.max(0, Math.round((Date.now() - ts) / 1000));
    if (s < 45) return t('time.now');
    const m = Math.round(s / 60);
    if (m < 60) return t('time.min', { n: m });
    const hr = Math.round(m / 60);
    if (hr < 24) return t('time.hour', { n: hr });
    const d = Math.round(hr / 24);
    if (d < 30) return t('time.day', { n: d });
    return new Date(ts).toLocaleDateString(lang);
  }

  function setStatus(el, message, ok = false) {
    el.textContent = message || '';
    el.classList.toggle('ok', !!message && ok);
    el.classList.toggle('error', !!message && !ok);
  }

  // dialogs: any [data-close] button closes its dialog
  document.addEventListener('click', (e) => {
    const btn = e.target.closest?.('[data-close]');
    if (btn) btn.closest('dialog')?.close();
  });

  // ------------------------------------------------------ user + settings
  const userAvatarEl = $('#user-avatar');
  const userNameEl = $('#user-name');
  const userDot = $('#user-dot');
  const statusBtn = $('#status-btn');
  const statusMenu = $('#status-menu');
  let me = null;
  let refreshPresence = () => {};

  function paintStatus() {
    userDot.className = 'sdot ' + me.status;
    const label = t('status.' + me.status);
    statusBtn.title = me.status_text ? `${label} - ${me.status_text}` : label;
    for (const opt of statusMenu.querySelectorAll('.status-opt')) {
      opt.setAttribute('aria-pressed', String(opt.dataset.status === me.status));
    }
  }

  const mePromise = api('/me').then((u) => {
    me = u;
    userNameEl.textContent = u.display_name;
    fillAvatar(userAvatarEl, u.display_name, u.avatar_url);
    paintStatus();
    return u;
  });

  function refreshAvatars() {
    fillAvatar(userAvatarEl, me.display_name, me.avatar_url);
    fillAvatar($('#settings-avatar'), me.display_name, me.avatar_url);
  }

  // ---- language buttons in the top bar
  for (const btn of document.querySelectorAll('#lang-switch [data-lang]')) {
    btn.addEventListener('click', async () => {
      if (btn.getAttribute('aria-pressed') === 'true') return;
      try { await api('/me/language', { method: 'PUT', body: { language: btn.dataset.lang } }); location.reload(); }
      catch (err) { alert(err.message); }
    });
  }

  // ---- status menu (Online / Idle / Do Not Disturb / Invisible + custom text)
  function toggleStatusMenu(open) {
    statusMenu.hidden = !open;
    statusBtn.setAttribute('aria-expanded', String(open));
    if (open && me) { $('#status-text').value = me.status_text; paintStatus(); }
  }
  statusBtn.addEventListener('click', () => toggleStatusMenu(statusMenu.hidden));
  document.addEventListener('click', (e) => {
    if (!statusMenu.hidden && !statusMenu.contains(e.target) && !statusBtn.contains(e.target)) toggleStatusMenu(false);
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !statusMenu.hidden) { toggleStatusMenu(false); statusBtn.focus(); }
  });

  async function saveStatus(patch) {
    try {
      const r = await api('/me/status', { method: 'PUT', body: patch });
      me.status = r.status;
      me.status_text = r.status_text;
      $('#status-text').value = r.status_text;
      paintStatus();
      refreshPresence();
    } catch (err) { alert(err.message); }
  }
  for (const opt of statusMenu.querySelectorAll('.status-opt')) {
    opt.addEventListener('click', () => saveStatus({ status: opt.dataset.status }));
  }
  $('#status-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    await saveStatus({ text: $('#status-text').value });
    toggleStatusMenu(false);
  });
  $('#status-clear').addEventListener('click', () => saveStatus({ text: '' }));

  // ---- settings dialog
  const dlg = $('#settings-dialog');
  $('#open-settings').addEventListener('click', async () => {
    await mePromise;
    $('#name-input').value = me.display_name;
    for (const id of ['avatar', 'name', 'password']) setStatus($(`#${id}-status`), '');
    $('#password-form').reset();
    $('#avatar-form').reset();
    refreshAvatars();
    dlg.showModal();
  });

  $('#avatar-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const status = $('#avatar-status');
    const file = $('#avatar-file').files[0];
    if (!file) return;
    const ext = file.name.split('.').pop().toLowerCase();
    if (!['png', 'jpg', 'jpeg', 'gif'].includes(ext)) return setStatus(status, t('err.avatar_type'));
    if (file.size > 2 * 1024 * 1024) return setStatus(status, t('err.avatar_big'));
    const form = new FormData();
    form.append('file', file);
    try {
      const r = await api('/me/avatar', { method: 'POST', form });
      me.avatar_url = r.avatar_url;
      refreshAvatars();
      e.target.reset();
      setStatus(status, t('set.picture_ok'), true);
      refreshPresence();
    } catch (err) { setStatus(status, err.message); }
  });

  $('#avatar-remove').addEventListener('click', async () => {
    try {
      await api('/me/avatar', { method: 'DELETE' });
      me.avatar_url = null;
      refreshAvatars();
      setStatus($('#avatar-status'), t('set.picture_removed'), true);
      refreshPresence();
    } catch (err) { setStatus($('#avatar-status'), err.message); }
  });

  $('#name-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const status = $('#name-status');
    try {
      const r = await api('/me', { method: 'PATCH', body: { display_name: $('#name-input').value } });
      me.display_name = r.display_name;
      userNameEl.textContent = r.display_name;
      $('#name-input').value = r.display_name;
      refreshAvatars();
      setStatus(status, t('set.nick_saved'), true);
      refreshPresence();
    } catch (err) { setStatus(status, err.message); }
  });

  $('#password-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const status = $('#password-status');
    const next = $('#pw-new').value;
    if (next !== $('#pw-confirm').value) return setStatus(status, t('set.pw_mismatch'));
    try {
      await api('/me/password', { method: 'POST', body: { current: $('#pw-current').value, new: next } });
      e.target.reset();
      setStatus(status, t('set.pw_ok'), true);
    } catch (err) { setStatus(status, err.message); }
  });

  // ------------------------------------------- online bookmark (presence)
  const Presence = (() => {
    const IDLE_AFTER = 2 * 60 * 1000;      // no mouse/keyboard for 2 min -> "idling"
    const BEAT_EVERY = 20 * 1000;
    const root = $('#presence');
    const countEl = $('#presence-count');
    const listEl = $('#presence-list');
    let activity = 'browsing';
    let subject = null;
    let lastInput = Date.now();

    const current = () => (document.hidden || Date.now() - lastInput > IDLE_AFTER ? 'idle' : activity);

    // dot colour: what the person chose, but "Online" turns yellow when they are away from the keyboard
    const dotFor = (u) => (u.status === 'online' && u.activity === 'idle' ? 'idle' : u.status);

    function render(data) {
      countEl.textContent = data.count;
      listEl.replaceChildren(...data.users.map((u) => h('li', {},
        avatarWithDot(u.name, u.avatar_url, dotFor(u), 'small'),
        h('div', { class: 'p-text' },
          h('div', { class: 'p-name' }, u.name, u.me ? h('span', { class: 'muted' }, ' ' + t('presence.you')) : null),
          u.status_text ? h('div', { class: 'p-status' }, u.status_text) : null,
          h('div', { class: 'p-meta' },
            u.status === 'invisible'
              ? h('span', { class: 'muted' }, t('presence.hidden'))
              : h('span', { class: 'chip ' + u.activity }, t('act.' + u.activity)),
            u.status === 'dnd' ? h('span', { class: 'chip dnd' }, t('status.dnd')) : null,
            u.status !== 'invisible' && u.subject && (u.activity === 'studying' || u.activity === 'practising')
              ? h('span', { class: 'p-sub' }, u.subject) : null)))));
    }

    async function beat() {
      try { render(await api('/presence', { method: 'POST', body: { activity: current(), subject_id: subject } })); }
      catch { /* offline or signed out - ignore */ }
    }

    function set(newActivity, subjectId = null) {
      activity = newActivity;
      subject = subjectId;
      beat();
    }

    for (const ev of ['mousemove', 'keydown', 'pointerdown', 'scroll', 'touchstart']) {
      addEventListener(ev, () => {
        const wasIdle = current() === 'idle';
        lastInput = Date.now();
        if (wasIdle) beat();
      }, { passive: true });
    }
    document.addEventListener('visibilitychange', beat);
    setInterval(beat, BEAT_EVERY);

    const tab = $('#presence-tab');
    tab.addEventListener('click', async () => {
      const open = root.classList.toggle('open');
      tab.setAttribute('aria-expanded', String(open));
      $('#presence-panel').setAttribute('aria-hidden', String(!open));
      if (open) { try { render(await api('/presence')); } catch { /* ignore */ } }
    });

    beat();
    return { set, refresh: beat };
  })();
  refreshPresence = Presence.refresh;

  window.App = {
    api, ApiError, h, $, t, tn, lang, avatar, avatarWithDot, fillAvatar, timeAgo, setStatus, Presence,
    getMe: () => mePromise,
  };
})();
