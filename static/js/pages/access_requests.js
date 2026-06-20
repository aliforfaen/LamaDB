// ─── Access Requests Page ───────────────────────────────────────────────
(function() {
  'use strict';

  function formatDate(iso) { if (!iso) return ''; var d = new Date(iso); return d.toLocaleString(); }

  var currentFilter = 'pending';

  window.loadAccessRequests = async function(filter) {
    if (filter) currentFilter = filter;
    if (!window.LlamaApp || !window.LlamaApp.getApiKey || !window.LlamaApp.getApiKey()) return;
    var table = document.getElementById('requests-table-body');
    if (!table) return;

    document.querySelectorAll('#requests-filter-bar .filter-tab').forEach(function(el) {
      el.classList.toggle('active', el.dataset.status === currentFilter);
    });

    try {
      var qs = currentFilter ? '?status=' + currentFilter : '';
      var requests = await window.api('/api/secrets/requests' + qs);
      table.innerHTML = '';
      if (!requests.length) {
        table.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--fg-muted);padding:2rem;">No ' + currentFilter + ' requests.</td></tr>';
        return;
      }
      requests.forEach(function(r) {
        var tr = document.createElement('tr');
        var actionsHtml = '';
        if (r.status === 'pending') {
          actionsHtml =
            '<button class="btn btn-sm btn-primary" onclick="event.stopPropagation();window.approveRequest(' + r.id + ')" style="margin-right:0.25rem">Approve</button>' +
            '<button class="btn btn-sm btn-ghost" onclick="event.stopPropagation();window.rejectRequest(' + r.id + ')" style="color:var(--danger)">Reject</button>';
        } else {
          actionsHtml = '<span style="color:var(--fg-muted);font-size:0.8rem">' +
            (r.status === 'approved' ? '\u2713 Approved' : '\u2717 Rejected') + '</span>';
        }
        tr.innerHTML =
          '<td><strong>' + window.escHtml(r.requester_name) + '</strong></td>' +
          '<td>' + window.escHtml(r.secret_name) + '</td>' +
          '<td>' + window.escHtml(r.reason || '\u2014') + '</td>' +
          '<td>' + formatDate(r.created_at) + '</td>' +
          '<td><span class="badge" style="font-size:0.75rem;background:' + (r.status === 'pending' ? '#f59e0b' : r.status === 'approved' ? '#10b981' : '#ef4444') + ';color:#fff">' + r.status + '</span></td>' +
          '<td>' + actionsHtml + '</td>';
        table.appendChild(tr);
      });
    } catch (e) { console.error('loadAccessRequests:', e); }
  };

  window.approveRequest = async function(requestId) {
    try {
      await window.api('/api/secrets/requests/' + requestId, {
        method: 'PATCH',
        body: JSON.stringify({ status: 'approved' })
      });
      window.loadAccessRequests();
    } catch (e) { window.showError('Approve failed: ' + e.message); }
  };

  window.rejectRequest = async function(requestId) {
    try {
      await window.api('/api/secrets/requests/' + requestId, {
        method: 'PATCH',
        body: JSON.stringify({ status: 'rejected' })
      });
      window.loadAccessRequests();
    } catch (e) { window.showError('Reject failed: ' + e.message); }
  };

  window.loadAccessRequestsPage = function() { window.loadAccessRequests(); };

  if (document.getElementById('requests-table-body')) {
    setTimeout(function() { window.loadAccessRequests(); }, 100);
  }
})();
