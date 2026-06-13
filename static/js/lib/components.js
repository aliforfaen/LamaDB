// ─── LamaDB Dashboard Shared UI Components ──────────────────────────
(function() {
  'use strict';

  // ─── HTML escaping ──────────────────────────────────────────────────────────
  window.escHtml = function(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  };

  window.escAttr = function(str) {
    if (!str) return '';
    return String(str).replace(/'/g, '&#39;').replace(/"/g, '&quot;');
  };

  // ─── Relative time helper ──────────────────────────────────────────────────
  window.relativeTime = function(isoStr) {
    if (isoStr == null || isoStr === '') return '<span style="color:var(--muted);">Never</span>';
    var date;
    if (typeof isoStr === 'number') {
      // Unix timestamp: detect seconds vs milliseconds
      date = new Date(isoStr < 1e12 ? isoStr * 1000 : isoStr);
    } else {
      date = new Date(isoStr);
    }
    if (isNaN(date.getTime())) return '<span style="color:var(--muted);">\u2014</span>';
    // Guard against epoch dates that produce "57y ago" — reject dates before 2000
    if (date.getTime() < Date.UTC(2000, 0, 1)) return '<span style="color:var(--muted);">\u2014</span>';
    var now = new Date();
    var diffMs = now - date;
    var diffSec = Math.floor(diffMs / 1000);
    if (diffSec < 60) return 'just now';
    var diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return diffMin + 'm ago';
    var diffHr = Math.floor(diffMin / 60);
    if (diffHr < 24) return diffHr + 'h ago';
    var diffDay = Math.floor(diffHr / 24);
    if (diffDay < 30) return diffDay + 'd ago';
    var diffMonth = Math.floor(diffDay / 30);
    if (diffMonth < 12) return diffMonth + 'mo ago';
    return Math.floor(diffMonth / 12) + 'y ago';
  };

  // ─── Toast system ──────────────────────────────────────────────────────────
  var _toastTimers = {};

  window.showToast = function(msg, actionLabel, actionCallback, duration) {
    var container = document.getElementById('toast-container');
    if (!container) return;
    duration = duration || 5000;
    var toast = document.createElement('div');
    toast.className = 'toast';
    var msgSpan = document.createElement('span');
    msgSpan.className = 'toast-msg';
    msgSpan.textContent = msg;
    toast.appendChild(msgSpan);
    if (actionLabel && actionCallback) {
      var btn = document.createElement('button');
      btn.className = 'toast-btn';
      btn.textContent = actionLabel;
      btn.onclick = function() {
        actionCallback();
        toast.classList.add('toast-out');
        setTimeout(function() { toast.remove(); }, 300);
        clearTimeout(_toastTimers[toast]);
        delete _toastTimers[toast];
      };
      toast.appendChild(btn);
    }
    container.appendChild(toast);
    _toastTimers[toast] = setTimeout(function() {
      toast.classList.add('toast-out');
      setTimeout(function() { toast.remove(); }, 300);
      delete _toastTimers[toast];
    }, duration);
  };

  // ─── Confirm dialog ────────────────────────────────────────────────────────
  var _confirmCallback = null;

  window.showConfirm = function(title, message, icon, callback) {
    document.getElementById('confirm-title').textContent = title;
    document.getElementById('confirm-message').textContent = message;
    document.getElementById('confirm-icon').textContent = icon || '⚠';
    _confirmCallback = callback;
    document.getElementById('modal-confirm').classList.add('open');
  };

  window.confirmAction = function() {
    window.closeModal('modal-confirm');
    if (_confirmCallback) {
      _confirmCallback();
      _confirmCallback = null;
    }
  };

  // ─── Rows per page selector ────────────────────────────────────────────────
  window.injectRowsSelector = function() {
    var filterBar = document.querySelector('#page-events .filter-bar');
    if (!filterBar) return;
    var existing = filterBar.querySelector('.rows-selector');
    if (existing) return;
    var div = document.createElement('div');
    div.className = 'rows-selector';
    div.innerHTML = '<span>Rows:</span>' +
      '<select id="rows-per-page">' +
        '<option value="20" selected>20</option>' +
        '<option value="50">50</option>' +
        '<option value="100">100</option>' +
      '</select>';
    filterBar.appendChild(div);
    document.getElementById('rows-per-page').addEventListener('change', function() {
      if (window.eventsFilters) {
        window.eventsFilters.limit = parseInt(this.value, 10);
      }
      if (window.loadEvents) window.loadEvents();
    });
  };

  // ─── Mobile table data-label helper ──────────────────────────────────────────
  window.labelMobileTables = function() {
    document.querySelectorAll('.table-wrap table').forEach(function(table) {
      var headers = [];
      var thead = table.querySelector('thead tr');
      if (thead) {
        thead.querySelectorAll('th').forEach(function(th) {
          headers.push(th.textContent.trim());
        });
      }
      if (headers.length === 0) return;
      table.querySelectorAll('tbody tr').forEach(function(tr) {
        tr.querySelectorAll('td').forEach(function(td, i) {
          if (i < headers.length && !td.hasAttribute('data-label')) {
            td.setAttribute('data-label', headers[i]);
          }
        });
      });
    });
  };

  // ─── Tag input handler ──────────────────────────────────────────────────────
  window.handleTagInput = function(e, containerId) {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      var input = e.target;
      var val = input.value.trim().replace(/,/g, '');
      if (!val) return;
      var wrap = document.getElementById(containerId);
      var tag = document.createElement('span');
      tag.className = 'tag-pill';
      var rem = document.createElement('span');
      rem.className = 'remove';
      rem.textContent = '\u00d7';
      rem.onclick = function() { tag.remove(); };
      tag.textContent = val + ' ';
      tag.appendChild(rem);
      wrap.insertBefore(tag, input);
      input.value = '';
    }
    if (e.key === 'Backspace' && e.target.value === '') {
      var wrap = document.getElementById(containerId);
      var pills = wrap.querySelectorAll('.tag-pill');
      if (pills.length) pills[pills.length - 1].remove();
    }
  };

  window.getTagValues = function(containerId) {
    var pills = document.querySelectorAll('#' + containerId + ' .tag-pill');
    return Array.prototype.map.call(pills, function(p) {
      return p.textContent.replace('\u00d7', '').trim();
    });
  };

  // ─── Event expandable rows ──────────────────────────────────────────────────
  window.toggleEventRow = function(tr) {
    tr.classList.toggle('open');
    var detail = tr.nextElementSibling;
    while (detail && detail.classList.contains('row-detail')) {
      detail.classList.toggle('open');
      detail = detail.nextElementSibling;
      break;
    }
  };

  // ─── Feed slug auto-generation ───────────────────────────────────────────────
  window.autoSlug = function() {
    var name = document.getElementById('feed-name').value;
    var slug = name.toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-|-$/g, '');
    document.getElementById('feed-slug').value = slug;
  };

})();
