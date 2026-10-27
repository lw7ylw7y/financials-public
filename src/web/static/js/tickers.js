function hideCheckingIndicator() {
  var el = document.getElementById('checking-indicator');
  if (el) el.remove();
}

// Fetches one group's own live data and swaps its whole block in
// place -- shared by the initial background check and by the
// add-ticker handler below, which re-fires this on just the
// affected group instead of reloading the page.
function checkGroup(block) {
  var group = block.dataset.group;
  return fetch('/api/tickers/groups/' + encodeURIComponent(group) + '/check')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (!data.group_html) return;
      // An open amount editor (or a save in flight) is never redrawn under the user: this refresh is skipped.
      if (block.querySelector('.invested-input')) return;
      // When the marks could not be read the redraw has no ticks; keep the boxes already showing.
      var ticked = data.marks_known === false
        ? Array.prototype.map.call(block.querySelectorAll('.full-position:checked'), function(b) { return b.dataset.symbol; })
        : [];
      // Likewise keep the invested amounts already showing when they could not be read.
      var shown = {};
      if (data.invested_known === false) {
        block.querySelectorAll('td.invested-cell').forEach(function(cell) {
          shown[cell.closest('tr').dataset.symbol] = cell.innerHTML;
        });
      }
      block.outerHTML = data.group_html.trim();
      var fresh = document.querySelector('#ticker-groups .category-block[data-group="' + group + '"]');
      if (!fresh) return;
      fresh.querySelectorAll('.full-position').forEach(function(b) {
        if (ticked.indexOf(b.dataset.symbol) < 0) return;
        b.checked = true;
        b.closest('tr').setAttribute('data-full-position', '1');
      });
      fresh.querySelectorAll('td.invested-cell').forEach(function(cell) {
        var html = shown[cell.closest('tr').dataset.symbol];
        if (html !== undefined) cell.innerHTML = html;
      });
    });
}

var checks = [];
document.querySelectorAll('#ticker-groups .category-block[data-group]').forEach(function(block) {
  checks.push(checkGroup(block).catch(function() { /* stay on the stored snapshot already shown */ }));
});
checks.push(
  fetch('/api/market-news/check').then(function(r) { return r.json(); }).then(function(data) {
    document.getElementById('market-news').innerHTML = data.news_html;
  }).catch(function() { /* stay on the stored snapshot already shown */ })
);
Promise.allSettled(checks).then(hideCheckingIndicator);

var tickerGroups = document.getElementById('ticker-groups');
tickerGroups.addEventListener('click', function(e) {
  var th = e.target.closest('th[data-sort-key]');
  if (th) {
    var table = th.closest('table');
    var newDir = th.classList.contains('sort-asc') ? 'desc' : 'asc';
    table.querySelectorAll('th[data-sort-key]').forEach(function(other) {
      other.classList.remove('sort-asc', 'sort-desc');
    });
    th.classList.add('sort-' + newDir);
    var mult = newDir === 'asc' ? 1 : -1;
    var key = th.dataset.sortKey;
    var tbody = table.querySelector('tbody');
    var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));
    rows.sort(function(a, b) {
      if (key === 'symbol') {
        return mult * a.dataset.symbol.localeCompare(b.dataset.symbol);
      }
      var av = a.dataset.pctInRange === '' ? null : parseFloat(a.dataset.pctInRange);
      var bv = b.dataset.pctInRange === '' ? null : parseFloat(b.dataset.pctInRange);
      if (av === null && bv === null) return 0;
      if (av === null) return 1;
      if (bv === null) return -1;
      return mult * (av - bv);
    });
    rows.forEach(function(r) { tbody.appendChild(r); });
    return;
  }

  var btn = e.target.closest('.remove-ticker');
  if (!btn) return;
  var group = btn.dataset.group, symbol = btn.dataset.symbol;
  if (!confirm('Remove ' + symbol + ' from ' + group + '?')) return;

  var row = btn.closest('tr');
  var parent = row.parentNode;
  var nextRow = row.nextSibling;
  row.remove();

  fetch('/api/tickers/remove', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({group: group, symbol: symbol})
  }).then(function(r) { return r.json(); }).then(function(data) {
    if (data.error) {
      alert(data.error);
      parent.insertBefore(row, nextRow);
    }
  }).catch(function() {
    alert('Failed to remove ' + symbol + '.');
    parent.insertBefore(row, nextRow);
  });
});
// Ticking a Full Position box greys its row straight away; a failed
// save puts the box and the row back. Every box with the same symbol
// (a name in two groups) follows, so the page agrees with a reload.
tickerGroups.addEventListener('change', function(e) {
  var box = e.target.closest('.full-position');
  if (!box) return;
  var note = document.getElementById('full-position-error');
  var symbol = box.dataset.symbol, full = box.checked;
  function paint(value) {
    tickerGroups.querySelectorAll('.full-position').forEach(function(other) {
      if (other.dataset.symbol !== symbol) return;
      other.checked = value;
      var row = other.closest('tr');
      if (value) row.setAttribute('data-full-position', '1'); else row.removeAttribute('data-full-position');
    });
  }
  paint(full);
  note.textContent = '';
  box.disabled = true;
  fetch('/api/full-position', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({symbol: symbol, full: full})
  }).then(function(r) {
    if (!r.ok) throw new Error(String(r.status));
  }).catch(function() {
    paint(!full);
    note.textContent = "Couldn't save the change; the box is back where it was.";
  }).then(function() { box.disabled = false; });
});
// Invested: the pen turns the cell into a number box. Enter or Save stores the total, Esc or
// Cancel puts the cell back, and an empty box clears the amount. The cell is redrawn from the
// server's reply so what is shown is what was stored.
tickerGroups.addEventListener('click', function(e) {
  var pen = e.target.closest('.invested-edit');
  if (!pen || pen.disabled) return;
  var cell = pen.closest('td.invested-cell');
  var symbol = pen.dataset.symbol;
  var original = cell.innerHTML;
  var current = cell.querySelector('.invested-amount');
  var error = document.getElementById('invested-error');
  error.textContent = '';

  var input = document.createElement('input');
  input.type = 'number';
  input.min = '0';
  input.step = '0.01';
  input.className = 'invested-input';
  input.value = current ? current.dataset.amount : '';
  input.setAttribute('aria-label', 'Amount invested in ' + symbol);
  var save = document.createElement('button');
  save.type = 'button';
  save.textContent = 'Save';
  var cancel = document.createElement('button');
  cancel.type = 'button';
  cancel.textContent = 'Cancel';
  cell.innerHTML = '';
  cell.append(input, ' ', save, ' ', cancel);
  input.focus();

  function restore() {
    cell.innerHTML = original;
    var back = cell.querySelector('.invested-edit');
    if (back) back.focus();
  }
  function submit() {
    var raw = input.value.trim();
    // A number box reports an unparseable entry ("1e", "-") as empty; that must not clear a real total.
    if (input.validity && input.validity.badInput) { error.textContent = 'Enter an amount in dollars.'; input.focus(); return; }
    var amount = raw === '' ? null : Number(raw);
    if (amount !== null && !isFinite(amount)) { error.textContent = 'Enter an amount in dollars.'; input.focus(); return; }
    input.disabled = save.disabled = cancel.disabled = true;
    error.textContent = '';
    fetch('/api/invested', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({symbol: symbol, amount: amount})
    }).then(function(r) {
      return r.json().catch(function() { return {}; }).then(function(body) {
        if (!r.ok || !body.cell_html) { var failure = new Error('save failed'); failure.detail = body.error; throw failure; }
        cell.outerHTML = body.cell_html.trim();
        var fresh = tickerGroups.querySelector('.invested-edit[data-symbol="' + symbol + '"]');
        if (fresh) fresh.focus();
      });
    }).catch(function(failure) {
      input.disabled = save.disabled = cancel.disabled = false;
      error.textContent = "Couldn't save the amount" + (failure.detail ? ': ' + failure.detail : '.');
      input.focus();
    });
  }
  save.addEventListener('click', submit);
  cancel.addEventListener('click', function() { error.textContent = ''; restore(); });
  input.addEventListener('keydown', function(k) {
    if (k.key === 'Enter') { k.preventDefault(); submit(); }
    else if (k.key === 'Escape') { error.textContent = ''; restore(); }
  });
});
tickerGroups.addEventListener('submit', function(e) {
  var form = e.target.closest('.add-ticker-form');
  if (!form) return;
  e.preventDefault();
  var group = form.dataset.group, symbol = form.symbol.value.trim().toUpperCase();
  if (!symbol) return;
  fetch('/api/tickers/add', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({group: group, symbol: symbol})
  }).then(function(r) { return r.json(); }).then(function(data) {
    if (data.error) { alert(data.error); return; }
    form.reset();

    var block = document.querySelector('#ticker-groups .category-block[data-group="' + group + '"]');
    if (!block) return;
    var tbody = block.querySelector('tbody');
    var alreadyShown = tbody.querySelector('tr[data-symbol="' + symbol + '"]');
    if (!alreadyShown) {
      var row = document.createElement('tr');
      row.dataset.symbol = symbol;
      row.dataset.pctInRange = '';

      var symbolCell = document.createElement('td');
      symbolCell.textContent = symbol;
      var loadingCell = document.createElement('td');
      var hasInvested = !!block.querySelector('th.invested-head');
      loadingCell.colSpan = block.querySelectorAll('thead th').length - (hasInvested ? 5 : 4);
      loadingCell.className = 'muted';
      loadingCell.textContent = 'Loading…';
      var verdictCell = document.createElement('td');
      verdictCell.className = 'verdict-cell muted';
      verdictCell.innerHTML = '&mdash;';
      var investedCell = null;
      if (hasInvested) {
        investedCell = document.createElement('td');
        investedCell.className = 'num invested-cell muted';
        investedCell.innerHTML = '&mdash;';
      }
      var fullCell = document.createElement('td');
      fullCell.className = 'full-cell';
      var fullBox = document.createElement('input');
      fullBox.type = 'checkbox';
      fullBox.className = 'full-position';
      fullBox.dataset.symbol = symbol;
      fullBox.setAttribute('aria-label', 'Full position in ' + symbol);
      fullCell.appendChild(fullBox);
      var removeCell = document.createElement('td');
      var removeBtn = document.createElement('button');
      removeBtn.type = 'button';
      removeBtn.className = 'remove-ticker';
      removeBtn.dataset.group = group;
      removeBtn.dataset.symbol = symbol;
      removeBtn.title = 'Remove ' + symbol + ' from ' + group;
      removeBtn.setAttribute('aria-label', 'Remove ' + symbol);
      removeBtn.textContent = '×';
      removeCell.appendChild(removeBtn);

      row.appendChild(symbolCell);
      row.appendChild(loadingCell);
      row.appendChild(verdictCell);
      if (investedCell) row.appendChild(investedCell);
      row.appendChild(fullCell);
      row.appendChild(removeCell);
      tbody.appendChild(row);
    }

    // Re-check just this group so the new ticker (and everything
    // else in it) gets real data -- no full page reload needed.
    checkGroup(block).catch(function() { /* leave the pending row as-is */ });
  }).catch(function() { alert('Failed to add ' + symbol + '.'); });
});

// A verdict tip is position:fixed so the scrolling table block cannot clip it; it is placed
// under its pill (above when there is no room below) and kept inside the window. Escape hides
// it until the pointer or focus comes back.
function placeVerdictTip(wrap) {
  var tip = wrap.querySelector('.verdict-tip');
  if (!tip) return;
  wrap.classList.remove('dismissed');
  var r = wrap.getBoundingClientRect();
  var width = Math.min(300, window.innerWidth - 16);
  tip.style.left = Math.max(8, Math.min(r.left, window.innerWidth - width - 8)) + 'px';
  var below = r.bottom + 4;
  tip.style.top = below + 'px';
  if (below + tip.offsetHeight > window.innerHeight && r.top - 4 - tip.offsetHeight > 0) {
    tip.style.top = (r.top - 4 - tip.offsetHeight) + 'px';
  }
}
document.addEventListener('mouseover', function(e) {
  var wrap = e.target.closest && e.target.closest('.verdict-wrap');
  if (wrap) placeVerdictTip(wrap);
});
document.addEventListener('focusin', function(e) {
  var wrap = e.target.closest && e.target.closest('.verdict-wrap');
  if (wrap) placeVerdictTip(wrap);
});
document.addEventListener('keydown', function(e) {
  if (e.key !== 'Escape') return;
  document.querySelectorAll('.verdict-wrap').forEach(function(w) { w.classList.add('dismissed'); });
});
