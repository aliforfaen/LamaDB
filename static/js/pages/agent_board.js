// Page: Agent Board
(function() {
  'use strict';

  window.loadAgentBoardPage = async function() {
    loadInboxUnreadCount();
    loadAgentBoardTasks();
    loadAgentBoardMessages();
    loadAgentBoardInbox();
  };

  function loadInboxUnreadCount() {
    window.api('/api/agent_board/inbox/count').then(function(data) {
      var badge = document.getElementById('badge-inbox');
      var count = data.count || 0;
      if (badge) {
        badge.textContent = count > 0 ? count : '';
        badge.style.display = count > 0 ? 'inline' : 'none';
      }
      var navBadge = document.querySelector('.nav-item[data-page="agentboard"] .tab-badge');
      if (navBadge) {
        navBadge.textContent = count > 0 ? count : '';
        navBadge.style.display = count > 0 ? 'inline' : 'none';
      }
    }).catch(function() {});
  }

  function loadAgentBoardInbox() {
    window.api('/api/agent_board/inbox').then(function(messages) {
      renderInboxList(messages);
    }).catch(function(e) {
      var el = document.getElementById('ab-inbox-list');
      if (el) el.innerHTML = '<div style="color:var(--danger);padding:10px;">Failed: ' + e.message + '</div>';
    });
  }

  function renderInboxList(messages) {
    var el = document.getElementById('ab-inbox-list');
    if (!el) return;
    if (!Array.isArray(messages) || messages.length === 0) {
      el.innerHTML = '<div style="color:var(--muted);padding:20px;text-align:center;">No messages in inbox.</div>'; return;
    }
    el.innerHTML = messages.map(function(m) {
      var ts = m.created_at ? window.relativeTime(m.created_at) : '';
      var readClass = m.read ? '' : 'style="border-left:3px solid var(--accent);font-weight:600;"';
      return '<div class="ab-msg-item" ' + readClass + ' onclick="window.viewInboxMsg(\'' + m.id + '\')" style="cursor:pointer;padding:10px 12px;border-bottom:1px solid var(--border-light);background:var(--surface);">' +
        '<div style="display:flex;justify-content:space-between;align-items:center;">' +
          '<span style="font-size:13px;color:var(--fg);">' + window.escHtml(m.subject || m.title || '(no subject)') + '</span>' +
          '<span style="font-size:11px;color:var(--muted);font-family:var(--font-mono);">' + ts + '</span>' +
        '</div>' +
        '<div style="font-size:12px;color:var(--fg-2);margin-top:4px;">' +
          (m.from_agent ? '<span style="color:var(--accent-cyan);">From: ' + window.escHtml(m.from_agent) + '</span>' : '') +
          (m.to_agent ? ' <span style="color:var(--accent);">To: ' + window.escHtml(m.to_agent) + '</span>' : '') +
        '</div>' +
        (m.body ? '<div style="font-size:12px;color:var(--muted);margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + window.escHtml(m.body.substring(0, 100)) + '</div>' : '') +
      '</div>';
    }).join('');
  }

  window.viewInboxMsg = function(msgId) {
    window.api('/api/agent_board/messages/' + msgId + '/read', { method: 'POST' }).then(function() {
      loadAgentBoardInbox();
      loadInboxUnreadCount();
    }).catch(function() {});
    window.api('/api/agent_board/thread/' + msgId).then(function(thread) {
      var el = document.getElementById('ab-inbox-detail');
      if (!el) return;
      if (!Array.isArray(thread) || thread.length === 0) {
        el.innerHTML = '<div style="color:var(--muted);padding:20px;">No messages</div>'; return;
      }
      el.innerHTML = thread.map(function(m) {
        var ts = m.created_at ? window.relativeTime(m.created_at) : '';
        return '<div style="background:var(--surface-2);border:1px solid var(--border);border-radius:var(--radius);padding:12px;margin-bottom:8px;">' +
          '<div style="display:flex;justify-content:space-between;font-size:12px;color:var(--muted);margin-bottom:4px;">' +
            '<span>' + window.escHtml(m.from_agent || 'system') + ' \u2192 ' + window.escHtml(m.to_agent || 'all') + '</span>' +
            '<span>' + ts + '</span>' +
          '</div>' +
          '<div style="font-size:13px;font-weight:600;color:var(--fg);">' + window.escHtml(m.subject || m.title || '') + '</div>' +
          (m.body ? '<div style="font-size:12px;color:var(--fg-2);margin-top:6px;line-height:1.5;">' + window.escHtml(m.body) + '</div>' : '') +
        '</div>';
      }).join('');
      if (el.innerHTML) {
        el.innerHTML += '<div style="margin-top:8px;display:flex;gap:8px;">' +
          '<input type="text" id="inbox-reply-input" placeholder="Type reply\u2026" style="flex:1;background:var(--surface-2);border:1px solid var(--border);border-radius:var(--radius-sm);padding:6px 10px;color:var(--fg);font-family:var(--font-display);font-size:13px;" />' +
          '<button class="btn btn-sm btn-primary" onclick="window.replyToThread(\'' + msgId + '\')">Send</button>' +
        '</div>';
      }
    }).catch(function() {});
  };

  window.replyToThread = function(threadId) {
    var input = document.getElementById('inbox-reply-input');
    if (!input || !input.value.trim()) return;
    window.api('/api/agent_board/messages', {
      method: 'POST',
      body: JSON.stringify({ reply_to: threadId, subject: 'Re:', body: input.value.trim(), to_agent: 'hermes' })
    }).then(function() {
      input.value = '';
      window.viewInboxMsg(threadId);
    }).catch(function(e) { alert('Failed to send: ' + e.message); });
  };

  function loadAgentBoardTasks() {
    window.api('/api/agent_board/tasks').then(function(tasks) {
      renderAbTasks(tasks);
    }).catch(function(e) {
      var el = document.getElementById('ab-tasks');
      if (el) el.innerHTML = '<div style="color:var(--danger);padding:10px;">Failed: ' + e.message + '</div>';
    });
  }

  function renderAbTasks(tasks) {
    var el = document.getElementById('ab-tasks-content');
    if (!el) return;
    if (!Array.isArray(tasks) || tasks.length === 0) {
      el.innerHTML = '<div style="color:var(--muted);padding:20px;text-align:center;">No tasks.</div>'; return;
    }
    el.innerHTML = '<div class="table-wrap"><table><thead><tr><th>ID</th><th>Type</th><th>Status</th><th>Agent</th><th>Created</th></tr></thead><tbody>' +
      tasks.map(function(t) {
        var statusClass = t.status === 'completed' ? 'info' : t.status === 'failed' ? 'critical' : 'warn';
        return '<tr>' +
          '<td class="mono" style="font-size:11px;">' + (t.id ? t.id.substring(0, 8) : '') + '</td>' +
          '<td>' + window.escHtml(t.task_type || t.type || '') + '</td>' +
          '<td><span class="sev-badge ' + statusClass + '">' + (t.status || 'pending') + '</span></td>' +
          '<td>' + window.escHtml(t.assigned_to || t.agent || '') + '</td>' +
          '<td class="mono" style="font-size:12px;">' + window.relativeTime(t.created_at) + '</td>' +
        '</tr>';
      }).join('') +
    '</tbody></table></div>';
  }

  function loadAgentBoardMessages() {
    window.api('/api/agent_board/messages').then(function(messages) {
      renderAbMessages(messages);
    }).catch(function(e) {
      var el = document.getElementById('ab-messages');
      if (el) el.innerHTML = '<div style="color:var(--danger);padding:10px;">Failed: ' + e.message + '</div>';
    });
  }

  function renderAbMessages(messages) {
    var el = document.getElementById('ab-messages-content');
    if (!el) return;
    if (!Array.isArray(messages) || messages.length === 0) {
      el.innerHTML = '<div style="color:var(--muted);padding:20px;text-align:center;">No messages.</div>'; return;
    }
    el.innerHTML = messages.map(function(m) {
      var ts = m.created_at ? window.relativeTime(m.created_at) : '';
      return '<div style="background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:10px 12px;margin-bottom:6px;">' +
        '<div style="display:flex;justify-content:space-between;font-size:12px;">' +
          '<span style="color:var(--fg-2);">' + window.escHtml(m.from_agent || '') + ' \u2192 ' + window.escHtml(m.to_agent || '') + '</span>' +
          '<span style="color:var(--muted);font-family:var(--font-mono);">' + ts + '</span>' +
        '</div>' +
        '<div style="font-size:13px;font-weight:500;color:var(--fg);margin-top:4px;">' + window.escHtml(m.subject || m.title || '') + '</div>' +
        (m.body ? '<div style="font-size:12px;color:var(--fg-2);margin-top:4px;">' + window.escHtml(m.body.substring(0, 150)) + '</div>' : '') +
      '</div>';
    }).join('');
  }
})();
