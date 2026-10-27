(function () {
  var panel = document.getElementById('filters-panel');
  var toggle = document.getElementById('filters-toggle');
  var apply = document.getElementById('filters-apply');
  var preview = document.getElementById('filters-preview');
  var inputs = Array.prototype.slice.call(panel.querySelectorAll('input[data-field]'));
  var defaults = JSON.parse(panel.dataset.defaults);
  var sequence = 0;
  var timer = null;
  var invalid = false;
  function announceApplied() {
    var shown = null;
    try { shown = sessionStorage.getItem('screenerFiltersApplied'); sessionStorage.removeItem('screenerFiltersApplied'); } catch (e) {}
    if (shown !== null) document.getElementById('announce').textContent = 'Filters applied. ' + shown + ' names shown.';
  }
  function readForm() {
    var form = {};
    inputs.forEach(function (input) {
      var entry = form[input.dataset.field] = form[input.dataset.field] || {};
      if (input.dataset.part === 'on') entry.on = input.checked;
      else entry.value = input.value === '' ? null : Number(input.value);
    });
    return form;
  }
  var saved = JSON.stringify(readForm());
  function syncSwitches() {
    inputs.forEach(function (input) {
      if (input.dataset.part !== 'on') return;
      var row = input.closest('.filter-row');
      row.querySelectorAll('input[data-part="value"]').forEach(function (number) { number.disabled = !input.checked; });
    });
  }
  function showErrors(errors) {
    inputs.forEach(function (input) {
      if (input.dataset.part !== 'value') return;
      var message = errors[input.dataset.field] || '';
      document.getElementById('err-' + input.dataset.field).textContent = message;
      input.setAttribute('aria-invalid', message ? 'true' : 'false');
    });
    invalid = Object.keys(errors).length > 0;
  }
  function refreshApply() {
    apply.disabled = invalid || JSON.stringify(readForm()) === saved;
  }
  function post(url, body) {
    return fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      .then(function (res) {
        return res.json().then(function (json) { return { status: res.status, body: json }; });
      });
  }
  function runPreview() {
    var ticket = ++sequence;
    preview.textContent = 'Counting…';
    post('/api/screener/settings/preview', { settings: readForm() }).then(function (res) {
      if (ticket !== sequence) return;
      if (res.status === 400 && res.body.errors) {
        showErrors(res.body.errors);
        preview.textContent = '';
      } else if (res.status === 200) {
        showErrors({});
        preview.textContent = 'With these settings: ' + res.body.would_show + ' names (now ' + res.body.now + ').' +
          (res.body.fetch_tonight ? ' ' + res.body.fetch_tonight + ' more names will be fetched tonight.' : '');
      } else {
        throw new Error(String(res.status));
      }
      refreshApply();
    }).catch(function () {
      if (ticket !== sequence) return;
      preview.textContent = "Couldn't count. Apply will still work.";
      refreshApply();
    });
  }
  function changed() {
    syncSwitches();
    refreshApply();
    clearTimeout(timer);
    timer = setTimeout(runPreview, 300);
  }
  inputs.forEach(function (input) { input.addEventListener('input', changed); input.addEventListener('change', changed); });
  toggle.addEventListener('click', function () {
    var open = panel.hidden;
    panel.hidden = !open;
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    toggle.innerHTML = open ? 'Filters &#9662;' : 'Filters &#9656;';
  });
  document.getElementById('filters-reset').addEventListener('click', function () {
    inputs.forEach(function (input) {
      var entry = defaults[input.dataset.field];
      if (input.dataset.part === 'on') input.checked = entry.on;
      else input.value = entry.value;
    });
    changed();
  });
  apply.addEventListener('click', function () {
    apply.disabled = true;
    post('/api/screener/settings', { settings: readForm() }).then(function (res) {
      if (res.status === 400 && res.body.errors) {
        showErrors(res.body.errors);
        preview.textContent = '';
        refreshApply();
        return;
      }
      if (res.status !== 200) throw new Error(String(res.status));
      if (res.body.shown !== null) { try { sessionStorage.setItem('screenerFiltersApplied', String(res.body.shown)); } catch (e) {} }
      window.location.reload();
    }).catch(function () {
      preview.textContent = "Couldn't save the filters. Nothing was changed.";
      refreshApply();
    });
  });
  syncSwitches();
  announceApplied();
})();
