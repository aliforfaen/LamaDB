// ─── Secrets Management Page ────────────────────────────────────────────
(function() {
  'use strict';

  var SECRET_TYPES = ['api_key', 'oauth', 'login', 'token', 'custom'];
  var _copyBtnTimer = {};

  function formatDate(iso) { if (!iso) return '\u2014'; var d = new Date(iso); return d.toLocaleDateString(); }

  function statusBadge(expiresAt) {
    if (!expiresAt) return '<span style="color:var(--muted);font-size:0.8rem">\u2014</span>';
    var exp = new Date(expiresAt);
    var now = new Date();
    if (exp < now) return '<span class="badge" style="background:var(--danger);color:#fff">Expired</span>';
    var days = Math.ceil((exp - now) / (1000 * 60 * 60 * 24));
    if (days <= 7) return '<span class="badge" style="background:#f59e0b;color:#000">Expires in ' + days + 'd</span>';
    return '<span style="color:var(--muted);font-size:0.8rem">' + formatDate(expiresAt) + '</span>';
  }

  function computeStats(secrets) {
    var total = secrets.length;
    var typeCounts = {};
    var lastUsed = null;
    var expired = 0;
    secrets.forEach(function(s) {
      typeCounts[s.secret_type] = (typeCounts[s.secret_type] || 0) + 1;
      if (s.last_revealed_at && (!lastUsed || s.last_revealed_at > lastUsed)) {
        lastUsed = s.last_revealed_at;
      }
      if (s.expires_at && new Date(s.expires_at) < new Date()) {
        expired++;
      }
    });
    return { total: total, typeCounts: typeCounts, lastUsed: lastUsed, expired: expired };
  }

  function renderSecretsStats(secrets) {
    var container = document.getElementById('secrets-stats');
    if (!container) return;
    var stats = computeStats(secrets);
    var typeBreakdown = Object.entries(stats.typeCounts)
      .map(function(e) { return e[0] + ' (' + e[1] + ')'; })
      .join(', ') || '\u2014';
    container.innerHTML =
      '<div class="stat-card">' +
        '<div class="stat-label">Total Secrets</div>' +
        '<div class="stat-value">' + stats.total + '</div>' +
      '</div>' +
      '<div class="stat-card">' +
        '<div class="stat-label">Expired</div>' +
        '<div class="stat-value" style="color:' + (stats.expired > 0 ? 'var(--danger)' : 'var(--accent)') + '">' + stats.expired + '</div>' +
      '</div>' +
      '<div class="stat-card">' +
        '<div class="stat-label">Last Used</div>' +
        '<div class="stat-value" style="font-size:18px;">' + (stats.lastUsed ? formatDate(stats.lastUsed) : '\u2014') + '</div>' +
      '</div>' +
      '<div class="stat-card">' +
        '<div class="stat-label">By Type</div>' +
        '<div class="stat-sub">' + typeBreakdown + '</div>' +
      '</div>';
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
      renderSecretsStats(secrets);
      table.innerHTML = '';
      if (!secrets.length) {
        table.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--muted);padding:2rem;">No secrets found.</td></tr>';
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
          '<td>' + (s.last_revealed_at ? formatDate(s.last_revealed_at) : '<span style="color:var(--muted)">Never used</span>') + '</td>' +
          '<td><button class="copy-btn" onclick="event.stopPropagation();window.copySecretToClipboard(\'' + s.id + '\', this)" title="Copy secret value">' +
            '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>' +
          '</button></td>';
        table.appendChild(tr);
      });
    } catch (e) { console.error('loadSecrets:', e); }
  }

  window.copySecretToClipboard = async function(secretId, btn) {
    try {
      var result = await window.api('/api/secrets/' + secretId + '/reveal');
      await navigator.clipboard.writeText(result.value);
      btn.classList.add('copied');
      btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
      if (_copyBtnTimer[secretId]) clearTimeout(_copyBtnTimer[secretId]);
      _copyBtnTimer[secretId] = setTimeout(function() {
        btn.classList.remove('copied');
        btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
      }, 2000);
      window.showToast && window.showToast('Copied ' + secretId.slice(0, 8) + '...');
    } catch (e) {
      window.showToast && window.showToast('Copy failed: ' + e.message);
    }
  };

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
            '<div class="grant-row">' +
            '<span class="grant-name">' + window.escHtml(g.grantee_name || g.grantee_id) + ' <span class="badge" style="font-size:0.7rem">' + g.grantee_type + '</span></span>' +
            '<span class="grant-level badge" style="font-size:0.7rem">' + g.access_level + '</span>' +
            '<button class="btn btn-sm btn-ghost" onclick="event.stopPropagation();window.revokeSecretAccess(\'' + secretId + '\',' + g.id + ')" style="color:var(--danger);flex-shrink:0">&times;</button>' +
            '</div>';
        });
      } else {
        grantsHtml = '<p style="color:var(--muted);font-size:13px;">No access grants.</p>';
      }

      detail.innerHTML =
        '<div class="detail-panel">' +
        '<div class="detail-header">' +
        '<h3>' + window.escHtml(s.name) + '</h3>' +
        '<button class="detail-close" onclick="document.getElementById(\'secrets-detail\').innerHTML=\'\'">&times;</button>' +
        '</div>' +
        '<div class="detail-body">' +
        '<div class="detail-meta-grid">' +
        '<div class="detail-meta-item"><span class="meta-label">Service</span><span class="meta-value">' + window.escHtml(s.service) + '</span></div>' +
        '<div class="detail-meta-item"><span class="meta-label">Type</span><span class="meta-value">' + s.secret_type + '</span></div>' +
        '<div class="detail-meta-item"><span class="meta-label">Priority</span><span class="meta-value">' + s.priority + '</span></div>' +
        '<div class="detail-meta-item"><span class="meta-label">Expires</span><span class="meta-value">' + (s.expires_at ? formatDate(s.expires_at) : 'Never') + '</span></div>' +
        '<div class="detail-meta-item"><span class="meta-label">Last Used</span><span class="meta-value">' + (s.last_revealed_at ? formatDate(s.last_revealed_at) : 'Never') + '</span></div>' +
        '<div class="detail-meta-item"><span class="meta-label">Tags</span><span class="meta-value">' + ((s.tags || []).join(', ') || '\u2014') + '</span></div>' +
        '</div>' +
        '<div class="detail-desc">' + window.escHtml(s.description || 'No description') + '</div>' +

        '<div class="reveal-box">' +
        '<div class="reveal-label">Secret Value</div>' +
        '<div class="reveal-row">' +
        '<input type="text" id="reveal-field" readonly value="\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022" />' +
        '<button class="btn btn-sm btn-primary" id="reveal-btn" onclick="window.revealSecretValue(\'' + secretId + '\')">Reveal</button>' +
        '<button class="btn btn-sm btn-secondary" id="copy-btn" onclick="window.copyRevealedSecret()" style="display:none">' +
          '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg> Copy</button>' +
        '</div>' +
        '<div class="reveal-timer" id="reveal-timer"></div>' +
        '</div>' +

        '<h4 class="detail-section-title">Access Grants</h4>' +
        '<div style="display:flex;gap:8px;margin-bottom:8px;flex-wrap:wrap;">' +
        '<select id="grant-type-select" style="flex:1;min-width:100px;padding:6px 8px;background:var(--surface-2);border:1px solid var(--border);border-radius:var(--radius-sm);color:var(--fg);font-size:12px;"><option value="user">User</option><option value="group">Group</option></select>' +
        '<input type="text" id="grant-id-input" placeholder="User/Group ID" style="flex:2;min-width:120px;padding:6px 8px;background:var(--surface-2);border:1px solid var(--border);border-radius:var(--radius-sm);color:var(--fg);font-size:12px;">' +
        '<button class="btn btn-sm btn-primary" onclick="window.grantSecretAccess(\'' + secretId + '\')">Grant Access</button>' +
        '</div>' +
        '<div id="grants-list">' + grantsHtml + '</div>' +

        '<div class="detail-actions">' +
        '<button class="btn btn-sm btn-primary" onclick="window.openEditSecretModal(\'' + secretId + '\')">Edit</button>' +
        '<button class="btn btn-sm btn-danger" onclick="window.deleteSecretConfirm(\'' + secretId + '\')">Delete</button>' +
        '</div>' +
        '</div>' +
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
    var modal = document.getElementById('modal-new-secret');
    if (!modal) {
      // Create modal on first use
      modal = document.createElement('div');
      modal.id = 'modal-new-secret';
      modal.className = 'modal-overlay';
      modal.innerHTML =
        '<div class="modal">' +
        '<div class="modal-header">' +
        '<h3>New Secret</h3>' +
        '<button class="modal-close" onclick="window.closeSecretModal()">&times;</button>' +
        '</div>' +
        '<div class="modal-body" id="new-secret-body">' +
        '<div class="modal-form">' +
        '<div class="form-group"><label>Name</label><input type="text" id="new-secret-name" placeholder="My API Key" required></div>' +
        '<div class="form-group"><label>Service</label><input type="text" id="new-secret-service" placeholder="openai" required></div>' +
        '<div class="form-group"><label>Description</label><input type="text" id="new-secret-desc" placeholder="Optional"></div>' +
        '<div class="form-row"><div class="form-group"><label>Type</label><select id="new-secret-type" onchange="window.switchSecretTypeFields(this.value)">' +
        SECRET_TYPES.map(function(t) { return '<option value="' + t + '">' + t + '</option>'; }).join('') +
        '</select></div>' +
        '<div class="form-group"><label>Priority</label><select id="new-secret-priority"><option value="primary">Primary</option><option value="secondary">Secondary</option><option value="fallback">Fallback</option></select></div></div>' +
        '<div id="type-fields-container"></div>' +
        '<div class="form-group"><label>Tags (comma-separated)</label><input type="text" id="new-secret-tags" placeholder="production, paid"></div>' +
        '<div class="form-actions">' +
        '<button class="btn btn-ghost" onclick="window.closeSecretModal()">Cancel</button>' +
        '<button class="btn btn-primary" onclick="window.createSecret()">Create Secret</button>' +
        '</div>' +
        '</div>' +
        '</div>' +
        '</div>';
      document.body.appendChild(modal);
    }

    var typeFields = {
      'api_key': '<div class="form-group"><label>API Key</label><input type="text" id="new-secret-value" placeholder="sk-..." required></div>',
      'oauth': '<div class="form-group"><label>Client ID</label><input type="text" id="new-secret-extra1" placeholder="client_..."></div><div class="form-group"><label>Client Secret</label><input type="text" id="new-secret-value" placeholder="secret_..." required></div>',
      'login': '<div class="form-group"><label>Username</label><input type="text" id="new-secret-extra1" placeholder="username"></div><div class="form-group"><label>Password</label><input type="password" id="new-secret-value" required></div>',
      'token': '<div class="form-group"><label>Token</label><input type="text" id="new-secret-value" placeholder="eyJ..." required></div><div class="form-group"><label>Token Type</label><select id="new-secret-extra1"><option>Bearer</option><option>Basic</option><option>Custom</option></select></div>',
      'custom': '<div class="form-group"><label>Value</label><input type="text" id="new-secret-value" required></div><div class="form-group"><label>Extra 1</label><input type="text" id="new-secret-extra1"></div><div class="form-group"><label>Extra 2</label><input type="text" id="new-secret-extra2"></div>'
    };
    window._secretTypeFields = typeFields;

    // Clear and set default type fields
    var container = document.getElementById('type-fields-container');
    if (container) container.innerHTML = typeFields['api_key'];

    modal.classList.add('open');
  };

  window.closeSecretModal = function() {
    var modal = document.getElementById('modal-new-secret');
    if (modal) modal.classList.remove('open');
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
      window.showToast && window.showToast('Name, service, and value are required', null, null, 3000);
      return;
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
      window.closeSecretModal();
      document.getElementById('secrets-detail').innerHTML = '';
      loadSecrets();
    } catch (e) { window.showToast && window.showToast('Create failed: ' + e.message, null, null, 3000); }
  };

  window.loadSecrets = loadSecrets;
})();
