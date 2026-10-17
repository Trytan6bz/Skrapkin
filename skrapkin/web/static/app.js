(() => {
  'use strict';

  // ---- helpers ---------------------------------------------------------------------------------
  const $ = (id) => document.getElementById(id);
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // Build DOM nodes. Strings become text nodes, never HTML: scraped data is untrusted.
  function h(tag, props = {}, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (k === 'class') el.className = v;
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else if (v !== false && v != null) el.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat()) if (kid != null) el.append(kid);
    return el;
  }

  async function api(path, { method = 'GET', body } = {}) {
    const opts = { method, headers: { 'X-Skrapkin': '1' } };
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    let res;
    try { res = await fetch(path, opts); }
    catch { throw new Error("Can't reach SKrapkin. Is it still running?"); }
    let data = null;
    try { data = await res.json(); } catch { /* not JSON */ }
    if (!res.ok) throw new Error((data && data.error) || `Request failed (${res.status}).`);
    return data;
  }

  function toast(message, kind = '') {
    const t = h('div', { class: `toast ${kind}` }, message);
    $('toasts').append(t);
    setTimeout(() => t.remove(), kind === 'error' ? 8000 : 4500);
  }

  function setStatus(el, text, kind = '') {
    el.textContent = text;
    el.className = `status small ${kind}`.trim();
  }

  const safeUrl = (u) => /^https?:\/\//i.test(u || '');
  const debounce = (fn, ms = 300) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

  async function copyText(text) {
    try { await navigator.clipboard.writeText(text); return true; }
    catch {
      const ta = h('textarea', { 'aria-hidden': 'true' });
      ta.value = text;
      document.body.append(ta);
      ta.select();
      const ok = document.execCommand('copy');
      ta.remove();
      return ok;
    }
  }

  function confirmDialog(title, body, okLabel = 'Continue') {
    return new Promise((resolve) => {
      const d = $('confirm');
      $('confirm-title').textContent = title;
      $('confirm-body').textContent = body;
      $('confirm-ok').textContent = okLabel;
      d.returnValue = 'cancel';
      d.addEventListener('close', () => resolve(d.returnValue === 'ok'), { once: true });
      d.showModal();
    });
  }

  const prefs = {
    get(key, fallback) { try { return JSON.parse(localStorage.getItem('skrapkin.' + key)) ?? fallback; } catch { return fallback; } },
    set(key, value) { try { localStorage.setItem('skrapkin.' + key, JSON.stringify(value)); } catch { /* private mode */ } },
  };

  // ---- sortable, selectable table ---------------------------------------------------------------
  function Table(root, columns, { id, selectable = false, empty = 'Nothing here yet.', rowClass } = {}) {
    let rows = [];
    let sortKey = null;
    let dir = 1;
    const selected = new Set();

    const valueOf = (row, c) => (c.value ? c.value(row) : row[c.key]);
    const sorted = () => {
      if (!sortKey) return rows;
      const c = columns.find((x) => x.key === sortKey);
      return [...rows].sort((a, b) => {
        const x = valueOf(a, c), y = valueOf(b, c);
        const cmp = typeof x === 'number' && typeof y === 'number'
          ? x - y : String(x ?? '').localeCompare(String(y ?? ''), undefined, { numeric: true, sensitivity: 'base' });
        return cmp * dir;
      });
    };

    function render() {
      const shown = sorted();
      const all = h('input', { type: 'checkbox', 'aria-label': 'Select all rows', onchange: (e) => {
        selected.clear();
        if (e.target.checked) shown.forEach((r) => selected.add(id(r)));
        render();
      } });
      all.checked = shown.length > 0 && shown.every((r) => selected.has(id(r)));
      const head = h('tr', {},
        selectable ? h('th', { class: 'nosort' }, all) : null,
        columns.map((c) => h('th', {
          title: 'Click to sort',
          onclick: () => { dir = sortKey === c.key ? -dir : 1; sortKey = c.key; render(); },
        }, c.title + (sortKey === c.key ? (dir > 0 ? ' ▲' : ' ▼') : ''))));
      const body = shown.length
        ? shown.map((r) => {
            const isSel = selectable && selected.has(id(r));
            const box = selectable ? h('td', {}, (() => {
              const cb = h('input', { type: 'checkbox', 'aria-label': 'Select row', onchange: (e) => {
                e.target.checked ? selected.add(id(r)) : selected.delete(id(r));
                e.target.closest('tr').classList.toggle('selected', e.target.checked);
              } });
              cb.checked = isSel;
              return cb;
            })()) : null;
            return h('tr', { class: [isSel ? 'selected' : '', rowClass ? rowClass(r) : ''].join(' ').trim() },
              box, columns.map((c) => h('td', {}, c.render ? c.render(r) : String(r[c.key] ?? ''))));
          })
        : [h('tr', {}, h('td', { class: 'empty', colspan: columns.length + (selectable ? 1 : 0) }, empty))];
      const wrap = h('div', { class: 'table-wrap' }, h('table', {}, h('thead', {}, head), h('tbody', {}, body)));
      root.replaceChildren(wrap);
    }

    render();
    return {
      setRows(next) { rows = next; const ids = new Set(rows.map(id)); [...selected].forEach((s) => ids.has(s) || selected.delete(s)); render(); },
      selected: () => rows.filter((r) => selected.has(id(r))),
      all: () => rows,
      count: () => rows.length,
    };
  }

  const link = (url) => (safeUrl(url)
    ? h('a', { href: url, target: '_blank', rel: 'noopener noreferrer' }, url.replace(/^https?:\/\/(www\.)?/i, '').replace(/\/$/, ''))
    : String(url || ''));

  const emailChips = (list) => h('span', {}, (list || []).map((e) =>
    h('span', { class: `chip st-${e.status}`, title: e.note ? `${e.status}: ${e.note}` : e.status }, e.address)));

  // ---- state and tabs -------------------------------------------------------------------------
  let STATUS = null;
  let activeTab = 'find';
  let busy = null;   // kind of the task currently followed, or null

  function showTab(name) {
    if (!$('tab-' + name)) name = 'find';
    activeTab = name;
    document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('active', t.id === 'tab-' + name));
    document.querySelectorAll('#tabs button').forEach((b) => b.classList.toggle('active', b.dataset.tab === name));
    if (location.hash !== '#' + name) history.replaceState(null, '', '#' + name);
    ({ leads: loadLeads, verified: loadVerified, verify: refreshHunter, settings: fillSettings })[name]?.();
  }

  async function refreshStatus() {
    try { STATUS = await api('/api/status'); }
    catch (e) { setPill('pill-db', 'Offline', 'bad', e.message); return null; }
    const db = STATUS.db;
    setPill('pill-db', db.connected ? 'Database: connected' : 'Database: not connected',
      db.connected ? 'ok' : 'bad', db.connected ? db.target : db.error || 'Open Settings to connect');
    const hk = STATUS.hunter;
    setPill('pill-hunter', hk.configured ? 'Hunter: key saved' : 'Hunter: no key', hk.configured ? 'ok' : 'warn',
      hk.source ? `Key from ${hk.source}` : 'Add a key on the Verify tab');
    return STATUS;
  }

  function setPill(id, text, kind, title) {
    const el = $(id);
    el.textContent = text;
    el.className = `pill pill-${kind}`;
    el.title = title || '';
  }

  function fillSelect(sel, options, firstLabel) {
    sel.replaceChildren(
      ...(firstLabel ? [h('option', { value: '' }, firstLabel)] : []),
      ...options.map((o) => h('option', { value: o.value }, o.label)));
  }

  // ---- following a background task ---------------------------------------------------------------
  async function follow(taskId, onUpdate) {
    let cursor = 0;
    for (;;) {
      let snap;
      try { snap = await api(`/api/tasks/${taskId}?cursor=${cursor}`); }
      catch (e) { toast(e.message, 'error'); return null; }
      cursor = snap.lead_count;
      onUpdate(snap);
      if (snap.state !== 'running') return snap;
      await sleep(700);
    }
  }

  function setBusy(kind) {
    busy = kind;
    $('find-start').textContent = kind === 'find' ? 'Searching…' : 'Find leads';
    $('verify-start').textContent = kind === 'verify' ? 'Verifying…' : 'Verify now';
    $('find-stop').textContent = 'Stop';
    $('verify-stop').textContent = 'Stop';
    $('find-start').disabled = !!kind;
    $('verify-start').disabled = !!kind;
    $('verify-preview').disabled = kind === 'verify';
    $('find-stop').disabled = kind !== 'find';
    $('verify-stop').disabled = kind !== 'verify';
  }

  async function stopTask(taskId, button) {
    if (!taskId) return;
    button.disabled = true;
    button.textContent = 'Stopping…';
    try { await api(`/api/tasks/${taskId}/stop`, { method: 'POST' }); }
    catch (e) { toast(e.message, 'error'); button.disabled = false; button.textContent = 'Stop'; }
  }

  // Bar fills as businesses are checked; before that (waiting on OpenStreetMap) it just animates.
  function showProgress(bar, snap) {
    if (snap.state === 'running' && snap.total === 0) { bar.removeAttribute('value'); return; }
    bar.max = Math.max(snap.total, 1);
    bar.value = snap.done;
  }

  // ---- countries and regions -----------------------------------------------------------------------
  const regionCache = {};
  const countryName = {};

  async function loadRegions(code) {
    if (!code) return [];
    if (!regionCache[code]) {
      try { regionCache[code] = (await api(`/api/regions/${encodeURIComponent(code)}`)).regions; }
      catch { regionCache[code] = []; }
    }
    return regionCache[code];
  }

  // Fill a region <select> for a country. firstLabel is the "no region" choice.
  async function fillRegions(select, code, firstLabel, keep = '') {
    const list = await loadRegions(code);
    fillSelect(select, list.map((r) => ({ label: r.name, value: r.name })), firstLabel);
    select.disabled = !code || list.length === 0;
    if (keep && list.some((r) => r.name === keep)) select.value = keep;
    select.dispatchEvent(new Event('regions-loaded'));
  }

  // ---- find leads --------------------------------------------------------------------------------
  let findTable, findTaskId = null, findRows = [];

  function initFind() {
    const o = STATUS.options;
    fillSelect($('find-category'), o.categories);
    o.countries.forEach((c) => { countryName[c.code] = c.name; });
    fillSelect($('find-country'), o.countries.map((c) => ({ label: c.name, value: c.code })));
    fillSelect($('find-confidence'), o.confidence);
    const p = prefs.get('find', {});
    $('find-category').value = p.category || o.categories[0].value;
    $('find-country').value = p.country || 'US';
    fillRegions($('find-region'), $('find-country').value, 'Entire country (a sample)', p.region || '');
    $('find-country').addEventListener('change', () => fillRegions($('find-region'), $('find-country').value, 'Entire country (a sample)'));
    $('find-place').value = p.place || '';
    $('find-max').value = p.max || 100;
    $('find-confidence').value = p.confidence || 'medium';
    $('find-personal').checked = p.personal ?? true;
    $('find-chains').checked = p.chains ?? false;
    $('find-save').checked = p.save ?? true;
    $('find-skip').checked = p.skip ?? true;
    $('find-workers').value = p.workers || 8;
    $('find-thorough').checked = p.thorough ?? false;
    $('find-verify').checked = p.verify ?? false;
    findTable = Table($('find-table'), [
      { key: 'business', title: 'Business' },
      { key: 'website', title: 'Website', render: (r) => link(r.website) },
      { key: 'emails', title: 'Emails' },
      { key: 'phones', title: 'Phones' },
      { key: 'confidence', title: 'Confidence' },
    ], { id: (r) => r.n, empty: 'Results appear here as they are found.' });
    $('find-start').addEventListener('click', startFind);
    $('find-stop').addEventListener('click', () => stopTask(findTaskId, $('find-stop')));
    const hint = () => { $('find-hint').hidden = !!($('find-region').value || $('find-place').value.trim()); };
    ['find-country', 'find-region'].forEach((id) => $(id).addEventListener('change', hint));
    $('find-place').addEventListener('input', hint);
    $('find-region').addEventListener('regions-loaded', hint);
    hint();
  }

  async function startFind() {
    if (!$('find-region').value && !$('find-place').value.trim()) {
      const name = $('find-country').selectedOptions[0].textContent;
      const ok = await confirmDialog(`Search all of ${name}?`,
        'A whole-country search is slow and often times out on the free OpenStreetMap server, and returns only a sample. Choosing a region or city is faster and gives a fuller result.',
        'Search anyway');
      if (!ok) return;
    }
    const body = {
      category: $('find-category').value, country: $('find-country').value,
      region: $('find-region').value, place: $('find-place').value.trim(),
      max_businesses: Number($('find-max').value), min_confidence: $('find-confidence').value,
      exclude_personal: !$('find-personal').checked, keep_chains: $('find-chains').checked,
      save_db: $('find-save').checked, verify_after: $('find-verify').checked,
      skip_checked: $('find-skip').checked, workers: Number($('find-workers').value),
      thorough: $('find-thorough').checked,
    };
    prefs.set('find', { category: body.category, country: body.country, region: body.region, place: body.place,
      max: body.max_businesses,
      confidence: body.min_confidence, personal: !body.exclude_personal, chains: body.keep_chains,
      save: body.save_db, verify: body.verify_after, skip: body.skip_checked, workers: body.workers,
      thorough: body.thorough });
    try {
      const { task } = await api('/api/find', { method: 'POST', body });
      attachFind(task);
    } catch (e) { toast(e.message, 'error'); }
  }

  async function attachFind(taskId) {
    findTaskId = taskId;
    findRows = [];
    findTable.setRows([]);
    $('find-download').hidden = true;
    $('find-counter').textContent = '';
    setBusy('find');
    const skippedHistory = $('find-skip').checked && $('find-save').checked;
    const final = await follow(taskId, (s) => {
      showProgress($('find-progress'), s);
      if (s.logs.length && s.state === 'running') {
        setStatus($('find-status'), `${s.logs[s.logs.length - 1]} (${Math.round(s.elapsed)}s)`);
      } else if (s.logs.length) setStatus($('find-status'), s.logs[s.logs.length - 1]);
      $('find-log').textContent = s.logs.join('\n');
      if (s.leads.length) {
        const start = findRows.length;
        findRows = s.leads.map((l, i) => ({ ...l, n: start + i })).reverse().concat(findRows);
        findTable.setRows(findRows);
      }
      const withEmail = findRows.filter((r) => r.emails).length;
      $('find-counter').textContent = findRows.length ? `${findRows.length} leads · ${withEmail} with an email` : '';
    });
    setBusy(null);
    $('find-progress').max = 1;
    $('find-progress').value = 0;
    if (!final) return;
    const dl = $('find-download');
    if (final.state === 'error') {
      setStatus($('find-status'), final.error, 'error');
      toast(final.error, 'error');
    } else {
      const r = final.result || {};
      const word = final.state === 'stopped' ? 'Stopped' : 'Done';
      setStatus($('find-status'), r.count
        ? `${word}: ${r.count} leads${r.saved_to_database ? ' saved to the database' : ''}.`
        : (skippedHistory
          ? `${word}: no new businesses. Everything findable here was already checked. Try another region, city or category.`
          : `${word}: no leads found. Try a different region or category.`), r.count ? 'ok' : '');
      if (r.file) { dl.href = `/api/download/${encodeURIComponent(r.file)}`; dl.hidden = false; }
      if (r.verification) toast(`Verification: ${r.verification.valid} valid, ${r.verification.invalid} invalid.`, 'ok');
    }
    refreshStatus();
  }

  // ---- leads -------------------------------------------------------------------------------------
  let leadsTable;
  const STATUS_OPTIONS = [
    { label: 'Verified (valid)', value: 'valid' }, { label: 'Not checked yet', value: 'unchecked' },
    { label: 'Invalid', value: 'invalid' }, { label: 'Accept-all (risky)', value: 'accept_all' },
    { label: 'Webmail', value: 'webmail' }, { label: 'Skipped: unlikely real', value: 'filtered' },
    { label: 'Unknown', value: 'unknown' },
  ];

  function filterQuery(prefix, withStatus) {
    const q = new URLSearchParams();
    const put = (k, id) => { const v = $(`${prefix}-${id}`)?.value; if (v) q.set(k, v); };
    put('q', 'q'); put('category', 'category'); put('country', 'country'); put('region', 'region');
    if (withStatus) put('status', 'status');
    return q.toString();
  }

  function initLeads() {
    const o = STATUS.options;
    fillSelect($('leads-category'), o.categories, 'All types');
    const countryOptions = o.countries.map((c) => ({ label: c.name, value: c.code }));
    o.countries.forEach((c) => { countryName[c.code] = c.name; });
    fillSelect($('leads-country'), countryOptions, 'All countries');
    fillRegions($('leads-region'), '', 'All regions');
    fillSelect($('leads-status'), STATUS_OPTIONS, 'Any email status');
    leadsTable = Table($('leads-table'), [
      { key: 'business', title: 'Business' },
      { key: 'country', title: 'Country', value: (r) => countryName[r.country] || r.country, render: (r) => countryName[r.country] || r.country },
      { key: 'region', title: 'Region' },
      { key: 'city', title: 'City' },
      { key: 'website', title: 'Website', render: (r) => link(r.website) },
      { key: 'emails', title: 'Emails', value: (r) => r.emails.map((e) => e.address).join(' '), render: (r) => emailChips(r.emails) },
      { key: 'phones', title: 'Phones', value: (r) => r.phones.join(' '), render: (r) => r.phones.join('; ') },
      { key: 'confidence', title: 'Confidence' },
    ], { id: (r) => r.key, selectable: true, empty: 'No leads yet. Run a search on the Find leads tab.' });
    const reload = debounce(loadLeads);
    $('leads-q').addEventListener('input', reload);
    $('leads-country').addEventListener('change', async () => {
      await fillRegions($('leads-region'), $('leads-country').value, 'All regions');
      loadLeads();
    });
    ['leads-category', 'leads-region', 'leads-status'].forEach((id) => $(id).addEventListener('change', loadLeads));
    $('leads-refresh').addEventListener('click', loadLeads);
    $('leads-copy').addEventListener('click', async () => {
      const src = leadsTable.selected().length ? leadsTable.selected() : leadsTable.all();
      const emails = src.flatMap((l) => l.emails.map((e) => e.address));
      toast(emails.length && (await copyText(emails.join('\n'))) ? `Copied ${emails.length} emails.` : 'No emails to copy.');
    });
    $('leads-delete').addEventListener('click', async () => {
      const sel = leadsTable.selected();
      if (!sel.length) return toast('Select some leads first.');
      if (!window.confirm(`Delete ${sel.length} selected leads? Verified emails already filed stay in Verified results.`)) return;
      try {
        const r = await api('/api/leads/delete', { method: 'POST', body: { keys: sel.map((l) => l.key) } });
        toast(`Deleted ${r.deleted} leads.`, 'ok');
        loadLeads();
      } catch (e) { toast(e.message, 'error'); }
    });
  }

  async function loadLeads() {
    const qs = filterQuery('leads', true);
    $('leads-export').href = '/api/export/leads.csv' + (qs ? '?' + qs : '');
    try {
      const d = await api('/api/leads' + (qs ? '?' + qs : ''));
      leadsTable.setRows(d.leads);
      $('leads-count').textContent = `Showing ${d.leads.length} leads · ${d.totals.leads} saved in total · ${d.totals.verified} verified emails`;
    } catch (e) {
      leadsTable.setRows([]);
      $('leads-count').textContent = e.message;
    }
  }

  // ---- verify ------------------------------------------------------------------------------------
  let verifyTable, verifyTaskId = null;

  function initVerify() {
    verifyTable = Table($('verify-table'), [
      { key: 'decision', title: 'Decision', render: (r) => h('span', { class: r.decision === 'check' ? 'decision-check' : 'decision-skip' },
        r.decision === 'check' ? '✔ Check with Hunter' : `Skip: ${r.reason}`) },
      { key: 'email', title: 'Email' },
      { key: 'business', title: 'Business' },
      { key: 'score', title: 'Score' },
    ], { id: (r) => r.email, empty: 'Click Preview to see what would be checked.', rowClass: (r) => (r.decision === 'check' ? '' : 'skip') });
    $('hunter-save').addEventListener('click', saveKey);
    $('hunter-remove').addEventListener('click', removeKey);
    $('verify-save-settings').addEventListener('click', saveVerifySettings);
    $('verify-preview').addEventListener('click', () => previewVerify().catch((e) => toast(e.message, 'error')));
    $('verify-start').addEventListener('click', startVerify);
    $('verify-stop').addEventListener('click', () => stopTask(verifyTaskId, $('verify-stop')));
  }

  async function refreshHunter() {
    if (!STATUS) return;
    $('verify-threshold').value = STATUS.config.min_likelihood;
    $('verify-budget').value = STATUS.config.max_credits_per_run;
    const el = $('hunter-status');
    if (!STATUS.hunter.configured) return setStatus(el, 'No key saved yet. Verification is disabled until you add one.');
    try {
      const { account } = await api('/api/hunter/account');
      setStatus(el, `Key works (from ${STATUS.hunter.source}). Plan: ${account.plan || 'n/a'}, ${account.remaining} of ${account.available} verifications left.`, 'ok');
    } catch (e) { setStatus(el, e.message, 'error'); }
  }

  async function saveKey() {
    const key = $('hunter-key').value.trim();
    if (!key) return toast('Paste your Hunter API key first.');
    setStatus($('hunter-status'), 'Testing key (free)…');
    try {
      const r = await api('/api/hunter/key', { method: 'POST', body: { key } });
      $('hunter-key').value = '';
      toast('Key saved.', 'ok');
      await refreshStatus();
      setStatus($('hunter-status'), `Key works and is saved. Plan: ${r.account.plan || 'n/a'}, ${r.account.remaining} of ${r.account.available} verifications left.`, 'ok');
    } catch (e) { setStatus($('hunter-status'), e.message, 'error'); }
  }

  async function removeKey() {
    try {
      const r = await api('/api/hunter/key', { method: 'DELETE' });
      toast(r.note || 'Key removed.', r.note ? '' : 'ok');
      await refreshStatus();
      refreshHunter();
    } catch (e) { toast(e.message, 'error'); }
  }

  async function saveVerifySettings() {
    try {
      const r = await api('/api/verify/settings', { method: 'POST', body: {
        min_likelihood: Number($('verify-threshold').value), max_credits_per_run: Number($('verify-budget').value) } });
      STATUS.config.min_likelihood = r.min_likelihood;
      STATUS.config.max_credits_per_run = r.max_credits_per_run;
      toast('Settings saved.', 'ok');
    } catch (e) { toast(e.message, 'error'); }
  }

  async function previewVerify() {
    await saveVerifySettings();
    setStatus($('verify-summary'), 'Checking which emails are worth a lookup…');
    const d = await api('/api/verify/preview', { method: 'POST' });
    const order = { check: 0, skip: 1 };
    verifyTable.setRows(d.rows.sort((a, b) => order[a.decision] - order[b.decision] || b.score - a.score));
    setStatus($('verify-summary'), `${d.will_use} emails would use Hunter credits. ${d.summary}`);
    return d;
  }

  async function startVerify() {
    try {
      const d = await previewVerify();
      if (d.will_use === 0) return toast('Nothing to verify: no new emails need a Hunter lookup.');
      const ok = await confirmDialog('Use Hunter credits?',
        `This will check ${d.will_use} emails with Hunter and use up to ${d.will_use} of your verification credits. ${d.skipped} other emails are skipped for free.`,
        `Check ${d.will_use} emails`);
      if (!ok) return;
      const { task } = await api('/api/verify/start', { method: 'POST' });
      attachVerify(task);
    } catch (e) { toast(e.message, 'error'); }
  }

  async function attachVerify(taskId) {
    verifyTaskId = taskId;
    setBusy('verify');
    const final = await follow(taskId, (s) => {
      showProgress($('verify-progress'), s);
      if (s.logs.length) setStatus($('verify-summary'), s.logs[s.logs.length - 1]);
    });
    setBusy(null);
    $('verify-progress').max = 1;
    $('verify-progress').value = 0;
    if (!final) return;
    if (final.state === 'error') {
      setStatus($('verify-summary'), final.error, 'error');
      return toast(final.error, 'error');
    }
    const st = (final.result || {}).stats || {};
    let text = `Checked ${st.checked} with Hunter: ${st.valid} valid, ${st.invalid} invalid, ${st.accept_all} accept-all, ${st.unknown} unknown. Skipped ${st.skipped_free} for free.`;
    if (st.left_unchecked) text += ` ${st.left_unchecked} emails are waiting for the next run.`;
    if (st.stopped) text += ` Stopped: ${st.stopped}.`;
    setStatus($('verify-summary'), text, 'ok');
    verifyTable.setRows([]);
    refreshStatus();
    refreshHunter();
  }

  // ---- verified ----------------------------------------------------------------------------------
  let verifiedTable;

  function initVerified() {
    const o = STATUS.options;
    fillSelect($('verified-category'), o.categories, 'All types');
    fillSelect($('verified-country'), o.countries.map((c) => ({ label: c.name, value: c.code })), 'All countries');
    fillRegions($('verified-region'), '', 'All regions');
    verifiedTable = Table($('verified-table'), [
      { key: 'email', title: 'Email' },
      { key: 'business', title: 'Business' },
      { key: 'country', title: 'Country', value: (r) => countryName[r.country] || r.country, render: (r) => countryName[r.country] || r.country },
      { key: 'region', title: 'Region' },
      { key: 'city', title: 'City' },
      { key: 'website', title: 'Website', render: (r) => link(r.website) },
      { key: 'phones', title: 'Phones', value: (r) => r.phones.join(' '), render: (r) => r.phones.join('; ') },
      { key: 'score', title: 'Score' },
      { key: 'verified_at', title: 'Verified', render: (r) => (r.verified_at || '').slice(0, 16).replace('T', ' ') },
    ], { id: (r) => r.email, selectable: true, empty: 'No verified emails yet. Verify some on the Verify emails tab.' });
    $('verified-q').addEventListener('input', debounce(loadVerified));
    $('verified-country').addEventListener('change', async () => {
      await fillRegions($('verified-region'), $('verified-country').value, 'All regions');
      loadVerified();
    });
    ['verified-category', 'verified-region'].forEach((id) => $(id).addEventListener('change', loadVerified));
    $('verified-refresh').addEventListener('click', loadVerified);
    $('verified-copy-all').addEventListener('click', async () => {
      const emails = verifiedTable.all().map((r) => r.email);
      toast(emails.length && (await copyText(emails.join('\n'))) ? `Copied ${emails.length} emails.` : 'No emails to copy.');
    });
    $('verified-delete').addEventListener('click', async () => {
      const sel = verifiedTable.selected();
      if (!sel.length) return toast('Select some emails first.');
      if (!window.confirm(`Remove ${sel.length} emails from the verified list?`)) return;
      try {
        await api('/api/verified/delete', { method: 'POST', body: { emails: sel.map((r) => r.email) } });
        loadVerified();
      } catch (e) { toast(e.message, 'error'); }
    });
  }

  async function loadVerified() {
    const qs = filterQuery('verified', false);
    $('verified-export').href = '/api/export/verified.csv' + (qs ? '?' + qs : '');
    try {
      const d = await api('/api/verified' + (qs ? '?' + qs : ''));
      verifiedTable.setRows(d.verified);
      $('verified-count').textContent = `${d.verified.length} verified emails`;
    } catch (e) {
      verifiedTable.setRows([]);
      $('verified-count').textContent = e.message;
    }
  }

  // ---- settings ----------------------------------------------------------------------------------
  function initSettings() {
    $('db-show').addEventListener('change', (e) => { $('db-uri').type = e.target.checked ? 'text' : 'password'; });
    $('history-clear').addEventListener('click', async () => {
      if (!window.confirm('Forget every business SKrapkin has checked? Repeat searches will check the same businesses again. Saved leads are not touched.')) return;
      try {
        const r = await api('/api/history/clear', { method: 'POST' });
        toast(`Forgot ${r.cleared} businesses.`, 'ok');
        loadHistory();
      } catch (e) { toast(e.message, 'error'); }
    });
    $('db-save').addEventListener('click', async () => {
      const el = $('db-result');
      setStatus(el, 'Connecting…');
      try {
        const r = await api('/api/db', { method: 'POST', body: { uri: $('db-uri').value.trim(), db_name: $('db-name').value.trim() } });
        $('db-uri').value = '';
        setStatus(el, r.connected ? `Connected to ${r.target}.` : r.error, r.connected ? 'ok' : 'error');
        await refreshStatus();
      } catch (e) { setStatus(el, e.message, 'error'); }
    });
  }

  async function loadHistory() {
    const el = $('history-count');
    try {
      const { checked } = await api('/api/history');
      setStatus(el, checked ? `${checked} businesses checked so far.` : 'Nothing checked yet.');
    } catch (e) { setStatus(el, e.message); }
  }

  function fillSettings() {
    if (!STATUS) return;
    loadHistory();
    $('db-name').value = STATUS.config.db_name;
    $('db-env-note').hidden = !STATUS.db.uri_from_environment;
    $('db-uri').disabled = STATUS.db.uri_from_environment;
    $('db-uri').placeholder = STATUS.db.uri_from_environment ? 'Set by environment' : 'mongodb://localhost:27017';
    $('about-version').textContent = 'v' + STATUS.version;
    $('about-output').textContent = STATUS.output_dir;
    const el = $('db-result');
    if (STATUS.db.connected) setStatus(el, `Connected to ${STATUS.db.target}.`, 'ok');
    else setStatus(el, STATUS.db.error || 'Not connected.', 'error');
  }

  // ---- boot --------------------------------------------------------------------------------------
  async function boot() {
    document.querySelectorAll('#tabs button').forEach((b) => b.addEventListener('click', () => showTab(b.dataset.tab)));
    window.addEventListener('hashchange', () => showTab(location.hash.slice(1)));
    if (!(await refreshStatus())) {
      // keep trying: the server may still be starting
      for (let i = 0; i < 20 && !STATUS; i++) { await sleep(1500); await refreshStatus(); }
      if (!STATUS) return;
    }
    initFind(); initLeads(); initVerify(); initVerified(); initSettings();
    showTab(location.hash.slice(1) || 'find');
    setInterval(() => { if (!document.hidden) refreshStatus(); }, 15000);
    if (STATUS.active_task) {
      const { id, kind } = STATUS.active_task;
      if (kind === 'find') { showTab('find'); attachFind(id); }
      else { showTab('verify'); attachVerify(id); }
    }
  }

  boot();
})();
