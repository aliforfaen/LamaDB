// Page: Users (Settings sub-tab)
(function() {
  'use strict';

  window.loadUsersPage = async function() {
    var el = document.getElementById('users-table');
    if (!el) return;
    el.innerHTML = '<p class="loading">Loading\u2026</p>';
    try {
      var users = await window.api('/api/users');
      if (!users || users.length === 0) {
        el.innerHTML = '<div style="color:var(--muted);padding:20px;text-align:center;">No users found.</div>';
        return;
      }
      el.innerHTML = '<div class="table-wrap"><table><thead><tr><th>Name</th><th>Type</th><th>Status</th><th>Last Active</th><th>Tasks</th><th></th></tr></thead><tbody>' +
        users.map(function(u) {
          var statusDot = u.status === 'active' ? '<span class="status-dot" style="background:var(--success);display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:4px;"></span>' : '<span class="status-dot" style="background:var(--muted);display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:4px;"></span>';
          var typeBadge = u.type === 'agent' ? '<span class="badge" style="background:var(--accent-cyan);color:#fff;font-size:10px;padding:2px 6px;border-radius:var(--radius-sm);">agent</span>' : '<span class="badge" style="background:var(--accent);color:#fff;font-size:10px;padding:2px 6px;border-radius:var(--radius-sm);">human</span>';
          return '<tr style="cursor:pointer;" onclick="window.toggleUserDetail(\'' + u.id + '\')">' +
            '<td style="font-weight:500;">' + window.escHtml(u.name) + '</td>' +
            '<td>' + typeBadge + '</td>' +
            '<td>' + statusDot + ' ' + u.status + '</td>' +
            '<td class="mono" style="font-size:12px;">' + (u.last_active_at ? window.relativeTime(u.last_active_at) : 'never') + '</td>' +
            '<td class="mono">' + u.open_tasks + ' open / ' + u.completed_tasks + ' done</td>' +
            '<td><button class="btn btn-sm btn-secondary" onclick="event.stopPropagation();window.showUserActions(\'' + u.id + '\', \'' + window.escAttr(u.name) + '\')">\u22ef</button></td>' +
          '</tr>' +
          '<tr id="user-detail-' + u.id + '" style="display:none;"><td colspan="6">Loading\u2026</td></tr>';
        }).join('') +
      '</tbody></table></div>';
    } catch(e) {
      el.innerHTML = '<div style="color:var(--danger);padding:10px;">Failed: ' + e.message + '</div>';
    }
  };

  window.toggleUserDetail = async function(userId) {
    var row = document.getElementById('user-detail-' + userId);
    if (!row) return;
    if (row.style.display !== 'none' && row.innerHTML !== 'Loading\u2026') {
      row.style.display = row.style.display === 'none' ? '' : 'none';
      return;
    }
    row.style.display = '';
    try {
      var user = await window.api('/api/users/' + userId);
      row.innerHTML = '<td colspan="6" style="padding:16px;background:var(--surface-2);">' +
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">' +
          '<div>' +
            '<div style="font-size:12px;color:var(--muted);margin-bottom:4px;">API Key</div>' +
            '<code style="background:var(--surface);padding:4px 8px;border-radius:var(--radius-sm);font-size:12px;display:inline-block;">' + (user.api_key_masked || 'No key') + '</code>' +
            '<button class="btn btn-sm btn-secondary" style="margin-left:8px;" onclick="window.rotateUserKey(\'' + userId + '\')">Rotate</button>' +
          '</div>' +
          '<div>' +
            '<div style="font-size:12px;color:var(--muted);margin-bottom:4px;">Instructions</div>' +
            '<div style="font-size:12px;color:var(--fg-2);">' + (user.instructions || 'None') + '</div>' +
          '</div>' +
          '<div>' +
            '<div style="font-size:12px;color:var(--muted);margin-bottom:4px;">Stats</div>' +
            '<div style="font-size:12px;">Open tasks: <strong>' + user.open_tasks + '</strong> | Completed: <strong>' + user.completed_tasks + '</strong></div>' +
          '</div>' +
          '<div style="text-align:right;">' +
            '<button class="btn btn-sm btn-danger" onclick="window.deactivateUser(\'' + userId + '\')">Deactivate</button>' +
          '</div>' +
        '</div>' +
      '</td>';
    } catch(e) {
      row.innerHTML = '<td colspan="6" style="color:var(--danger);padding:10px;">Failed: ' + e.message + '</td>';
    }
  };

  window.showNewUserForm = function() {
    var el = document.getElementById('new-user-form');
    if (!el) return;
    el.style.display = 'block';
    el.innerHTML = '<h4 style="margin:0 0 10px;">Create User</h4>' +
      '<div class="user-form-grid">' +
        '<div class="form-group"><label>Name</label><input id="nu-name" type="text" placeholder="agent-name" /></div>' +
        '<div class="form-group"><label>Type</label><select id="nu-type"><option value="agent">Agent</option><option value="human">Human</option></select></div>' +
      '</div>' +
      '<div class="form-group" style="margin-top:10px;"><label>Instructions <span class="help-text">(shown to agent on connect)</span></label><textarea id="nu-instructions" rows="3" placeholder="You are the orchestrator. Pick up backlog tasks\u2026"></textarea></div>' +
      '<div class="user-form-actions">' +
        '<button class="btn btn-sm btn-primary" onclick="window.createUser()">Create</button>' +
        '<button class="btn btn-sm btn-secondary" onclick="document.getElementById(\'new-user-form\').style.display=\'none\'">Cancel</button>' +
      '</div>';
  };

  window.createUser = async function() {
    var name = document.getElementById('nu-name').value.trim();
    if (!name) { alert('Name required'); return; }
    try {
      var result = await window.api('/api/users', {
        method: 'POST',
        body: JSON.stringify({
          name: name,
          type: document.getElementById('nu-type').value,
          instructions: document.getElementById('nu-instructions').value.trim()
        })
      });
      document.getElementById('new-user-form').style.display = 'none';
      // Show the API key prominently
      var modal = document.createElement('div');
      modal.className = 'modal-overlay';
      modal.innerHTML = '<div class="modal" style="max-width:450px;background:var(--surface);border:2px solid var(--accent);border-radius:var(--radius);padding:20px;text-align:center;">' +
        '<h3 style="margin:0 0 8px;">User Created!</h3>' +
        '<p style="color:var(--muted);font-size:13px;margin-bottom:12px;"><strong>' + window.escHtml(name) + '</strong></p>' +
        '<div style="background:var(--surface-2);border:1px solid var(--border);border-radius:var(--radius-sm);padding:12px;margin-bottom:12px;word-break:break-all;font-family:var(--font-mono);font-size:13px;" id="api-key-display">' + result.api_key + '</div>' +
        '<button class="btn btn-sm btn-primary" onclick="navigator.clipboard.writeText(document.getElementById(\'api-key-display\').textContent);this.textContent=\'Copied!\';setTimeout(function(){this.textContent=\'Copy to Clipboard\';}.bind(this),2000);" style="margin-bottom:8px;">Copy to Clipboard</button>' +
        '<p style="color:var(--danger);font-size:11px;margin:0;">Save this key now - it won\'t be shown again!</p>' +
        '<button class="btn btn-sm btn-secondary" style="margin-top:12px;" onclick="this.closest(\'.modal-overlay\').remove()">Close</button>' +
      '</div>';
      document.body.appendChild(modal);
      modal.addEventListener('click', function(e) { if (e.target === modal) modal.remove(); });
      window.loadUsersPage();
    } catch(e) {
      alert('Failed: ' + e.message);
    }
  };

  window.rotateUserKey = async function(userId) {
    if (!confirm('Rotate API key for this user? The old key will stop working immediately.')) return;
    try {
      var result = await window.api('/api/users/' + userId + '/rotate-key', { method: 'POST' });
      alert('New API key:\n\n' + result.api_key + '\n\nSave this now!');
      window.loadUsersPage();
    } catch(e) {
      alert('Failed: ' + e.message);
    }
  };

  window.deactivateUser = async function(userId) {
    if (!confirm('Deactivate this user? All their API keys will be revoked.')) return;
    try {
      await window.api('/api/users/' + userId, { method: 'DELETE' });
      window.showToast('User deactivated', 'success');
      window.loadUsersPage();
    } catch(e) {
      alert('Failed: ' + e.message);
    }
  };

  window.showUserActions = function(userId, userName) {
    var el = document.createElement('div');
    el.className = 'modal-overlay';
    el.innerHTML = '<div class="modal" style="max-width:320px;background:var(--surface);border-radius:var(--radius);padding:16px;">' +
      '<h4 style="margin:0 0 10px;">Actions: ' + window.escHtml(userName) + '</h4>' +
      '<div style="display:flex;flex-direction:column;gap:6px;">' +
        '<button class="btn btn-sm btn-secondary" onclick="this.closest(\'.modal-overlay\').remove();window.rotateUserKey(\'' + userId + '\')">\ud83d\udd04 Rotate API Key</button>' +
        '<button class="btn btn-sm btn-danger" onclick="this.closest(\'.modal-overlay\').remove();window.deactivateUser(\'' + userId + '\')">\u2717 Deactivate User</button>' +
      '</div>' +
      '<button class="btn btn-sm btn-ghost" style="margin-top:12px;width:100%;" onclick="this.closest(\'.modal-overlay\').remove()">Cancel</button>' +
    '</div>';
    document.body.appendChild(el);
    el.addEventListener('click', function(e) { if (e.target === el) el.remove(); });
  };
})();
