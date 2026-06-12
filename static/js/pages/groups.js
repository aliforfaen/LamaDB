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
        list.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--fg-muted);padding:2rem;">No groups yet. Create one above.</td></tr>';
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
            '<div class="member-row" style="display:flex;align-items:center;gap:0.5rem;padding:0.35rem 0;border-bottom:1px solid var(--border);">' +
            '<span style="flex:1"><strong>' + window.escHtml(m.user_name) + '</strong></span>' +
            '<span class="badge" style="font-size:0.75rem">' + m.role + '</span>' +
            '<button class="btn btn-sm btn-ghost" onclick="event.stopPropagation();window.removeGroupMember(\'' + groupId + '\',\'' + m.user_id + '\')" title="Remove member" style="color:var(--danger)">&times;</button>' +
            '</div>';
        });
      } else {
        membersHtml = '<p style="color:var(--fg-muted)">No members yet.</p>';
      }

      detail.innerHTML =
        '<div class="detail-header" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem;">' +
        '<h3 style="margin:0">' + window.escHtml(g.name) + '</h3>' +
        '<button class="btn btn-sm btn-ghost" onclick="document.getElementById(\'groups-detail\').innerHTML=\'\'">&times;</button>' +
        '</div>' +
        '<p style="color:var(--fg-muted);margin-bottom:1rem;">' + window.escHtml(g.description || 'No description') + '</p>' +
        '<h4 style="margin-bottom:0.5rem">Members (' + (g.members ? g.members.length : 0) + ')</h4>' +
        '<div style="margin-bottom:0.75rem;display:flex;gap:0.5rem">' +
        '<select id="new-member-select" style="flex:1;padding:0.3rem">' +
        '<option value="">Add member...</option>' +
        (users || []).map(function(u) {
          return '<option value="' + u.id + '">' + window.escHtml(u.name) + '</option>';
        }).join('') +
        '</select>' +
        '<select id="new-member-role" style="padding:0.3rem"><option value="member">Member</option><option value="admin">Admin</option><option value="owner">Owner</option></select>' +
        '<button class="btn btn-sm btn-primary" onclick="window.addGroupMember(\'' + groupId + '\')">Add</button>' +
        '</div>' +
        '<div id="group-members-list">' + membersHtml + '</div>' +
        '<div style="margin-top:1rem">' +
        '<button class="btn btn-sm btn-danger" onclick="window.deleteGroup(\'' + groupId + '\')">Delete Group</button>' +
        '</div>';

      window._currentGroupId = groupId;
    } catch (e) { console.error('showGroupDetail:', e); }
  }

  window.createGroup = async function() {
    var name = document.getElementById('new-group-name');
    var desc = document.getElementById('new-group-desc');
    if (!name || !name.value.trim()) return;
    try {
      await window.api('/api/groups', {
        method: 'POST',
        body: JSON.stringify({ name: name.value.trim(), description: (desc ? desc.value.trim() : '') })
      });
      name.value = '';
      if (desc) desc.value = '';
      loadGroups();
    } catch (e) { window.showError('Failed to create group: ' + e.message); }
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
    } catch (e) { window.showError('Failed to add member: ' + e.message); }
  };

  window.removeGroupMember = async function(groupId, userId) {
    if (!confirm('Remove this member?')) return;
    try {
      await window.api('/api/groups/' + groupId + '/members/' + userId, { method: 'DELETE' });
      showGroupDetail(groupId);
    } catch (e) { window.showError('Failed to remove member: ' + e.message); }
  };

  window.deleteGroup = async function(groupId) {
    if (!confirm('Delete this group? This cannot be undone.')) return;
    try {
      await window.api('/api/groups/' + groupId, { method: 'DELETE' });
      document.getElementById('groups-detail').innerHTML = '';
      loadGroups();
    } catch (e) { window.showError('Failed to delete group: ' + e.message); }
  };

  window.loadGroups = loadGroups;
})();
