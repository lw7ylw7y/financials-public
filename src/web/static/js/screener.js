var QUOTE_BATCH = 25;
var QUOTE_FIRST_CELL = 2;  // after Ticker and Score
var QUOTE_TIMEOUT_MS = 60000;  // a batch that has not answered by then counts as failed
function notePrices(html) {
  var el = document.getElementById('prices-note');
  if (el) el.innerHTML = html;
}
function placeQuote(row, entry) {
  var cells = row.children;
  var tmp = document.createElement('table');
  tmp.innerHTML = '<tbody><tr>' + entry.html + '</tr></tbody>';
  var fresh = tmp.querySelector('tr').children;
  for (var i = 0; i < 4; i++) cells[QUOTE_FIRST_CELL + i].replaceWith(fresh[0]);
  row.dataset.pctinrange = entry.pct_in_range == null ? '' : entry.pct_in_range;
  row.dataset.change = entry.change_percent == null ? '' : entry.change_percent;
}
function failBatch(rows, status) {
  rows.forEach(function (row) {
    for (var i = 0; i < 4; i++) {
      var cell = row.children[QUOTE_FIRST_CELL + i];
      cell.className = i === 2 ? 'muted' : 'num muted';
      cell.textContent = 'n/a';
    }
  });
  notePrices(status === 401
    ? 'Your session expired. <a href="/login">Sign in again.</a>'
    : "Prices couldn't be loaded. Reload to try again.");
}
function hideCheckingIndicator() {
  var el = document.getElementById('checking-indicator');
  if (el) el.remove();
}
var batchesLeft = 0;
function batchSettled() {
  batchesLeft -= 1;
  if (batchesLeft <= 0) hideCheckingIndicator();
}
function fetchBatch(rows) {
  var symbols = rows.map(function (r) { return r.dataset.symbolRow; }).join(',');
  var controller = typeof AbortController === 'function' ? new AbortController() : null;
  var timer = setTimeout(function () { if (controller) controller.abort(); }, QUOTE_TIMEOUT_MS);
  // Whatever happens, the batch ends: the "checking" cue must not outlive a failure handler that throws.
  function settle() { clearTimeout(timer); batchSettled(); }
  fetch('/api/screener/quotes?symbols=' + encodeURIComponent(symbols), controller ? {signal: controller.signal} : undefined)
    .then(function (res) {
      if (!res.ok) { failBatch(rows, res.status); return null; }
      return res.json();
    })
    .then(function (body) {
      if (!body) return;
      rows.forEach(function (row) {
        var entry = body.quotes[row.dataset.symbolRow];
        if (entry) placeQuote(row, entry);
      });
    })
    .catch(function () { failBatch(rows, 0); })
    .then(settle, settle);
}
var quoteRows = Array.prototype.slice.call(document.querySelectorAll('tr[data-quote-row]'));
batchesLeft = Math.ceil(quoteRows.length / QUOTE_BATCH);
if (!batchesLeft) hideCheckingIndicator();
for (var i = 0; i < quoteRows.length; i += QUOTE_BATCH) fetchBatch(quoteRows.slice(i, i + QUOTE_BATCH));

function sortValue(row, key, numeric) {
  var v = row.dataset[key.toLowerCase()];
  if (v === undefined || v === '') return null;
  return numeric ? parseFloat(v) : v;
}
// The whole header cell sorts, not only the label button: the arrow beside the label is part of
// the cell. A key press on the button reaches this listener as a click on the cell.
document.querySelectorAll('th.sortable').forEach(function (th) {
  th.addEventListener('click', function () {
    var key = th.dataset.sortKey;
    var numeric = th.classList.contains('num');
    var wasAsc = th.getAttribute('aria-sort') === 'ascending';
    var wasDesc = th.getAttribute('aria-sort') === 'descending';
    var descending = wasAsc;
    document.querySelectorAll('th.sortable').forEach(function (other) { other.setAttribute('aria-sort', 'none'); });
    th.setAttribute('aria-sort', descending ? 'descending' : 'ascending');
    var announce = document.getElementById('announce');
    if (announce) announce.textContent = 'Sorted by ' + th.textContent.trim() + ', ' + (descending ? 'descending' : 'ascending');
    var tbody = th.closest('table').tBodies[0];
    var pairs = Array.prototype.slice.call(tbody.querySelectorAll('tr.screener-row')).map(function (row) {
      return { row: row, detail: row.nextElementSibling, value: sortValue(row, key, numeric) };
    });
    pairs.sort(function (a, b) {
      if (a.value === null && b.value === null) return 0;
      if (a.value === null) return 1;
      if (b.value === null) return -1;
      var order = numeric ? a.value - b.value : String(a.value).localeCompare(String(b.value));
      return descending ? -order : order;
    });
    pairs.forEach(function (p) { tbody.appendChild(p.row); tbody.appendChild(p.detail); });
  });
});
document.querySelectorAll('button.disclose').forEach(function (button) {
  button.addEventListener('click', function () {
    var detail = document.getElementById(button.getAttribute('aria-controls'));
    var open = detail.hidden;
    detail.hidden = !open;
    button.setAttribute('aria-expanded', open ? 'true' : 'false');
    button.firstElementChild.innerHTML = open ? '&#9662;' : '&#9656;';
  });
});
document.addEventListener('keydown', function (event) {
  if (event.key !== 'Escape') return;
  document.querySelectorAll('tr.detail-row:not([hidden])').forEach(function (detail) {
    detail.hidden = true;
    var button = document.querySelector('button.disclose[aria-controls="' + detail.id + '"]');
    button.setAttribute('aria-expanded', 'false');
    button.firstElementChild.innerHTML = '&#9656;';
  });
});
var table = document.querySelector('table.screener-table');
var currentTab = table ? table.dataset.tab : null;
var toast = document.getElementById('toast');
var toastTimer = null;
var undoAction = null;
var MAX_NOTE = 2000;

// A moved row that is due for review also moves the "n due" count.
function bumpDue(tab, delta) {
  var link = document.querySelector('a[data-tab="' + tab + '"]');
  if (!link) return;
  var holder = link.querySelector('.tab-due');
  var count = holder.querySelector('.tab-due-count');
  var next = Math.max(0, (count ? parseInt(count.textContent, 10) : 0) + delta);
  holder.innerHTML = next ? ' &middot; <span class="tab-due-count">' + next + '</span> due' : '';
}
function bumpCount(tab, delta, row) {
  if (row && row.hasAttribute('data-review-due') && tab !== 'new') bumpDue(tab, delta);
  var link = document.querySelector('a[data-tab="' + tab + '"] .tab-count');
  if (link) link.textContent = Math.max(0, parseInt(link.textContent, 10) + delta);
  if (tab === 'new' && tab === currentTab) {
    var shown = document.getElementById('shown-count');
    if (shown) shown.textContent = Math.max(0, parseInt(shown.textContent, 10) + delta);
  }
}
function showToast(text, undo, seconds) {
  clearTimeout(toastTimer);
  toast.textContent = text;
  undoAction = undo || null;
  if (undo) {
    var button = document.createElement('button');
    button.type = 'button';
    button.textContent = 'Undo';
    button.addEventListener('click', undo);
    toast.appendChild(button);
  }
  toast.hidden = false;
  toastTimer = setTimeout(hideToast, seconds * 1000);
}
function hideToast() {
  clearTimeout(toastTimer);
  toast.hidden = true;
  undoAction = null;
}
function post(url, body) {
  return fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    .then(function (res) {
      if (!res.ok) throw new Error(String(res.status));
      return res.json();
    });
}
function setHidden(row, hidden) {
  row.hidden = hidden;
  row.nextElementSibling.hidden = true;
}
function visibleRows() {
  return Array.prototype.slice.call(table.querySelectorAll('tr.screener-row')).filter(function (r) { return !r.hidden; });
}
function focusAfter(row) {
  var rows = visibleRows();
  var index = rows.indexOf(row);
  var target = rows[index + 1] || rows[index - 1];
  var button = target && target.querySelector('[data-action]');
  (button || document.querySelector('.screener-tabs a')).focus();
}
function updateImprovedLine() {
  var line = document.getElementById('improved-line');
  if (!line) return;
  var n = visibleRows().filter(function (r) { return r.querySelector('.improved-flag'); }).length;
  line.hidden = n === 0;
  line.textContent = n === 1 ? '1 dismissed name has improved since you dismissed it.'
    : n + ' dismissed names have improved since you dismissed them.';
}
var EMPTY_TEXT = {
  'new': 'Nothing left to review.',
  'shortlisted': 'Nothing shortlisted yet.',
  'dismissed': 'Nothing dismissed.'
};
function announce(text) {
  document.getElementById('announce').textContent = text;
}
function syncEmpty() {
  var block = table.closest('.category-block');
  var note = document.getElementById('list-empty');
  var none = visibleRows().length === 0;
  block.hidden = none;
  if (none && !note) {
    note = document.createElement('p');
    note.id = 'list-empty';
    note.className = 'empty';
    note.textContent = EMPTY_TEXT[currentTab];
    block.parentNode.insertBefore(note, block.nextSibling);
  }
  if (!none && note) note.remove();
}
function firstAction(row) {
  var button = row.querySelector('[data-action]');
  if (button) button.focus();
}
// Moves a row out of this list straight away and tells the server. The
// New count only rises when the server says the row belongs in New
// (a cleared name that fails a filter or needs a data check does not).
function moveRow(row, status) {
  var symbol = row.dataset.symbolRow;
  var from = currentTab;
  var move = { rolledBack: false };
  setHidden(row, true);
  bumpCount(from, -1, row);
  if (status !== 'new') bumpCount(status, 1, row);
  updateImprovedLine();
  syncEmpty();
  move.request = post('/api/screener/status', { symbol: symbol, status: status }).then(function (body) {
    if (status === 'new' && body.lands === 'new') bumpCount('new', 1);
    return body;
  });
  move.request.catch(function () {
    move.rolledBack = true;
    setHidden(row, false);
    bumpCount(from, 1, row);
    if (status !== 'new') bumpCount(status, -1, row);
    updateImprovedLine();
    syncEmpty();
    showToast("Couldn't save the change; the row is back where it was.", null, 8);
    firstAction(row);
  });
  return move;
}
function undoDismissal(row, symbol, previous, move) {
  hideToast();
  move.request.then(function () {
    return post('/api/screener/status', { symbol: symbol, status: previous }).then(function (body) {
      bumpCount('dismissed', -1, row);
      if (previous !== 'new' || body.lands === 'new') {
        setHidden(row, false);
        bumpCount(previous, 1, row);
        updateImprovedLine();
        syncEmpty();
        firstAction(row);
      }
    }, function () {
      showToast("Couldn't undo the dismissal. Open the Dismissed list to restore it.", null, 8);
    });
  }, function () { /* the dismissal failed and was already rolled back */ });
}
if (table) {
  table.addEventListener('click', function (event) {
    var button = event.target.closest('button[data-action]');
    if (!button || button.dataset.action === 'save-note' || button.dataset.action === 'promote') return;
    var row = button.closest('tr.screener-row');
    if (!row) return;
    var status = button.dataset.action;
    var symbol = row.dataset.symbolRow;
    var previous = currentTab;
    focusAfter(row);
    var move = moveRow(row, status);
    if (status === 'dismissed') {
      showToast('Dismissed ' + symbol + '. ', function () { undoDismissal(row, symbol, previous, move); }, 10);
    } else {
      hideToast();
      move.request.then(function () {
        var said = status === 'shortlisted' ? ' shortlisted' : (previous === 'dismissed' ? ' restored to New' : ' moved to New');
        announce(symbol + said);
      }, function () {});
    }
  });
}
// Promote adds the symbol to the Ticker Dashboard's Individual table and greys the row at
// once; a failed save puts the button and the row back. Every other Promote button is
// disabled while the request runs, because two quick promotes could overwrite each other's
// write to the group.
if (table) {
  table.addEventListener('click', function (event) {
    var button = event.target.closest('button[data-action="promote"]');
    if (!button || button.disabled) return;
    var row = button.closest('tr.screener-row');
    var symbol = row.dataset.symbolRow;
    var label = button.innerHTML;
    var tooltip = button.title;
    var others = Array.prototype.slice.call(table.querySelectorAll('button[data-action="promote"]:not([disabled])'));
    function paint(promoted) {
      if (promoted) row.setAttribute('data-promoted', '1'); else row.removeAttribute('data-promoted');
      button.disabled = promoted;
      button.innerHTML = promoted ? 'Promoted &#10003;' : label;
      button.title = promoted ? button.dataset.promotedTitle : tooltip;
    }
    others.forEach(function (other) { other.disabled = true; });
    paint(true);
    var dismiss = row.querySelector('[data-action="dismissed"]');
    if (dismiss) dismiss.focus();
    fetch('/api/screener/promote', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol: symbol }) })
      .then(function (res) {
        return res.json().catch(function () { return {}; }).then(function (body) {
          if (!res.ok) { var failure = new Error('promote failed'); failure.detail = body.error; throw failure; }
        });
      }).then(function () {
        announce(symbol + ' promoted to the watchlist');
      }, function (failure) {
        paint(false);
        showToast("Couldn't add " + symbol + " to the watchlist" + (failure.detail ? ': ' + failure.detail : '.'), null, 8);
        if (!failure.detail && button.focus) button.focus();
      }).then(function () {
        others.forEach(function (other) { if (other !== button || !row.hasAttribute('data-promoted')) other.disabled = false; });
      });
  });
}
document.addEventListener('keydown', function (event) {
  var active = document.activeElement;
  var typing = active && (active.tagName === 'TEXTAREA' || active.tagName === 'INPUT' || active.tagName === 'SELECT' || active.isContentEditable);
  if ((event.key === 'u' || event.key === 'U') && undoAction && !typing && !event.ctrlKey && !event.metaKey && !event.altKey) {
    undoAction();
  }
});

function refreshNote(area) {
  var block = area.closest('.note-block');
  var save = block.querySelector('[data-action="save-note"]');
  var state = block.querySelector('.note-state');
  var length = area.value.length;
  var dirty = area.value !== area._saved;
  var tooLong = length > MAX_NOTE;
  save.disabled = !dirty || tooLong || area._saving;
  if (tooLong) state.textContent = 'That note is too long (max 2,000 characters).';
  else if (dirty) state.textContent = 'Unsaved changes' + (length >= 1900 ? ' · ' + length.toLocaleString() + ' / 2,000' : '');
  else state.textContent = '';
}
document.querySelectorAll('textarea.note-field').forEach(function (area) {
  area._saved = area.defaultValue;
  area.addEventListener('input', function () { refreshNote(area); });
  var block = area.closest('.note-block');
  block.querySelector('[data-action="save-note"]').addEventListener('click', function () {
    var save = this;
    var state = block.querySelector('.note-state');
    var text = area.value;
    area._saving = true;
    save.disabled = true;
    state.textContent = 'Saving…';
    post('/api/screener/note', { symbol: area.dataset.symbol, text: text }).then(function () {
      area._saved = text;
      area._saving = false;
      var flag = document.querySelector('tr[data-symbol-row="' + area.dataset.symbol + '"] .note-flag');
      if (flag) flag.hidden = !text.trim();
      refreshNote(area);
      if (area.value === text) state.textContent = 'Saved';
    }).catch(function () {
      area._saving = false;
      refreshNote(area);
      state.textContent = 'Not saved. Retry';
    });
  });
});
window.addEventListener('beforeunload', function (event) {
  var dirty = Array.prototype.some.call(document.querySelectorAll('textarea.note-field'), function (a) {
    return a.value !== a._saved;
  });
  if (dirty) { event.preventDefault(); event.returnValue = ''; }
});
