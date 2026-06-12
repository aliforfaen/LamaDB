// ─── Secrets Management Page ────────────────────────────────────────────
(function() {
  'use strict';

  var SECRET_TYPES = ['api_key', 'oauth', 'login', 'token', 'custom'];

  function formatDate(iso) { if (!iso) return '\u2014'; var d = new Date(iso); return d.toLocaleDateString(); }

  function statusBadge(expiresAt) {
    if (!expiresAt) return '<span style="color:var(--fg-muted);font-size:0.8rem">\u2014</span>';
    var exp = new Date(expiresAt);
    var now = new Date();
    if (exp < now) return '<span class="badge" style="background:var(--danger);color:#fff">Expired</span>';
    var days = Math.ceil((exp - now) / (1000 * 60 * 60 * 24));
    if (days <= 7) return '<span class="badge" style="background:#f59e0b;color:#000">Expires in ' + days + 'd</span>';
    return '<span style="color:var(--fg-muted);font-size:0.8rem">' + formatDate(expiresAt) + '</span>';
  }

  async function loadSecrets(filters) {
    filters = filters || {};
    var table = document.getElementById('secrets-table-body');
    if (!table) return;
    try {
      var params = [];
      if (filters.service) params.push('service=' + encodeURIComponent(filters.service));
      if (filters.type) params.push('secret_type=' + encodeURIComponent(filters.type));
      if (filters.priority) params.push('priority=' + encodeURIComponent(filters.priority));
      if (filters.tag) params.push('tag=' + encodeURIComponent(filters.tag));
      var qs = params.length ? '?' + params.join('&') : '';
      var secrets = await window.api('/api/secrets' + qs);
      table.innerHTML = '';
      if (!secrets.length) {
        table.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--fg-muted);padding:2rem;">No secrets found.</td></tr>';
        return;
      }
      secrets.forEach(function(s) {
        var tr = document.createElement('tr');
        tr.className = 'clickable-row';
        tr.onclick = function() { showSecretDetail(s.id); };
        tr.innerHTML =
          '<td><strong>' + window.escHtml(s.name) + '</strong></td>' +
          '<td>' + window.escHtml(s.service) + '</td>' +
          '<td><span class="badge" style="font-size:0.75rem">' + s.secret_type + '</span></td>' +
          '<td>' + (s.priority === 'primary' ? '\u2B50' : s.priority === 'secondary' ? '\uD83D\uDD04' : '\u2B07\uFE0F') + ' ' + s.priority + '</td>' +
          '<td>' + (s.tags || []).map(function(t) { return '<span class="badge" style="font-size:0.7rem;background:var(--surface-2)">' + window.escHtml(t) + '</span>'; }).join(' ') + '</td>' +
          '<td>' + statusBadge(s.expires_at) + '</td>' +
          '<td>' + (s.last_revealed_at ? formatDate(s.last_revealed_at) : '<span style="color:var(--fg-muted)">Never used</span>') + '</td>';
        table.appendChild(tr);
      });
    } catch (e) { console.error('loadSecrets:', e); }
  }

  async function showSecretDetail(secretId) {
    var detail = document.getElementById('secrets-detail');
    if (!detail) return;
    try {
      var s = await window.api('/api/secrets/' + secretId);
      var accessGrants = await window.api('/api/secrets/' + secretId + '/access');

      var grantsHtml = '';
      if (accessGrants.length) {
        accessGrants.forEach(function(g) {
          grantsHtml +=
            '<div style="display:flex;align-items:center;gap:0.5rem;padding:0.35rem 0;border-bottom:1px solid var(--border)">' +
            '<span style="flex:1">' + window.escHtml(g.grantee_name || g.grantee_id) + ' <span class="badge" style="font-size:0.7rem">' + g.grantee_type + '</span></span>' +
            '<span class="badge" style="font-size:0.7rem">' + g.access_level + '</span>' +
            '<button class="btn btn-sm btn-ghost" onclick="event.stopPropagation();window.revokeSecretAccess(\'' + secretId + '\',' + g.id + ')" style="color:var(--danger)">&times;</button>' +
            '</div>';
        });
      } else {
        grantsHtml = '<p style="color:var(--fg-muted)">No access grants.</p>';
      }

      detail.innerHTML =
        '<div class="detail-header" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem">' +
        '<h3 style="margin:0">' + window.escHtml(s.name) + '</h3>' +
        '<button class="btn btn-sm btn-ghost" onclick="document.getElementById(\'secrets-detail\').innerHTML=\'\'">&times;</button>' +
        '</div>' +
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:0.5rem;margin-bottom:1rem">' +
        '<div><strong>Service:</strong> ' + window.escHtml(s.service) + '</div>' +
        '<div><strong>Type:</strong> ' + s.secret_type + '</div>' +
        '<div><strong>Priority:</strong> ' + s.priority + '</div>' +
        '<div><strong>Expires:</strong> ' + (s.expires_at ? formatDate(s.expires_at) : 'Never') + '</div>' +
        '<div><strong>Last Used:</strong> ' + (s.last_revealed_at ? formatDate(s.last_revealed_at) : 'Never') + '</div>' +
        '<div><strong>Tags:</strong> ' + (s.tags || []).join(', ') + '</div>' +
        '</div>' +
        '<p style="color:var(--fg-muted)">' + window.escHtml(s.description || 'No description') + '</p>' +

        '<div style="margin:1rem 0;padding:0.75rem;border:1px solid var(--border);border-radius:var(--radius)">' +
        '<strong>Secret Value</strong>' +
        '<div style="display:flex;gap:0.5rem;margin-top:0.5rem">' +
        '<input type="text" id="reveal-field" readonly style="flex:1;padding:0.4rem;font-family:monospace;font-size:0.85rem;background:var(--surface-1);border:1px solid var(--border);border-radius:4px" value="\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022" />' +
        '<button class="btn btn-sm btn-primary" id="reveal-btn" onclick="window.revealSecretValue(\'' + secretId + '\')">Reveal</button>' +
        '<button class="btn btn-sm" id="copy-btn" onclick="window.copyRevealedSecret()" style="display:none">Copy</button>' +
        '</div>' +
        '<div id="reveal-timer" style="font-size:0.75rem;color:var(--fg-muted);margin-top:0.25rem"></div>' +
        '</div>' +

        '<h4 style="margin-top:1rem">Access Grants</h4>' +
        '<div style="margin-bottom:0.5rem;display:flex;gap:0.5rem">' +
        '<select id="grant-type-select"><option value="user">User</option><option value="group">Group</option></select>' +
        '<input type="text" id="grant-id-input" placeholder="User/Group ID" style="flex:1;padding:0.3rem">' +
        '<button class="btn btn-sm btn-primary" onclick="window.grantSecretAccess(\'' + secretId + '\')">Grant Access</button>' +
        '</div>' +
        '<div>' + grantsHtml + '</div>' +

        '<div style="margin-top:1.5rem;display:flex;gap:0.5rem">' +
        '<button class="btn btn-sm btn-primary" onclick="window.editSecret(\'' + secretId + '\')">Edit</button>' +
        '<button class="btn btn-sm btn-danger" onclick="window.deleteSecretConfirm(\'' + secretId + '\')">Delete</button>' +
        '</div>';

      window._currentSecretId = secretId;
    } catch (e) { console.error('showSecretDetail:', e); }
  }

  var _revealTimer = null;
  var _revealedValue = '';

  window.revealSecretValue = async function(secretId) {
    try {
      var result = await window.api('/api/secrets/' + secretId + '/reveal');
      _revealedValue = result.value;
      document.getElementById('reveal-field').value = result.value;
      document.getElementById('reveal-btn').style.display = 'none';
      document.getElementById('copy-btn').style.display = 'inline-block';

      var seconds = 30;
      var timerEl = document.getElementById('reveal-timer');
      timerEl.textContent = 'Auto-masking in ' + seconds + 's';
      if (_revealTimer) clearInterval(_revealTimer);
      _revealTimer = setInterval(function() {
        seconds--;
        if (seconds <= 0) {
          clearInterval(_revealTimer);
          document.getElementById('reveal-field').value = '\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022';
          document.getElementById('reveal-btn').style.display = 'inline-block';
          document.getElementById('copy-btn').style.display = 'none';
          timerEl.textContent = '';
          _revealedValue = '';
        } else {
          timerEl.textContent = 'Auto-masking in ' + seconds + 's';
        }
      }, 1000);
    } catch (e) { window.showError('Reveal failed: ' + e.message); }
  };

  window.copyRevealedSecret = function() {
    if (!_revealedValue) return;
    navigator.clipboard.writeText(_revealedValue).then(function() {
      window.showToast && window.showToast('Copied!');
    }).catch(function() {
      window.showError('Copy failed');
    });
  };

  window.revokeSecretAccess = async function(secretId, grantId) {
    if (!confirm('Revoke this access grant?')) return;
    try {
      await window.api('/api/secrets/' + secretId + '/access/' + grantId, { method: 'DELETE' });
      showSecretDetail(secretId);
    } catch (e) { window.showError('Revoke failed: ' + e.message); }
  };

  window.grantSecretAccess = async function(secretId) {
    var type = document.getElementById('grant-type-select').value;
    var id = document.getElementById('grant-id-input').value.trim();
    if (!id) return;
    try {
      await window.api('/api/secrets/' + secretId + '/access', {
        method: 'POST',
        body: JSON.stringify({ grantee_type: type, grantee_id: id, access_level: 'read' })
      });
      showSecretDetail(secretId);
    } catch (e) { window.showError('Grant failed: ' + e.message); }
  };

  window.deleteSecretConfirm = async function(secretId) {
    if (!confirm('Delete this secret? This cannot be undone.')) return;
    try {
      await window.api('/api/secrets/' + secretId, { method: 'DELETE' });
      document.getElementById('secrets-detail').innerHTML = '';
      loadSecrets();
    } catch (e) { window.showError('Delete failed: ' + e.message); }
  };

  window.showNewSecretForm = function() {
    var detail = document.getElementById('secrets-detail');
    if (!detail) return;
    var typeFields = {
      'api_key': '<div class="form-group"><label>API Key</label><input type="text" id="new-secret-value" class="form-input" placeholder="sk-..." required></div>',
      'oauth': '<div class="form-group"><label>Client ID</label><input type="text" id="new-secret-extra1" class="form-input" placeholder="client_..."></div><div class="form-group"><label>Client Secret</label><input type="text" id="new-secret-value" class="form-input" placeholder="secret_..." required></div>',
      'login': '<div class="form-group"><label>Username</label><input type="text" id="new-secret-extra1" class="form-input" placeholder="username"></div><div class="form-group"><label>Password</label><input type="password" id="new-secret-value" class="form-input" required></div>',
      'token': '<div class="form-group"><label>Token</label><input type="text" id="new-secret-value" class="form-input" placeholder="eyJ..." required></div><div class="form-group"><label>Token Type</label><select id="new-secret-extra1" class="form-input"><option>Bearer</option><option>Basic</option><option>Custom</option></select></div>',
      'custom': '<div class="form-group"><label>Value</label><input type="text" id="new-secret-value" class="form-input" required></div><div class="form-group"><label>Extra 1</label><input type="text" id="new-secret-extra1" class="form-input"></div><div class="form-group"><label>Extra 2</label><input type="text" id="new-secret-extra2" class="form-input"></div>'
    };

    detail.innerHTML =
      '<h3>New Secret</h3>' +
      '<div class="form-group"><label>Name</label><input type="text" id="new-secret-name" class="form-input" placeholder="My API Key" required></div>' +
      '<div class="form-group"><label>Service</label><input type="text" id="new-secret-service" class="form-input" placeholder="openai" required></div>' +
      '<div class="form-group"><label>Description</label><input type="text" id="new-secret-desc" class="form-input" placeholder="Optional"></div>' +
      '<div class="form-group"><label>Type</label><select id="new-secret-type" class="form-input" onchange="window.switchSecretTypeFields(this.value)">' +
      SECRET_TYPES.map(function(t) { return '<option value="' + t + '">' + t + '</option>'; }).join('') +
      '</select></div>' +
      '<div id="type-fields-container">' + typeFields['api_key'] + '</div>' +
      '<div class="form-group"><label>Priority</label><select id="new-secret-priority" class="form-input"><option value="primary">Primary</option><option value="secondary">Secondary</option><option value="fallback">Fallback</option></select></div>' +
      '<div class="form-group"><label>Tags (comma-separated)</label><input type="text" id="new-secret-tags" class="form-input" placeholder="production, paid"></div>' +
      '<div style="display:flex;gap:0.5rem;margin-top:1rem">' +
      '<button class="btn btn-primary" onclick="window.createSecret()">Create</button>' +
      '<button class="btn btn-ghost" onclick="document.getElementById(\'secrets-detail\').innerHTML=\'\'">Cancel</button>' +
      '</div>';

    window._secretTypeFields = typeFields;
  };

  window.switchSecretTypeFields = function(type) {
    var container = document.getElementById('type-fields-container');
    var fields = window._secretTypeFields;
    if (container && fields) {
      container.innerHTML = fields[type] || fields['custom'];
    }
  };

  window.createSecret = async function() {
    var name = document.getElementById('new-secret-name');
    var service = document.getElementById('new-secret-service');
    var desc = document.getElementById('new-secret-desc');
    var type = document.getElementById('new-secret-type');
    var value = document.getElementById('new-secret-value');
    var extra1 = document.getElementById('new-secret-extra1');
    var extra2 = document.getElementById('new-secret-extra2');
    var priority = document.getElementById('new-secret-priority');
    var tagsRaw = document.getElementById('new-secret-tags');

    if (!name || !service || !value || !name.value.trim() || !service.value.trim() || !value.value) {
      window.showError('Name, service, and value are required'); return;
    }

    var body = {
      name: name.value.trim(), service: service.value.trim(),
      description: desc ? desc.value.trim() : '',
      secret_type: type.value, value: value.value, priority: priority.value,
      tags: tagsRaw && tagsRaw.value ? tagsRaw.value.split(',').map(function(t) { return t.trim(); }).filter(Boolean) : [],
      extra_1: extra1 && extra1.value ? extra1.value.trim() || null : null,
      extra_2: extra2 && extra2.value ? extra2.value.trim() || null : null,
    };

    try {
      await window.api('/api/secrets', { method: 'POST', body: JSON.stringify(body) });
      document.getElementById('secrets-detail').innerHTML = '';
      loadSecrets();
    } catch (e) { window.showError('Create failed: ' + e.message); }
  };

  window.loadSecrets = loadSecrets;
})();
