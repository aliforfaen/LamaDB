// Page: Events
(function() {
  'use strict';

  window.eventsFilters = { source: '', severity: '', limit: 20, consolidate: true };

  window.loadEvents = async function() {
    try {
      var params = new URLSearchParams();
      if (window.eventsFilters.source) params.set('source', window.eventsFilters.source);
      if (window.eventsFilters.severity) params.set('severity', window.eventsFilters.severity);
      params.set('limit', window.eventsFilters.limit);
      if (window.eventsFilters.consolidate) params.set('consolidate', 'true');
      var data = await window.api('/api/events?' + params.toString());
      renderEventsTable(data);
    } catch (e) {
      console.error('[LamaDB] Events error:', e);
      window.showError('Failed to load events: ' + e.message);
    }
  };

  function stripAnsi(str) {
    if (!str) return '';
    return str.replace(/\x1b\[[0-9;]*m/g, '').replace(/\[\[[0-9;]*m/g, '');
  }

  function renderEventsTable(events) {
    var tbody = document.getElementById('events-tbody');
    if (!tbody) return;
    if (!events || events.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" style="color:var(--muted);text-align:center;padding:20px;">No events found</td></tr>';
      return;
    }
    tbody.innerHTML = events.map(function(ev) {
      var sev = ev.severity || 'info';
      var sevClass = sev === 'critical' ? 'critical' : sev === 'warn' ? 'warn' : 'info';
      var ts = ev.ts ? new Date(ev.ts).toLocaleString('en-US', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }) : '';
      var bodyPreview = ev.body ? ev.body.substring(0, 80) : '';
      var meta = ev.metadata || {};
      var metaStr = JSON.stringify(meta, null, 2);
      var done = ev.processed ? 'checked' : '';
      // Consolidation: when count > 1, show "Title (×N)" badge
      var count = ev.count || 1;
      var titleHtml = stripAnsi(ev.title || '');
      if (count > 1) {
        titleHtml += ' <span class="sev-badge warn" title="' + count + ' similar events in the last hour" style="font-weight:600;">×' + count + '</span>';
      }
      return '<tr class="row-expand" onclick="toggleEventRow(this)">' +
        '<td class="mono nowrap">' + ts + '</td>' +
        '<td class="nowrap">' + (ev.source || '') + '</td>' +
        '<td class="mono nowrap">' + (ev.type || '') + '</td>' +
        '<td><span class="sev-badge ' + sevClass + '">' + sev + '</span></td>' +
        '<td class="truncate-cell" title="' + stripAnsi(ev.title || '') + '">' + titleHtml + '</td>' +
        '<td class="truncate-cell" title="' + stripAnsi(bodyPreview) + '">' + stripAnsi(bodyPreview) + '</td>' +
        '<td><input type="checkbox" ' + done + ' onclick="event.stopPropagation();" /></td>' +
      '</tr>' +
      '<tr class="row-detail">' +
        '<td colspan="7"><pre>' + metaStr + '</pre></td>' +
      '</tr>';
    }).join('');
  }

  document.querySelectorAll('#page-events .filter-bar select, #page-events .filter-bar input').forEach(function(el) {
    el.addEventListener('change', function() {
      var selects = document.querySelectorAll('#page-events .filter-bar select');
      window.eventsFilters.source = selects[0].value;
      window.eventsFilters.severity = selects[1].value;
      var rowsSelect = document.querySelector('#page-events .rows-selector select');
      window.eventsFilters.limit = rowsSelect ? parseInt(rowsSelect.value, 10) : 20;
      window.loadEvents();
    });
  });

  // Wire up the consolidation toggle (added by index.html).
  // The toggle has id `events-consolidate-toggle` and is in the events filter bar.
  document.addEventListener('change', function(e) {
    if (e.target && e.target.id === 'events-consolidate-toggle') {
      window.eventsFilters.consolidate = !!e.target.checked;
      window.loadEvents();
    }
  });
})();
