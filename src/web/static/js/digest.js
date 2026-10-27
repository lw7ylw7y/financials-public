function hideCheckingIndicator() {
  var el = document.getElementById('checking-indicator');
  if (el) el.remove();
}
fetch('/api/check').then(function(r) { return r.json(); }).then(function(data) {
  hideCheckingIndicator();
  if (!data.data_updated) return;
  document.getElementById('table-section').innerHTML = data.table_html;
  document.getElementById('countdown-section').innerHTML = data.countdown_html;
  if (data.ai_html) {
    document.getElementById('ai-section').innerHTML = data.ai_html;
  }
  loadHistory();  // the latest saved read may have changed with the tiles
}).catch(function() { hideCheckingIndicator(); /* stay on the stored snapshot already shown */ });

// The "Reads over time" card comes from its own request, so the page's first paint does not
// wait for the saved history. The chosen view and range survive a reload of the card.
var historyChoice = {range: '10y', shown: {leading: true, coincident: false, lagging: false}};
var HISTORY_CARD = '<section class="card history-card"><div class="history-head"><p class="category-label">Reads over time</p></div>';
function showHistoryChoice() {
  var section = document.getElementById('history-section');
  section.querySelectorAll('[data-group][aria-pressed]').forEach(function(b) {
    b.setAttribute('aria-pressed', historyChoice.shown[b.dataset.group] ? 'true' : 'false');
  });
  var card = section.querySelector('.history-card');
  if (card) Object.keys(historyChoice.shown).forEach(function(g) {
    card.classList.toggle('history-hide-' + g, !historyChoice.shown[g]);
  });
  var hint = section.querySelector('.history-empty');
  if (hint) hint.hidden = Object.keys(historyChoice.shown).some(function(g) { return historyChoice.shown[g]; });
  section.querySelectorAll('[data-range][aria-pressed]').forEach(function(b) {
    b.setAttribute('aria-pressed', b.dataset.range === historyChoice.range ? 'true' : 'false');
  });
  section.querySelectorAll('.history-pane').forEach(function(pane) {
    pane.hidden = pane.dataset.range !== historyChoice.range;
  });
}
var historyRequest = 0;
function loadHistory() {
  var section = document.getElementById('history-section');
  if (!section) return;
  var mine = ++historyRequest;  // a slower, older answer must not overwrite a newer one
  fetch('/api/reads/history').then(function(r) {
    if (r.status === 401) return {expired: true};
    return r.json();
  }).then(function(data) {
    if (mine !== historyRequest) return;
    if (data.expired) {
      section.innerHTML = HISTORY_CARD + '<p class="muted" role="status">Your session expired. <a href="/login">Sign in again.</a></p></section>';
    } else if (data.history_html) {
      section.innerHTML = data.history_html;
      showHistoryChoice();
    }
  }).catch(function() {
    if (mine !== historyRequest) return;
    section.innerHTML = HISTORY_CARD + '<p class="muted" role="status">History is unavailable right now.</p></section>';
  });
}
document.addEventListener('click', function(e) {
  var button = e.target.closest('#history-section button[data-group], #history-section button[data-range]');
  if (!button) return;
  if (button.dataset.group) historyChoice.shown[button.dataset.group] = !historyChoice.shown[button.dataset.group];
  if (button.dataset.range) historyChoice.range = button.dataset.range;
  showHistoryChoice();
});
loadHistory();

// The (i) beside a group label opens its explanation; clicking it again, pressing Esc or
// clicking elsewhere closes it. Delegated on the document because the live check replaces
// the sections' markup.
function closeInfo(except) {
  document.querySelectorAll('.info-button[aria-expanded="true"]').forEach(function(button) {
    if (button === except) return;
    button.setAttribute('aria-expanded', 'false');
    document.getElementById(button.getAttribute('aria-controls')).hidden = true;
  });
}
document.addEventListener('click', function(e) {
  if (e.target.closest('.info-popup')) return;  // text inside an open explanation can be selected
  var button = e.target.closest('.info-button');
  if (!button) { closeInfo(null); return; }
  var popup = document.getElementById(button.getAttribute('aria-controls'));
  var open = button.getAttribute('aria-expanded') === 'true';
  closeInfo(button);
  button.setAttribute('aria-expanded', open ? 'false' : 'true');
  popup.hidden = open;
});
document.addEventListener('keydown', function(e) {
  if (e.key !== 'Escape') return;
  var open = document.querySelector('.info-button[aria-expanded="true"]');
  closeInfo(null);
  if (open) open.focus();
});
