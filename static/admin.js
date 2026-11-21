/* Admin page: manage users and edit subject JSON files. */
(() => {
  'use strict';
  const { api, h, $, t, tn, avatar, timeAgo, setStatus, getMe } = window.App;

  let myId = null;
  let users = [];
  let subjects = [];
  let editingUser = null;     // null = creating
  let editingSubject = null;

  const ALPHABET = 'abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  function generatePassword(len = 10) {
    const bytes = crypto.getRandomValues(new Uint32Array(len));
    return Array.from(bytes, (b) => ALPHABET[b % ALPHABET.length]).join('');
  }

  // ----------------------------------------------------------------- tabs
  for (const btn of document.querySelectorAll('.tab')) {
    btn.addEventListener('click', () => {
      for (const b of document.querySelectorAll('.tab')) b.classList.toggle('active', b === btn);
      for (const sec of ['users', 'subjects']) $(`#tab-${sec}`).hidden = sec !== btn.dataset.tab;
    });
  }

  // ---------------------------------------------------------------- users
  const chip = (text, cls = '') => h('span', { class: ('chip ' + cls).trim() }, text);

  function userRow(u) {
    const self = u.id === myId;
    return h('tr', {},
      h('td', {}, h('div', { class: 'who' },
        avatar(u.display_name, u.avatar_url, 'small'),
        h('div', {}, h('strong', {}, u.display_name), h('div', { class: 'muted small-text' }, '@' + u.username)))),
      h('td', {}, u.is_admin ? chip(t('admin.role_admin'), 'studying') : t('admin.role_user')),
      h('td', {},
        u.is_banned ? chip(t('admin.banned'), 'banned') : chip(t('admin.active'), 'ok'),
        u.must_change_password ? chip(t('admin.must_change'), 'practising') : null),
      h('td', { class: 'muted' }, u.online ? t('admin.online_now') : u.last_seen ? timeAgo(u.last_seen) : t('admin.never')),
      h('td', { class: 'actions' },
        h('button', { type: 'button', class: 'btn small', onclick: () => openUserDialog(u) }, t('admin.edit')),
        h('button', { type: 'button', class: 'btn small', onclick: () => resetPassword(u) }, t('admin.reset')),
        self ? null : h('button', {
          type: 'button', class: 'btn small ' + (u.is_banned ? '' : 'danger'),
          onclick: () => toggleBan(u),
        }, u.is_banned ? t('admin.unban') : t('admin.ban'))));
  }

  function drawUsers() {
    $('#users-summary').textContent = t('admin.summary', {
      users: tn('n.user', users.length), online: users.filter((u) => u.online).length,
    });
    $('#users-body').replaceChildren(...users.map(userRow));
  }

  async function loadUsers() {
    users = await api('/admin/users');
    drawUsers();
  }

  async function toggleBan(u) {
    const ban = !u.is_banned;
    if (!confirm(t(ban ? 'admin.ban_confirm' : 'admin.unban_confirm', { name: u.username }))) return;
    try { await api(`/admin/users/${u.id}`, { method: 'PATCH', body: { is_banned: ban } }); await loadUsers(); }
    catch (err) { alert(err.message); }
  }

  const passDlg = $('#password-dialog');
  function showPassword(username, password) {
    $('#pd-text').textContent = t('admin.temp_text', { name: username });
    $('#pd-password').textContent = password;
    $('#pd-copy').textContent = t('admin.copy');
    passDlg.showModal();
  }
  $('#pd-copy').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText($('#pd-password').textContent); $('#pd-copy').textContent = t('admin.copied'); }
    catch { $('#pd-copy').textContent = t('admin.copy_fail'); }
  });

  async function resetPassword(u) {
    if (!confirm(t('admin.reset_confirm', { name: u.username }))) return;
    try {
      const r = await api(`/admin/users/${u.id}/reset-password`, { method: 'POST', body: {} });
      showPassword(u.username, r.password);
      await loadUsers();
    } catch (err) { alert(err.message); }
  }

  const userDlg = $('#user-dialog');
  function openUserDialog(u) {
    editingUser = u;
    $('#user-dialog-title').textContent = u ? t('admin.edit_user', { name: u.username }) : t('admin.new_user_title');
    $('#uf-username').value = u ? u.username : '';
    $('#uf-name').value = u ? u.display_name : '';
    $('#uf-admin').checked = u ? u.is_admin : false;
    $('#uf-admin').disabled = !!u && u.id === myId;      // don't lock yourself out
    $('#uf-password-row').hidden = !!u;
    $('#uf-password').required = !u;
    $('#uf-password').value = u ? '' : generatePassword();
    setStatus($('#user-form-error'), '');
    userDlg.showModal();
  }

  $('#new-user').addEventListener('click', () => openUserDialog(null));
  $('#uf-generate').addEventListener('click', () => { $('#uf-password').value = generatePassword(); });

  $('#user-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const err = $('#user-form-error');
    const body = {
      username: $('#uf-username').value.trim(),
      display_name: $('#uf-name').value.trim() || $('#uf-username').value.trim(),
    };
    if (!$('#uf-admin').disabled) body.is_admin = $('#uf-admin').checked;
    try {
      if (editingUser) {
        await api(`/admin/users/${editingUser.id}`, { method: 'PATCH', body });
      } else {
        body.password = $('#uf-password').value;
        await api('/admin/users', { method: 'POST', body });
      }
      userDlg.close();
      await loadUsers();
      if (!editingUser) showPassword(body.username, body.password);
    } catch (ex) { setStatus(err, ex.message); }
  });

  // ------------------------------------------------------------- subjects
  function subjectRow(s) {
    return h('tr', {},
      h('td', {}, s.errors
        ? h('div', {}, h('strong', {}, s.id), h('div', { class: 'status error small-text' }, '⚠ ' + s.errors[0] + (s.errors.length > 1 ? ` (+${s.errors.length - 1})` : '')))
        : h('strong', {}, s.title)),
      h('td', {}, h('code', {}, s.id + '.json')),
      h('td', {}, s.errors ? '—' : String(s.count)),
      h('td', { class: 'actions' }, h('button', { type: 'button', class: 'btn small', onclick: () => openSubject(s) }, t('admin.edit_json'))));
  }

  async function loadSubjects() {
    subjects = await api('/admin/subjects');
    $('#subjects-body').replaceChildren(...(subjects.length
      ? subjects.map(subjectRow)
      : [h('tr', {}, h('td', { colspan: 4, class: 'muted' }, t('admin.no_subjects')))]));
  }

  const subjDlg = $('#subject-dialog');
  async function openSubject(s) {
    try {
      const raw = await api(`/admin/subjects/${encodeURIComponent(s.id)}/raw`);
      editingSubject = s.id;
      $('#sd-title').textContent = t('admin.edit_subject', { name: s.id + '.json' });
      $('#sd-text').value = raw.text;
      $('#sd-problems').replaceChildren();
      subjDlg.showModal();
    } catch (err) { alert(err.message); }
  }

  $('#subject-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const problems = $('#sd-problems');
    try {
      await api(`/admin/subjects/${encodeURIComponent(editingSubject)}`, { method: 'PUT', body: { text: $('#sd-text').value } });
      subjDlg.close();
      await loadSubjects();
    } catch (err) {
      const list = err.data?.problems?.length ? err.data.problems : [err.message];
      problems.replaceChildren(...list.map((p) => h('li', {}, p)));
    }
  });

  const newDlg = $('#newsubject-dialog');
  let idTouched = false;
  $('#new-subject').addEventListener('click', () => {
    $('#newsubject-form').reset();
    idTouched = false;
    setStatus($('#ns-error'), '');
    newDlg.showModal();
  });
  $('#ns-id').addEventListener('input', () => { idTouched = true; });
  $('#ns-title').addEventListener('input', (e) => {
    if (idTouched) return;
    $('#ns-id').value = e.target.value.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')
      .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40);
  });
  $('#newsubject-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      const r = await api('/admin/subjects', { method: 'POST', body: { id: $('#ns-id').value, title: $('#ns-title').value } });
      newDlg.close();
      await loadSubjects();
      openSubject({ id: r.id });
    } catch (err) { setStatus($('#ns-error'), err.message); }
  });

  // ----------------------------------------------------------------- init
  (async () => {
    myId = (await getMe()).id;
    await Promise.all([loadUsers(), loadSubjects()]);
  })();
})();
