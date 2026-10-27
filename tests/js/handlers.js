// Behaviour of the page scripts in a DOM emulator (jsdom). Run by tests/test_js_handlers.py,
// which skips when jsdom is not installed: `npm install jsdom` somewhere and point NODE_PATH at it.
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const dir = process.argv[2];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function load(file, url, respond) {
  const calls = [];
  const dom = new JSDOM(fs.readFileSync(path.join(dir, file), 'utf8'), {
    runScripts: 'dangerously', pretendToBeVisual: true, url,
    beforeParse(w) {
      w.fetch = (u, o) => {
        calls.push({ url: String(u), body: o && o.body ? JSON.parse(o.body) : null });
        const r = respond(String(u));
        if (r.reject) return Promise.reject(new Error('network down'));
        const answer = { ok: r.ok, status: r.status, json: () => (r.json === null ? Promise.reject(new Error('not json')) : Promise.resolve(r.json)) };
        return r.delay ? new Promise((resolve) => setTimeout(() => resolve(answer), r.delay)) : Promise.resolve(answer);
      };
    },
  });
  return { dom, d: dom.window.document, calls };
}
const ok = { ok: true, status: 200, json: { ok: true, quotes: {}, group_html: '' } };

async function promote(mode) {
  const respond = (u) => {
    if (!u.includes('/promote')) return ok;
    if (mode === 'ok') return ok;
    if (mode === '400') return { ok: false, status: 400, json: { error: "unknown group: 'individual'" } };
    if (mode === 'html') return { ok: false, status: 502, json: null };
    return { ok: false, status: 503, json: { error: 'storage error' } };
  };
  const { dom, d, calls } = load('shortlist.html', 'http://localhost/screener?tab=shortlisted', respond);
  await sleep(60);
  const first = d.querySelector('tr[data-symbol-row="AAA"]'), second = d.querySelector('tr[data-symbol-row="BBB"]');
  const button = first.querySelector('button[data-action="promote"]');
  const otherButton = second.querySelector('button[data-action="promote"]');
  assert(!first.hasAttribute('data-promoted'), 'starts normal');
  button.click();
  assert(first.hasAttribute('data-promoted'), 'greys at once');
  assert(button.disabled && button.textContent.includes('Promoted'), 'button reads Promoted and is disabled');
  assert(otherButton.disabled, 'other Promote buttons are disabled while the request runs');
  assert.strictEqual(d.activeElement, first.querySelector('[data-action="dismissed"]'), 'focus moves to Dismiss');
  await sleep(60);
  const posts = calls.filter((c) => c.url.includes('/promote'));
  assert.deepStrictEqual(posts.map((p) => p.body), [{ symbol: first.dataset.symbolRow }], 'one post with only the symbol');
  assert.strictEqual(calls.filter((c) => c.url.includes('/status')).length, 0, 'no status post');
  assert(!otherButton.disabled, 'other buttons come back');
  const toast = d.getElementById('toast');
  if (mode === 'ok') {
    assert(first.hasAttribute('data-promoted') && button.disabled, 'stays promoted');
    assert(d.getElementById('announce').textContent.includes('promoted to the watchlist'), 'announced');
  } else {
    assert(!first.hasAttribute('data-promoted') && !button.disabled && button.textContent === 'Promote', 'restored');
    assert(!toast.hidden && toast.textContent.includes("Couldn't add"), 'toast shown');
    if (mode === '400') assert(toast.textContent.includes("unknown group"), 'server reason shown');
    if (mode === '503') assert(toast.textContent.includes('storage error'), 'server reason shown');
    if (mode === 'html') assert(!toast.textContent.includes('Unexpected') && !toast.textContent.includes(':'), 'no raw parse error shown');
  }
  dom.window.close();
}

async function quotesFillTheRightCells() {
  const cells = '<td class="num">$12.00</td><td class="num">+0.30</td><td class="range-bar-cell">bar</td><td class="num">57%</td>';
  for (const failing of [false, true]) {
    const respond = (u) => {
      if (!u.includes('/api/screener/quotes')) return ok;
      if (failing) return { ok: false, status: 503, json: {} };
      const symbols = new URL(u, 'http://localhost').searchParams.get('symbols').split(',');
      const quotes = {};
      symbols.forEach((s) => { quotes[s] = { html: cells, pct_in_range: 57.1, change_percent: 2.5 }; });
      return { ok: true, status: 200, json: { quotes } };
    };
    const { dom, d } = load('shortlist.html', 'http://localhost/screener?tab=shortlisted', respond);
    await sleep(60);
    assert.strictEqual(d.getElementById('checking-indicator'), null, 'the indicator clears once the batches settle');
    const row = d.querySelector('tr.screener-row');
    const texts = Array.from(row.children).map((c) => c.textContent.trim());
    assert(/^(n\/a|\d+)$/.test(texts[1]), 'the Score cell keeps its score, got ' + texts[1]);
    if (failing) assert.deepStrictEqual(texts.slice(2, 6), ['n/a', 'n/a', 'n/a', 'n/a'], 'a failed batch blanks the four quote cells');
    else {
      assert.deepStrictEqual(texts.slice(2, 6), ['$12.00', '+0.30', 'bar', '57%'], 'quote cells land after Score');
      assert.strictEqual(row.dataset.pctinrange, '57.1');
    }
    dom.window.close();
  }
}

async function screenerSorting() {
  const { dom, d } = load('shortlist.html', 'http://localhost/screener?tab=shortlisted', () => ok);
  await sleep(60);
  const order = () => Array.from(d.querySelectorAll('tr.screener-row')).map((r) => r.dataset.symbolRow);
  const th = d.querySelector('th.sortable[data-sort-key="symbol"]');
  th.click();  // the cell itself (where the arrow is), not the label button
  assert.strictEqual(th.getAttribute('aria-sort'), 'ascending', 'a click on the cell sorts');
  assert.deepStrictEqual(order(), order().slice().sort());
  th.click();
  assert.strictEqual(th.getAttribute('aria-sort'), 'descending', 'a second click reverses');
  assert.deepStrictEqual(order(), order().slice().sort().reverse());
  th.querySelector('button').click();  // the label button reaches the same handler once, not twice
  assert.strictEqual(th.getAttribute('aria-sort'), 'ascending', 'the button toggles once');
  const other = d.querySelector('th.sortable[data-sort-key="marketCap"]');
  other.click();
  assert.strictEqual(th.getAttribute('aria-sort'), 'none', 'sorting another column clears the first');
  dom.window.close();
}

async function checkingCue() {
  const quotes = (u) => {
    const symbols = new URL(u, 'http://localhost').searchParams.get('symbols').split(',');
    const out = {};
    symbols.forEach((s) => { out[s] = { html: '<td class="num">$1.00</td><td class="num">+0.00</td><td class="range-bar-cell">bar</td><td class="num">50%</td>', pct_in_range: 50, change_percent: 0 }; });
    return { quotes: out };
  };
  // 26 rows are two batches (25 + 1): the cue stays until the slower one is done.
  let { dom, d } = load('many.html', 'http://localhost/screener?tab=new', (u) =>
    (u.includes('/api/screener/quotes') ? { ok: true, status: 200, json: quotes(u), delay: Object.keys(quotes(u).quotes).length > 5 ? 120 : 20 } : ok));
  assert(d.getElementById('checking-indicator'), 'the cue is up before any answer');
  await sleep(60);
  assert(d.getElementById('checking-indicator'), 'it stays while the larger batch is still out');
  await sleep(200);
  assert.strictEqual(d.getElementById('checking-indicator'), null, 'it clears when the last batch lands');
  dom.window.close();
  // a rejected request and a failure handler that throws both still end the batch
  ({ dom, d } = load('many.html', 'http://localhost/screener?tab=new', (u) => (u.includes('/api/screener/quotes') ? { reject: true } : ok)));
  await sleep(100);
  assert.strictEqual(d.getElementById('checking-indicator'), null, 'a rejected fetch clears the cue');
  assert(d.getElementById('prices-note').textContent.includes("couldn't be loaded"));
  dom.window.close();
  ({ dom, d } = load('many.html', 'http://localhost/screener?tab=new', (u) => (u.includes('/api/screener/quotes') ? { ok: false, status: 503, json: {} } : ok)));
  d.querySelectorAll('tr.screener-row').forEach((r) => { while (r.children.length > 3) r.removeChild(r.lastChild); });  // rows too short for the failure handler
  await sleep(100);
  assert.strictEqual(d.getElementById('checking-indicator'), null, 'a failure handler that throws still clears the cue');
  dom.window.close();
}

async function scoreSorting() {
  const { dom, d } = load('scores.html', 'http://localhost/screener?tab=shortlisted', () => ok);
  await sleep(60);
  const scores = () => Array.from(d.querySelectorAll('tr.screener-row')).map((r) => (r.dataset.score === '' ? null : parseFloat(r.dataset.score)));
  assert(scores().includes(null) && scores().filter((x) => x !== null).length >= 3, 'the fixture has scored rows and a blank one');
  const th = d.querySelector('th.sortable[data-sort-key="score"]');
  th.click();
  const asc = scores();
  assert.strictEqual(asc[asc.length - 1], null, 'a blank score sorts last ascending');
  const filled = asc.filter((x) => x !== null);
  assert.deepStrictEqual(filled, filled.slice().sort((a, b) => a - b), 'ascending is numeric, not text');
  assert(th.getAttribute('aria-sort') === 'ascending');
  assert(d.getElementById('announce').textContent === 'Sorted by Score, ascending', 'the sort is announced');
  th.click();
  const desc = scores();
  assert.strictEqual(desc[desc.length - 1], null, 'a blank score sorts last descending too');
  const filledDesc = desc.filter((x) => x !== null);
  assert.deepStrictEqual(filledDesc, filledDesc.slice().sort((a, b) => b - a), 'descending is numeric');
  assert(d.getElementById('announce').textContent === 'Sorted by Score, descending');
  dom.window.close();
}

async function promotedRowIsInert() {
  const { dom, d, calls } = load('shortlist.html', 'http://localhost/screener?tab=shortlisted', () => ok);
  await sleep(60);
  const promoted = d.querySelector('tr[data-symbol-row="CCC"][data-promoted] button[data-action="promote"]');
  assert(promoted && promoted.disabled, 'a promoted row has a disabled button');
  promoted.click();
  assert.strictEqual(calls.filter((c) => c.url.includes('/promote')).length, 0, 'no post from a disabled button');
  dom.window.close();
}

async function tickers() {
  let failSave = false;
  const respond = (u) => (u.includes('full-position') && failSave ? { ok: false, status: 503, json: {} } : ok);
  const { dom, d, calls } = load('tickers.html', 'http://localhost/tickers', respond);
  await sleep(60);
  const spy = d.querySelector('input[data-symbol="SPY"]'), vg = d.querySelector('input[data-symbol="VGIT"]');
  assert(!spy.closest('tr').hasAttribute('data-full-position') && vg.closest('tr').hasAttribute('data-full-position') && vg.checked);
  spy.click();
  assert(spy.closest('tr').hasAttribute('data-full-position') && spy.disabled, 'greys at once, box disabled in flight');
  await sleep(60);
  assert(!spy.disabled);
  assert.deepStrictEqual(calls.filter((c) => c.url.includes('full-position')).map((c) => c.body), [{ symbol: 'SPY', full: true }]);
  failSave = true;
  vg.click();
  await sleep(60);
  assert(vg.checked && vg.closest('tr').hasAttribute('data-full-position'), 'a failed untick is put back');
  assert(d.getElementById('full-position-error').textContent.includes('the box is back where it was'));
  const th = d.querySelector('th[data-sort-key="symbol"]');
  th.click();
  assert(th.classList.contains('sort-asc'), 'sort still works');
  dom.window.close();
}

async function addedRowFitsTheTable() {
  const { dom, d } = load('tickers.html', 'http://localhost/tickers', () => ok);
  await sleep(60);
  const form = d.querySelector('.add-ticker-form');
  const block = form.closest('.category-block');
  const input = form.querySelector('input[name="symbol"]');
  input.value = 'zzz';
  if (!form.symbol) Object.defineProperty(form, 'symbol', { value: input });  // jsdom lacks named form access
  form.dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true }));
  await sleep(3);
  const row = block.querySelector('tr[data-symbol="ZZZ"]');
  assert(row, 'a pending row is added');
  const cells = Array.from(row.children).reduce((n, c) => n + (c.colSpan || 1), 0);
  assert.strictEqual(cells, block.querySelectorAll('thead th').length, 'the pending row spans the header exactly');
  assert(row.querySelector('.verdict-cell') || row.children.length >= 4, 'a verdict cell is present');
  dom.window.close();
}


async function invested() {
  const cellHtml = (amount) => '<td class="num invested-cell">' + (amount === null ? '<span class="muted">&mdash;</span>' : '<span class="invested-amount" data-amount="' + amount.toFixed(2) + '">$' + amount + '</span>')
    + ' <button type="button" class="invested-edit" data-symbol="AAPL" aria-label="Edit invested amount for AAPL">&#9998;</button></td>';
  let mode = 'ok';
  const respond = (u) => {
    if (u.includes('/groups/') && mode === 'refresh') return { ok: true, status: 200, json: { group_html: '<div class="category-block" data-group="individual">REPLACED</div>' } };
    if (!u.includes('/api/invested')) return ok;
    if (mode === 'bad') return { ok: false, status: 400, json: { error: 'Enter an amount from 0 to 1,000,000,000.' } };
    if (mode === 'down') return { ok: false, status: 503, json: { error: 'storage error' } };
    return { ok: true, status: 200, json: { ok: true, cell_html: cellHtml(mode === 'clear' ? null : 250) } };
  };
  const { dom, d, calls } = load('invested.html', 'http://localhost/tickers', respond);
  await sleep(60);
  const cell = () => d.querySelector('td.invested-cell');
  const pen = () => d.querySelector('.invested-edit[data-symbol="AAPL"]');
  const error = d.getElementById('invested-error');
  assert(cell().textContent.includes('$100'), 'shows the stored amount');
  // cancel restores the cell
  pen().click();
  const input = () => d.querySelector('input.invested-input');
  assert(input() && input().value === '100.00', 'the editor starts at the current amount');
  assert.strictEqual(d.activeElement, input(), 'focus is in the box');
  input().dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  assert(!input() && cell().textContent.includes('$100') && pen(), 'Esc puts the cell back');
  mode = 'ok';
  // text the browser cannot parse as a number must not clear the amount
  pen().click();
  Object.defineProperty(input(), 'validity', { value: { badInput: true } });  // jsdom cannot hold unparseable text in a number box
  const before = calls.filter((c) => c.url.includes('/api/invested')).length;
  d.querySelectorAll('.invested-cell button')[0].click();
  assert.strictEqual(calls.filter((c) => c.url.includes('/api/invested')).length, before, 'unparseable text posts nothing');
  assert(input() && error.textContent.includes('Enter an amount in dollars'), 'unparseable text is refused');
  input().dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  // a group refresh must not redraw an open editor
  pen().click();
  const group = d.querySelector('.category-block[data-group="individual"]');
  mode = 'refresh';
  await dom.window.checkGroup(group);
  assert(input() && !d.body.textContent.includes('REPLACED'), 'an open editor survives a group refresh');
  mode = 'bad';
  input().dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  // a rejected amount keeps the editor open with the reason
  mode = 'bad';
  pen().click(); input().value = '-5';
  input().dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  assert(input().disabled, 'box is disabled while saving');
  await sleep(60);
  assert(input() && !input().disabled && error.textContent.includes('Enter an amount from 0'), 'a 400 keeps the editor and shows the reason');
  mode = 'down';
  d.querySelectorAll('.invested-cell button')[0].click();
  await sleep(60);
  assert(error.textContent.includes("Couldn't save the amount: storage error"), 'a 503 shows the reason');
  // a save redraws the cell from the reply and focuses the pen
  mode = 'ok';
  input().value = '250';
  d.querySelectorAll('.invested-cell button')[0].click();
  await sleep(60);
  assert(!input() && cell().textContent.includes('$250') && !error.textContent, 'saved: the cell shows the server cell');
  assert.strictEqual(d.activeElement, pen(), 'focus returns to the pen');
  const posts = calls.filter((c) => c.url.includes('/api/invested')).map((c) => c.body);
  assert.deepStrictEqual(posts[posts.length - 1], { symbol: 'AAPL', amount: 250 });
  // an empty box clears
  mode = 'clear';
  pen().click(); input().value = '';
  d.querySelectorAll('.invested-cell button')[0].click();
  await sleep(60);
  assert.deepStrictEqual(calls.filter((c) => c.url.includes('/api/invested')).pop().body, { symbol: 'AAPL', amount: null });
  assert(cell().textContent.includes('\u2014'), 'cleared cell shows a dash');
  dom.window.close();
}

async function investedKeptWhenUnreadable() {
  const group = '<div class="category-block" data-group="individual"><table><thead><tr><th class="invested-head">Invested</th></tr></thead><tbody><tr data-symbol="AAPL"><td class="num invested-cell"><span class="muted">n/a</span> <button class="invested-edit" data-symbol="AAPL" disabled>x</button></td></tr></tbody></table></div>';
  const respond = (u) => (u.includes('/groups/individual/check') ? { ok: true, status: 200, json: { group_html: group, marks_known: true, invested_known: false } } : ok);
  const { dom, d } = load('invested.html', 'http://localhost/tickers', respond);
  await sleep(100);
  assert(d.querySelector('td.invested-cell').textContent.includes('$100'), 'the amounts already showing are kept when the refresh could not read them');
  dom.window.close();
}

async function historyCard() {
  const card = fs.readFileSync(path.join(dir, 'history_card.html'), 'utf8');
  let mode = 'ok';
  const respond = (u) => {
    if (!u.includes('/api/reads/history')) return { ok: true, status: 200, json: { data_updated: false } };
    if (mode === 'expired') return { ok: false, status: 401, json: { error: 'authentication required' } };
    if (mode === 'down') return { ok: false, status: 500, json: null };
    return { ok: true, status: 200, json: { history_html: card } };
  };
  let { dom, d } = load('digest.html', 'http://localhost/', respond);
  assert(d.getElementById('history-section').textContent.includes('Loading history'), 'a placeholder shows first');
  await sleep(60);
  const visible = () => Array.from(d.querySelectorAll('.history-pane')).filter((p) => !p.hidden).map((p) => p.dataset.range);
  const pressed = () => Array.from(d.querySelectorAll('#history-section [aria-pressed="true"]')).map((b) => b.dataset.group || b.dataset.range);
  const shell = () => d.querySelector('.history-card');
  assert.deepStrictEqual(visible(), ['10y'], 'the default pane is the only one shown');
  assert.deepStrictEqual(pressed(), ['leading', '10y'], 'only Leading is shown at first');
  assert(shell().classList.contains('history-hide-coincident') && shell().classList.contains('history-hide-lagging') && !shell().classList.contains('history-hide-leading'));
  d.querySelector('button[data-group="lagging"]').click();
  assert.deepStrictEqual(pressed(), ['leading', 'lagging', '10y']);
  assert(!shell().classList.contains('history-hide-lagging') && shell().classList.contains('history-hide-coincident'), 'pressing Lagging shows only Lagging more');
  d.querySelector('button[data-group="leading"]').click();
  assert(shell().classList.contains('history-hide-leading'), 'a shown group can be hidden again');
  d.querySelector('button[data-range="all"]').click();
  assert.deepStrictEqual(visible(), ['all']);
  assert.deepStrictEqual(pressed(), ['lagging', 'all']);
  assert(d.querySelector('.history-empty').hidden, 'no hint while a group is shown');
  d.querySelector('button[data-group="lagging"]').click();
  assert(!d.querySelector('.history-empty').hidden, 'a hint shows when every group is hidden');
  d.querySelector('button[data-group="coincident"]').click();
  assert(d.querySelector('.history-empty').hidden);
  // the card reloading (after a live check) keeps the choice, though the server markup has the defaults
  dom.window.loadHistory();
  await sleep(60);
  assert.deepStrictEqual(pressed(), ['coincident', 'all'], 'the pressed buttons survive a reload');
  assert(shell().classList.contains('history-hide-leading') && shell().classList.contains('history-hide-lagging') && !shell().classList.contains('history-hide-coincident'), 'the hide classes survive a reload');
  assert.deepStrictEqual(visible(), ['all'], 'and so does the range');
  dom.window.close();
  for (const [m, text] of [['expired', 'Your session expired'], ['down', 'History is unavailable right now.']]) {
    mode = m;
    ({ dom, d } = load('digest.html', 'http://localhost/', respond));
    await sleep(60);
    assert(d.getElementById('history-section').textContent.includes(text), m + ' shows its message');
    assert(!d.querySelector('.history-pane'), m + ' draws no chart');
    dom.window.close();
  }
}

async function infoPopups() {
  const { dom, d } = load('digest.html', 'http://localhost/', () => ({ ok: true, status: 200, json: { data_updated: false } }));
  await sleep(60);
  const button = (id) => d.querySelector('.info-button[aria-controls="' + id + '"]');
  const popup = (id) => d.getElementById(id);
  assert(popup('info-lagging-read').hidden && button('info-lagging-read').getAttribute('aria-expanded') === 'false', 'closed at first');
  button('info-lagging-read').click();
  assert(!popup('info-lagging-read').hidden && button('info-lagging-read').getAttribute('aria-expanded') === 'true', 'click opens');
  assert(popup('info-lagging-read').textContent.includes('6 to 12 months'), 'the explanation names the time frame');
  button('info-leading-read').click();
  assert(!popup('info-leading-read').hidden && popup('info-lagging-read').hidden, 'opening another closes the first');
  button('info-leading-read').click();
  assert(popup('info-leading-read').hidden, 'clicking again closes');
  button('info-coincident-table').click();
  assert(!popup('info-coincident-table').hidden);
  popup('info-coincident-table').click();
  assert(!popup('info-coincident-table').hidden, 'a click inside the explanation keeps it open');
  d.body.click();
  assert(popup('info-coincident-table').hidden && button('info-coincident-table').getAttribute('aria-expanded') === 'false', 'clicking elsewhere closes');
  button('info-lagging-table').click();
  d.dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  assert(popup('info-lagging-table').hidden && d.activeElement === button('info-lagging-table'), 'Esc closes and returns focus to the button');
  dom.window.close();
}

(async () => {
  for (const mode of ['ok', '400', '503', 'html']) await promote(mode);
  await promotedRowIsInert();
  await tickers();
  await screenerSorting();
  await quotesFillTheRightCells();
  await addedRowFitsTheTable();
  await invested();
  await infoPopups();
  await historyCard();
  await checkingCue();
  await scoreSorting();
  await investedKeptWhenUnreadable();
  console.log('ok');
})().catch((e) => { console.error(e.stack || e); process.exit(1); });
