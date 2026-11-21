/* Main app: subject list, Flagged, subject page, Study mode, Practise mode, per-card discussion. */
(() => {
  'use strict';
  const { api, h, $, t, tn, lang, avatar, timeAgo, setStatus, Presence } = window.App;

  const main = $('#main');
  const listEl = $('#subject-list');
  const toggle = $('#sidebar-toggle');
  const enc = encodeURIComponent;
  const narrow = () => matchMedia('(max-width: 800px)').matches;

  let subjectsList = [];
  const flags = new Set();                 // "subjectId/cardId" of the cards this user flagged
  let viewToken = 0;                       // bumped on every navigation so late responses are ignored
  let viewAbort = new AbortController();   // listeners registered with its signal die on navigation

  // ---------------------------------------------------------- small utils
  function shuffle(arr) {
    const a = arr.slice();
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  }

  const pre = (text) => h('span', { class: 'pre' }, text);
  const cardSid = (subject, card) => card.subject_id || subject.id;     // cards in "Flagged" come from many subjects
  const base = (subject) => (subject.flagged ? '#/flagged' : '#/s/' + enc(subject.id));
  const presenceId = (subject) => (subject.flagged ? null : subject.id);

  function progressBar(done, total) {
    const bar = h('div', { class: 'bar' });
    bar.style.width = `${total ? Math.round((done / total) * 100) : 0}%`;
    return h('div', { class: 'progress', role: 'progressbar', 'aria-valuemin': 0, 'aria-valuemax': total, 'aria-valuenow': done }, bar);
  }

  function explanationEl(card) {
    return card.explanation
      ? h('div', { class: 'explanation' }, h('div', { class: 'label' }, t('q.explanation')), pre(card.explanation))
      : null;
  }

  function show(...nodes) {
    main.replaceChildren(h('div', { class: 'page' }, ...nodes));
  }

  // ---------------------------------------------------------------- flags
  function updateFlaggedCount() {
    $('#flagged-count').textContent = flags.size ? tn('n.card', flags.size) : '';
  }

  function flagButton(subject, card) {
    const sid = cardSid(subject, card);
    const key = `${sid}/${card.id}`;
    const btn = h('button', {
      type: 'button', class: 'flag-btn',
      onclick: async () => {
        const on = flags.has(key);
        try {
          await api(`/subjects/${enc(sid)}/cards/${enc(card.id)}/flag`, { method: on ? 'DELETE' : 'PUT' });
          if (on) flags.delete(key); else flags.add(key);
          paint();
          updateFlaggedCount();
        } catch (err) { alert(err.message); }
      },
    });
    function paint() {
      const on = flags.has(key);
      btn.setAttribute('aria-pressed', String(on));
      btn.title = t(on ? 'flag.tip_on' : 'flag.tip_off');
      btn.textContent = '⚑ ' + t(on ? 'flag.flagged' : 'flag.flag');
    }
    paint();
    return btn;
  }

  // the small header line of a card: "Card 3 of 12 · from <subject>" + flag button
  function cardHead(subject, card, label) {
    return h('div', { class: 'qhead' },
      h('div', { class: 'qmeta' }, label, card.subject_title ? ` · ${card.subject_title}` : ''),
      flagButton(subject, card));
  }

  // -------------------------------------------------------------- sidebar
  function setSidebar(open, save = true) {
    document.body.classList.toggle('sidebar-closed', !open);
    toggle.setAttribute('aria-expanded', String(open));
    if (save) { try { localStorage.setItem('sidebar', open ? '1' : '0'); } catch { /* private mode */ } }
  }
  (() => {
    let saved = null;
    try { saved = localStorage.getItem('sidebar'); } catch { /* ignore */ }
    setSidebar(narrow() ? false : saved !== '0', false);
  })();
  toggle.addEventListener('click', () => setSidebar(document.body.classList.contains('sidebar-closed')));
  $('#flagged-link').addEventListener('click', () => { if (narrow()) setSidebar(false, false); });

  function renderSidebar(activeId) {
    $('#flagged-link').classList.toggle('active', activeId === 'flagged');
    updateFlaggedCount();
    if (!subjectsList.length) {
      listEl.replaceChildren(h('p', { class: 'muted pad' }, t('side.none')));
      return;
    }
    listEl.replaceChildren(...subjectsList.map((s) => h('a', {
      href: '#/s/' + enc(s.id),
      class: 'subject-link' + (s.id === activeId ? ' active' : ''),
      'aria-current': s.id === activeId ? 'page' : null,
      onclick: () => { if (narrow()) setSidebar(false, false); },
    }, h('span', { class: 's-title' }, s.title), h('small', {}, tn('n.card', s.count)))));
  }

  // ---------------------------------------------------------------- views
  function pictureOfTheDay() {
    const img = h('img', { alt: t('potd.title') });
    const fig = h('figure', { class: 'potd' }, img,
      h('figcaption', {}, t('potd.title') + ' · ' +
        new Date().toLocaleDateString(lang, { weekday: 'long', day: 'numeric', month: 'long' })));
    fig.hidden = true;                                   // stays hidden until we know there is a picture
    api('/potd').then((r) => {
      if (!r.url) return;
      img.addEventListener('load', () => { fig.hidden = false; });
      img.src = r.url;
    }).catch(() => {});
    return fig;
  }

  function homeView() {
    Presence.set('browsing');
    const tiles = [];
    if (flags.size) {
      tiles.push(h('a', { class: 'tile', href: '#/flagged' },
        h('strong', {}, '⚑ ' + t('flagged.title')), h('span', { class: 'muted' }, t('flagged.desc')), h('small', {}, tn('n.card', flags.size))));
    }
    for (const s of subjectsList) {
      tiles.push(h('a', { class: 'tile', href: '#/s/' + enc(s.id) },
        h('strong', {}, s.title),
        s.description ? h('span', { class: 'muted' }, s.description) : null,
        h('small', {}, tn('n.card', s.count))));
    }
    show(
      pictureOfTheDay(),
      h('h1', {}, t('home.title')),
      subjectsList.length
        ? h('p', { class: 'muted' }, t('home.hint'))
        : h('p', { class: 'muted' }, t('home.empty')),
      h('div', { class: 'tiles' }, tiles));
  }

  function notFoundView() {
    Presence.set('browsing');
    show(h('h1', {}, t('subject.notfound')), h('p', {}, h('a', { href: '#/' }, t('subject.back_all'))));
  }

  function overviewView(subject) {
    Presence.set('browsing');
    const n = subject.cards.length;
    const flaggedList = subject.flagged && n
      ? h('section', { class: 'flag-list' },
        h('h2', {}, t('flagged.list')),
        subject.cards.map((card) => h('div', { class: 'flag-row' },
          h('div', { class: 'grow' },
            h('div', { class: 'qmeta' }, card.subject_title),
            h('div', { class: 'clip' }, card.question)),
          flagButton(subject, card))))
      : null;

    show(
      h('h1', {}, (subject.flagged ? '⚑ ' : '') + subject.title),
      subject.description ? h('p', { class: 'lead' }, subject.description) : null,
      h('p', { class: 'muted' }, tn('n.card', n)),
      n === 0
        ? h('p', {}, subject.flagged ? t('flagged.empty') : t('subject.empty'))
        : h('div', { class: 'modes' },
          h('a', { class: 'mode-card', href: `${base(subject)}/study` },
            h('h2', {}, '📖 ' + t('mode.study')),
            h('p', {}, t('mode.study_desc')),
            h('span', { class: 'btn primary' }, t('mode.study_start'))),
          h('a', { class: 'mode-card', href: `${base(subject)}/practise` },
            h('h2', {}, '📝 ' + t('mode.practise')),
            h('p', {}, t('mode.practise_desc')),
            h('span', { class: 'btn primary' }, t('mode.practise_start')))),
      flaggedList);
  }

  // ---------------------------------------------------------------- Study
  function answerBlock(card) {
    if (card.type === 'choice') {
      return h('div', {},
        h('ul', { class: 'options' }, card.options.map((text, i) => {
          const ok = card.answer.includes(i);
          return h('li', { class: 'opt' + (ok ? ' correct' : '') }, h('span', { class: 'mark' }, ok ? '✓' : ''), pre(text));
        })),
        card.answer.length > 1 ? h('p', { class: 'hint' }, t('q.more_correct')) : null,
        explanationEl(card));
    }
    return h('div', {},
      h('div', { class: 'answer-box' }, h('div', { class: 'label' }, t('q.answer')), pre(card.answer)),
      explanationEl(card));
  }

  function studyView(subject) {
    Presence.set('studying', presenceId(subject));
    let order = subject.cards.map((_, i) => i);
    let pos = 0;
    const body = h('div');

    const shuffleBox = h('input', {
      type: 'checkbox',
      onchange: (e) => { order = e.target.checked ? shuffle(order) : order.slice().sort((a, b) => a - b); pos = 0; draw(); },
    });

    const go = (d) => { const p = pos + d; if (p >= 0 && p < order.length) { pos = p; draw(); window.scrollTo(0, 0); } };

    function draw() {
      const card = subject.cards[order[pos]];
      body.replaceChildren(
        progressBar(pos + 1, order.length),
        h('article', { class: 'qcard' },
          cardHead(subject, card, t('study.card_of', { i: pos + 1, n: order.length })),
          h('h2', { class: 'question pre' }, card.question),
          answerBlock(card)),
        h('div', { class: 'nav-row' },
          h('button', { type: 'button', class: 'btn', disabled: pos === 0, onclick: () => go(-1) }, t('nav.prev')),
          h('button', { type: 'button', class: 'btn primary', disabled: pos === order.length - 1, onclick: () => go(1) }, t('nav.next'))),
        discussion(cardSid(subject, card), card.id, false));
    }

    document.addEventListener('keydown', (e) => {
      if (/^(TEXTAREA|INPUT|SELECT)$/.test(document.activeElement?.tagName) || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === 'ArrowLeft') go(-1);
      if (e.key === 'ArrowRight') go(1);
    }, { signal: viewAbort.signal });

    show(
      h('div', { class: 'view-head' },
        h('a', { class: 'back', href: base(subject) }, '← ' + subject.title),
        h('span', { class: 'badge' }, t('mode.study')),
        h('label', { class: 'inline-label push' }, shuffleBox, ' ' + t('study.shuffle'))),
      body);
    draw();
  }

  // ------------------------------------------------------------- Practise
  const sameSet = (a, b) => a.length === b.length && a.every((x) => b.includes(x));

  function practiseView(subject) {
    Presence.set('practising', presenceId(subject));
    const order = shuffle(subject.cards.map((_, i) => i));      // always every card of the subject
    const answers = order.map(() => null);   // choice: [selected option numbers]; open: text
    let pos = 0;
    const body = h('div');

    const answered = (i) => {
      const a = answers[i];
      return Array.isArray(a) ? a.length > 0 : typeof a === 'string' && a.trim() !== '';
    };

    function finish() {
      const missing = order.filter((_, i) => !answered(i)).length;
      if (missing && !confirm(t('prac.unanswered', { q: tn('n.question', missing) }))) return;
      results();
    }

    function question() {
      const card = subject.cards[order[pos]];
      let input;
      if (card.type === 'choice') {
        const multi = card.answer.length > 1;
        const chosen = new Set(answers[pos] || []);
        const list = h('ul', { class: 'options selectable' }, card.options.map((text, i) => h('li', {},
          h('label', { class: 'opt' },
            h('input', {
              type: multi ? 'checkbox' : 'radio', name: 'opt', value: i, checked: chosen.has(i),
              onchange: () => { answers[pos] = [...list.querySelectorAll('input:checked')].map((x) => +x.value); },
            }),
            pre(text)))));
        input = h('div', {}, list, multi ? h('p', { class: 'hint' }, t('q.select_all')) : null);
      } else {
        input = h('textarea', {
          class: 'answer-input', rows: 6, placeholder: t('prac.placeholder'), 'aria-label': t('prac.your_answer'),
          oninput: (e) => { answers[pos] = e.target.value; },
        }, answers[pos] || '');
      }
      const last = pos === order.length - 1;
      body.replaceChildren(
        progressBar(pos + 1, order.length),
        h('article', { class: 'qcard' },
          cardHead(subject, card, t('prac.question_of', { i: pos + 1, n: order.length })),
          h('h2', { class: 'question pre' }, card.question),
          input),
        h('div', { class: 'nav-row' },
          h('button', { type: 'button', class: 'btn', disabled: pos === 0, onclick: () => { pos--; question(); window.scrollTo(0, 0); } }, t('nav.prev')),
          last
            ? h('button', { type: 'button', class: 'btn primary', onclick: finish }, t('prac.finish'))
            : h('button', { type: 'button', class: 'btn primary', onclick: () => { pos++; question(); window.scrollTo(0, 0); } }, t('nav.next'))),
        discussion(cardSid(subject, card), card.id, true));
    }

    function results() {
      const grades = order.map((ci, i) => {
        const card = subject.cards[ci];
        return card.type === 'choice' ? sameSet(answers[i] || [], card.answer) : null;   // open: self-graded
      });
      const scoreEl = h('div', { class: 'score' });
      const pctEl = h('div', { class: 'muted' });
      const hintEl = h('p', { class: 'hint' });
      const items = [];

      function refresh() {
        const right = grades.filter((g) => g === true).length;
        scoreEl.textContent = `${right} / ${order.length}`;
        pctEl.textContent = `${Math.round((right / order.length) * 100)} %`;
        const unmarked = grades.filter((g) => g === null).length;
        hintEl.textContent = unmarked ? t('prac.to_mark', { q: tn('n.open', unmarked) }) : '';
        items.forEach(({ el, buttons }, i) => {
          el.className = 'review-item ' + (grades[i] === true ? 'right' : grades[i] === false ? 'wrong' : 'unmarked');
          buttons?.forEach(([btn, value]) => btn.setAttribute('aria-pressed', String(grades[i] === value)));
        });
      }

      order.forEach((ci, i) => {
        const card = subject.cards[ci];
        let detail;
        let buttons = null;
        if (card.type === 'choice') {
          const mine = answers[i] || [];
          detail = h('div', {},
            h('ul', { class: 'options' }, card.options.map((text, k) => {
              const ok = card.answer.includes(k);
              const picked = mine.includes(k);
              return h('li', { class: 'opt' + (ok ? ' correct' : '') + (picked && !ok ? ' wrong' : '') },
                h('span', { class: 'mark' }, ok ? '✓' : picked ? '✗' : ''),
                pre(text),
                picked ? h('span', { class: 'you' }, t('prac.you_tag')) : null);
            })),
            mine.length ? null : h('p', { class: 'hint' }, t('prac.not_answered')));
        } else {
          const btnRight = h('button', { type: 'button', class: 'btn small', onclick: () => { grades[i] = true; refresh(); } }, t('prac.got_it'));
          const btnWrong = h('button', { type: 'button', class: 'btn small', onclick: () => { grades[i] = false; refresh(); } }, t('prac.missed'));
          buttons = [[btnRight, true], [btnWrong, false]];
          detail = h('div', {},
            h('div', { class: 'answer-box mine' }, h('div', { class: 'label' }, t('prac.your_answer')),
              answered(i) ? pre(answers[i]) : h('span', { class: 'muted' }, t('prac.no_answer'))),
            h('div', { class: 'answer-box' }, h('div', { class: 'label' }, t('prac.model')), pre(card.answer)),
            h('div', { class: 'row' }, btnRight, btnWrong));
        }
        const el = h('article', { class: 'review-item' },
          cardHead(subject, card, t('prac.question', { i: i + 1 })),
          h('h3', { class: 'question pre' }, card.question),
          detail,
          explanationEl(card));
        items.push({ el, buttons });
      });

      body.replaceChildren(
        h('section', { class: 'result-head' }, h('h2', {}, t('prac.result')), scoreEl, pctEl, hintEl),
        h('div', { class: 'row' },
          h('button', { type: 'button', class: 'btn primary', onclick: () => practiseView(subject) }, t('prac.retry')),
          h('a', { class: 'btn', href: `${base(subject)}/study` }, t('prac.study_these')),
          h('a', { class: 'btn ghost', href: base(subject) }, t('prac.back'))),
        h('div', { class: 'review' }, items.map((x) => x.el)));
      refresh();
      window.scrollTo(0, 0);
    }

    show(
      h('div', { class: 'view-head' },
        h('a', { class: 'back', href: base(subject) }, '← ' + subject.title),
        h('span', { class: 'badge practise' }, t('mode.practise')),
        h('button', { type: 'button', class: 'btn small push', onclick: finish }, t('prac.finish_now'))),
      body);
    question();
  }

  // ----------------------------------------------------------- Discussion
  function discussion(subjectId, cardId, collapsed) {
    const url = `/subjects/${enc(subjectId)}/cards/${enc(cardId)}/comments`;
    let comments = [];
    let loaded = false;

    const heading = h('h3', {}, t('disc.title', { n: '…' }));
    const thread = h('div', { class: 'thread' });
    const status = h('p', { class: 'status', role: 'alert' });
    const box = h('textarea', { rows: 3, maxlength: 1000, placeholder: t('disc.placeholder'), 'aria-label': t('disc.placeholder') });

    async function send(text, parentId, statusEl) {
      try {
        const c = await api(url, { method: 'POST', body: { body: text, parent_id: parentId } });
        comments.push(c);
        drawThread();
        return true;
      } catch (err) {
        setStatus(statusEl, err.message);
        return false;
      }
    }

    const postBtn = h('button', {
      type: 'button', class: 'btn small primary',
      onclick: async () => {
        setStatus(status, '');
        if (!box.value.trim()) return setStatus(status, t('err.comment_empty'));
        if (await send(box.value, null, status)) box.value = '';
      },
    }, t('disc.post'));

    function node(c, depth, kids) {
      const replyArea = h('div', { class: 'reply-area' });
      const children = kids.get(c.id) || [];

      function toggleReply() {
        if (replyArea.childNodes.length) { replyArea.replaceChildren(); return; }
        const ta = h('textarea', { rows: 2, maxlength: 1000, placeholder: t('disc.reply_placeholder'), 'aria-label': t('disc.reply') });
        const st = h('p', { class: 'status', role: 'alert' });
        replyArea.append(ta, h('div', { class: 'row' },
          h('button', {
            type: 'button', class: 'btn small primary',
            onclick: async () => {
              if (!ta.value.trim()) return setStatus(st, t('err.comment_empty'));
              await send(ta.value, c.id, st);      // success redraws the whole thread
            },
          }, t('disc.reply')),
          h('button', { type: 'button', class: 'btn small ghost', onclick: () => replyArea.replaceChildren() }, t('disc.cancel'))), st);
        ta.focus();
      }

      async function remove() {
        if (!confirm(t('disc.delete_confirm'))) return;
        try {
          await api(`/comments/${c.id}`, { method: 'DELETE' });
          Object.assign(c, { deleted: true, body: '', author: null, can_delete: false });
          drawThread();
        } catch (err) { alert(err.message); }
      }

      return h('div', { class: 'comment' + (depth >= 4 ? ' flat' : '') },
        c.deleted ? avatar('?', null, 'small ghosted') : avatar(c.author.name, c.author.avatar_url, 'small'),
        h('div', { class: 'c-main' },
          c.deleted
            ? h('div', { class: 'c-head muted' }, t('disc.deleted'))
            : h('div', { class: 'c-head' }, h('strong', {}, c.author.name), h('span', { class: 'muted' }, ' · ' + timeAgo(c.created_at))),
          c.deleted ? null : h('div', { class: 'c-body pre' }, c.body),
          c.deleted ? null : h('div', { class: 'c-actions' },
            h('button', { type: 'button', class: 'link', onclick: toggleReply }, t('disc.reply')),
            c.can_delete ? h('button', { type: 'button', class: 'link danger', onclick: remove }, t('disc.delete')) : null),
          replyArea,
          children.length ? h('div', { class: 'c-children' }, children.map((k) => node(k, depth + 1, kids))) : null));
    }

    function drawThread() {
      const kids = new Map();
      for (const c of comments) {
        const key = c.parent_id ?? 0;
        if (!kids.has(key)) kids.set(key, []);
        kids.get(key).push(c);
      }
      const roots = (kids.get(0) || []).slice().reverse();          // newest first, like a feed
      heading.textContent = t('disc.title', { n: comments.filter((c) => !c.deleted).length });
      thread.replaceChildren(...(roots.length
        ? roots.map((c) => node(c, 0, kids))
        : [h('p', { class: 'muted' }, t('disc.none'))]));
    }

    async function load() {
      try { comments = await api(url); loaded = true; drawThread(); }
      catch (err) { thread.replaceChildren(h('p', { class: 'status error' }, err.message)); }
    }

    const content = h('div', { class: 'd-content' },
      heading,
      h('div', { class: 'composer' }, box, h('div', { class: 'row' }, postBtn,
        h('button', { type: 'button', class: 'btn small ghost', onclick: load }, t('disc.refresh')))),
      status, thread);
    const root = h('section', { class: 'discussion' });

    if (collapsed) {
      content.hidden = true;
      const btn = h('button', {
        type: 'button', class: 'btn small ghost', 'aria-expanded': 'false',
        onclick: () => {
          const open = content.hidden;
          content.hidden = !open;
          btn.setAttribute('aria-expanded', String(open));
          btn.textContent = open ? t('disc.hide') : t('disc.show');
          if (open && !loaded) load();
        },
      }, t('disc.show'));
      root.append(btn, content);
    } else {
      root.append(content);
      load();
    }
    return root;
  }

  // --------------------------------------------------------------- router
  async function route() {
    const token = ++viewToken;
    viewAbort.abort();
    viewAbort = new AbortController();
    const parts = location.hash.replace(/^#\/?/, '').split('/').filter(Boolean).map(decodeURIComponent);

    let subject = null;
    let mode = null;
    if (parts[0] === 's' && parts[1]) {
      renderSidebar(parts[1]);
      try { subject = await api(`/subjects/${enc(parts[1])}`); }
      catch { if (token === viewToken) notFoundView(); return; }
      mode = parts[2];
    } else if (parts[0] === 'flagged') {
      renderSidebar('flagged');
      try { subject = await api('/flagged'); }
      catch { if (token === viewToken) notFoundView(); return; }
      mode = parts[1];
      // keep the local flag set in sync with what the server has
      flags.clear();
      for (const c of subject.cards) flags.add(`${c.subject_id}/${c.id}`);
      updateFlaggedCount();
    }
    if (token !== viewToken) return;
    window.scrollTo(0, 0);

    if (!subject) { renderSidebar(null); homeView(); return; }
    if (subject.flagged && !subject.cards.length) mode = null;     // nothing to study yet
    if (mode === 'study') studyView(subject);
    else if (mode === 'practise') practiseView(subject);
    else overviewView(subject);
  }

  async function init() {
    const [subjects, flagList] = await Promise.all([
      api('/subjects').catch(() => []),
      api('/flags').catch(() => []),
    ]);
    subjectsList = subjects;
    for (const f of flagList) flags.add(`${f.subject_id}/${f.card_id}`);
    window.addEventListener('hashchange', route);
    route();
  }
  init();
})();
