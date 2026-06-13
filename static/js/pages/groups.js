// ─── Groups Management Page ─────────────────────────────────────────────
(function() {
  'use strict';

  function formatDate(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    return d.toLocaleDateString();
  }

  async function loadGroups() {
    var list = document.getElementById('groups-table-body');
    if (!list) return;
    try {
      var groups = await window.api('/api/groups');
      list.innerHTML = '';
      if (!groups.length) {
        list.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--muted);padding:2rem;">No groups yet. Create one above.</td></tr>';
        return;
      }
      groups.forEach(function(g) {
        var tr = document.createElement('tr');
        tr.className = 'clickable-row';
        tr.onclick = function() { showGroupDetail(g.id); };
        tr.innerHTML =
          '<td><strong>' + window.escHtml(g.name) + '</strong></td>' +
          '<td>' + window.escHtml(g.description || '') + '</td>' +
          '<td>' + g.member_count + '</td>' +
          '<td>' + formatDate(g.created_at) + '</td>';
        list.appendChild(tr);
      });
    } catch (e) { console.error('loadGroups:', e); }
  }

  async function showGroupDetail(groupId) {
    var detail = document.getElementById('groups-detail');
    if (!detail) return;
    try {
      var g = await window.api('/api/groups/' + groupId);
      var users = await window.api('/api/users');
      var membersHtml = '';
      if (g.members && g.members.length) {
        g.members.forEach(function(m) {
          membersHtml +=
            '<div class="member-row">' +
            '<span class="member-name">' + window.escHtml(m.user_name) + '</span>' +
            '<span class="member-role badge" style="font-size:0.75rem">' + m.role + '</span>' +
            '<button class="btn btn-sm btn-ghost" onclick="event.stopPropagation();window.removeGroupMember(\'' + groupId + '\',\'' + m.user_id + '\')" title="Remove member" style="color:var(--danger);flex-shrink:0">&times;</button>' +
            '</div>';
        });
      } else {
        membersHtml = '<p style="color:var(--muted);font-size:13px;">No members yet.</p>';
      }

      detail.innerHTML =
        '<div class="detail-panel">' +
        '<div class="detail-header">' +
        '<h3>' + window.escHtml(g.name) + '</h3>' +
        '<button class="detail-close" onclick="document.getElementById(\'groups-detail\').innerHTML=\'\'">&times;</button>' +
        '</div>' +
        '<div class="detail-body">' +
        '<div class="detail-desc">' + window.escHtml(g.description || 'No description') + '</div>' +

        '<h4 class="detail-section-title">Members (' + (g.members ? g.members.length : 0) + ')</h4>' +
        '<div style="display:flex;gap:8px;margin-bottom:8px;flex-wrap:wrap;">' +
        '<select id="new-member-select" style="flex:1;min-width:100px;padding:6px 8px;background:var(--surface-2);border:1px solid var(--border);border-radius:var(--radius-sm);color:var(--fg);font-size:12px;">' +
        '<option value="">Add member...</option>' +
        (users || []).map(function(u) {
          return '<option value="' + u.id + '">' + window.escHtml(u.name) + '</option>';
        }).join('') +
        '</select>' +
        '<select id="new-member-role" style="padding:6px 8px;background:var(--surface-2);border:1px solid var(--border);border-radius:var(--radius-sm);color:var(--fg);font-size:12px;"><option value="member">Member</option><option value="admin">Admin</option><option value="owner">Owner</option></select>' +
        '<button class="btn btn-sm btn-primary" onclick="window.addGroupMember(\'' + groupId + '\')">Add</button>' +
        '</div>' +
        '<div id="group-members-list">' + membersHtml + '</div>' +

        '<div class="detail-actions">' +
        '<button class="btn btn-sm btn-danger" onclick="window.deleteGroup(\'' + groupId + '\')">Delete Group</button>' +
        '</div>' +
        '</div>' +
        '</div>';

      window._currentGroupId = groupId;
    } catch (e) { console.error('showGroupDetail:', e); }
  }

  window.showNewGroupForm = function() {
    var modal = document.getElementById('modal-new-group');
    if (!modal) {
      modal = document.createElement('div');
      modal.id = 'modal-new-group';
      modal.className = 'modal-overlay';
      modal.innerHTML =
        '<div class="modal">' +
        '<div class="modal-header">' +
        '<h3>New Group</h3>' +
        '<button class="modal-close" onclick="window.closeGroupModal()">&times;</button>' +
        '</div>' +
        '<div class="modal-body">' +
        '<div class="modal-form">' +
        '<div class="form-group"><label>Group Name</label><input type="text" id="new-group-name" placeholder="e.g. Engineering" required></div>' +
        '<div class="form-group"><label>Description</label><input type="text" id="new-group-desc" placeholder="Optional description"></div>' +
        '<div class="form-actions">' +
        '<button class="btn btn-ghost" onclick="window.closeGroupModal()">Cancel</button>' +
        '<button class="btn btn-primary" onclick="window.createGroup()">Create Group</button>' +
        '</div>' +
        '</div>' +
        '</div>' +
        '</div>';
      document.body.appendChild(modal);
    }
    // Clear fields
    var nameInput = document.getElementById('new-group-name');
    var descInput = document.getElementById('new-group-desc');
    if (nameInput) nameInput.value = '';
    if (descInput) descInput.value = '';
    modal.classList.add('open');
  };

  window.closeGroupModal = function() {
    var modal = document.getElementById('modal-new-group');
    if (modal) modal.classList.remove('open');
  };

  window.createGroup = async function() {
    var name = document.getElementById('new-group-name');
    var desc = document.getElementById('new-group-desc');
    if (!name || !name.value.trim()) {
      window.showToast && window.showToast('Group name is required', null, null, 3000);
      return;
    }
    try {
      await window.api('/api/groups', {
        method: 'POST',
        body: JSON.stringify({ name: name.value.trim(), description: (desc ? desc.value.trim() : '') })
      });
      window.closeGroupModal();
      loadGroups();
    } catch (e) { window.showToast && window.showToast('Failed to create group: ' + e.message, null, null, 3000); }
  };

  window.addGroupMember = async function(groupId) {
    var userId = document.getElementById('new-member-select').value;
    var role = document.getElementById('new-member-role').value;
    if (!userId) return;
    try {
      await window.api('/api/groups/' + groupId + '/members', {
        method: 'POST',
        body: JSON.stringify({ user_id: userId, role: role })
      });
      showGroupDetail(groupId);
    } catch (e) { window.showToast && window.showToast('Failed to add member: ' + e.message, null, null, 3000); }
  };

  window.removeGroupMember = async function(groupId, userId) {
    window.showConfirm && window.showConfirm('Remove Member', 'Remove this member from the group?', 'Remove', async function() {
      try {
        await window.api('/api/groups/' + groupId + '/members/' + userId, { method: 'DELETE' });
        showGroupDetail(groupId);
      } catch (e) { window.showToast && window.showToast('Failed to remove member: ' + e.message, null, null, 3000); }
    });
  };

  window.deleteGroup = async function(groupId) {
    window.showConfirm && window.showConfirm('Delete Group', 'Delete this group? This cannot be undone.', 'Delete', async function() {
      try {
        await window.api('/api/groups/' + groupId, { method: 'DELETE' });
        document.getElementById('groups-detail').innerHTML = '';
        loadGroups();
      } catch (e) { window.showToast && window.showToast('Failed to delete group: ' + e.message, null, null, 3000); }
    });
  };

  window.loadGroups = loadGroups;
})();