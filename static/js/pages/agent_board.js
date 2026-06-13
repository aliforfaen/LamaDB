// Page: Agent Board — Central Dashboard
(function() {
  'use strict';

  /* ─── PAGE LOADER ──────────────────────────────────────────────────── */
  window.loadAgentBoardPage = async function() {
    loadAbStatGrid();
    loadAbAgentProfiles();
    loadAbMessagesSummary();
    loadAbMcpStatus();
    loadAbApiErrors();
    loadInboxUnreadCount();
  };

  /* ─── TAB SWITCHING ────────────────────────────────────────────────── */
  window.switchAgentBoardTab = function(tab) {
    document.querySelectorAll('#page-agentboard .sub-tab-btn').forEach(function(btn) {
      btn.classList.toggle('active', btn.id === 'ab-tab-' + tab);
    });
    var dashboardEl = document.getElementById('ab-dashboard');
    var tasksEl = document.getElementById('ab-tasks-container');
    var inboxEl = document.getElementById('ab-inbox-container');

    dashboardEl.style.display = tab === 'dashboard' ? '' : 'none';
    tasksEl.style.display = tab === 'tasks' ? '' : 'none';
    inboxEl.style.display = tab === 'inbox' ? '' : 'none';

    if (tab === 'tasks') loadAbTasks();
    if (tab === 'inbox') { loadAgentBoardInbox(); loadInboxUnreadCount(); }
  };

  /* ─── INBOX (remains for the Inbox tab) ───────────────────────────── */
  function loadInboxUnreadCount() {
    window.api('/api/agent_board/inbox/count').then(function(data) {
      var badge = document.getElementById('badge-inbox');
      var count = data.unread || 0;
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

  window.loadAgentBoardInbox = function() {
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
      var messages = thread.thread || thread;
      if (!Array.isArray(messages) || messages.length === 0) {
        el.innerHTML = '<div style="color:var(--muted);padding:20px;">No messages</div>'; return;
      }
      el.innerHTML = messages.map(function(m) {
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

  window.markAllInboxRead = function() {
    window.api('/api/agent_board/messages/read-all', {
      method: 'PATCH',
      body: JSON.stringify({})
    }).then(function() {
      loadAgentBoardInbox();
      loadInboxUnreadCount();
    }).catch(function() {});
  };

  window.inboxAgentChanged = function(agent) {
    loadAgentBoardInbox();
  };

  /* ─── DASHBOARD: STAT BAR ─────────────────────────────────────────── */
  function loadAbStatGrid() {
    // Agents count
    window.api('/api/users').then(function(users) {
      var count = Array.isArray(users) ? users.length : 0;
      var el = document.getElementById('ab-stat-agents');
      if (el) el.textContent = count;
    }).catch(function() {});

    // Tasks count
    window.api('/api/agent_board/tasks?limit=200').then(function(tasks) {
      var count = Array.isArray(tasks) ? tasks.length : 0;
      var el = document.getElementById('ab-stat-tasks');
      if (el) el.textContent = count;
    }).catch(function() {});

    // Messages count
    window.api('/api/agent_board/messages?limit=200').then(function(msgs) {
      var count = Array.isArray(msgs) ? msgs.length : 0;
      var el = document.getElementById('ab-stat-messages');
      if (el) el.textContent = count;
    }).catch(function() {});

    // Unread count
    window.api('/api/agent_board/inbox/count').then(function(data) {
      var el = document.getElementById('ab-stat-unread');
      if (el) el.textContent = data.unread || 0;
    }).catch(function() {});
  }

  /* ─── DASHBOARD: AGENT PROFILES ───────────────────────────────────── */
  function loadAbAgentProfiles() {
    var list = document.getElementById('ab-agent-profiles-list');
    if (!list) return;
    window.api('/api/users').then(function(users) {
      var countEl = document.getElementById('ab-agent-count');
      if (countEl && Array.isArray(users)) countEl.textContent = users.length + (users.length === 1 ? ' agent' : ' agents');

      if (!Array.isArray(users) || users.length === 0) {
        list.innerHTML = '<div class="ab-empty">No agents found.</div>';
        return;
      }

      // Show only first 8 agents (limit for dashboard card)
      var display = users.slice(0, 8);
      list.innerHTML = display.map(function(u) {
        var initial = (u.name || '?')[0].toUpperCase();
        var typeClass = u.type === 'human' ? 'human' : 'agent';
        var isActive = u.status === 'active';
        var statusDot = isActive
          ? '<span class="status-dot" style="background:var(--accent);display:inline-block;width:6px;height:6px;border-radius:50%;"></span>'
          : '<span class="status-dot" style="background:var(--muted);display:inline-block;width:6px;height:6px;border-radius:50%;"></span>';
        var taskInfo = (u.open_tasks !== undefined)
          ? (u.open_tasks + ' open / ' + (u.completed_tasks || 0) + ' done')
          : '';
        return '<div class="ab-agent-card">' +
          '<div class="ab-agent-avatar ' + typeClass + '">' + initial + '</div>' +
          '<div class="ab-agent-info">' +
            '<div class="name">' + window.escHtml(u.name) + '</div>' +
            '<div class="meta">' +
              '<span class="ab-type-badge ' + typeClass + '">' + u.type + '</span>' +
              '<span>' + taskInfo + '</span>' +
            '</div>' +
          '</div>' +
          '<div class="ab-agent-status">' +
            statusDot +
            '<span>' + u.status + '</span>' +
          '</div>' +
        '</div>';
      }).join('');

      if (users.length > 8) {
        list.innerHTML += '<div style="text-align:center;padding-top:6px;font-size:12px;color:var(--muted);">+' + (users.length - 8) + ' more</div>';
      }
    }).catch(function(e) {
      list.innerHTML = '<div style="color:var(--danger);padding:10px;">Failed: ' + e.message + '</div>';
    });
  }

  /* ─── DASHBOARD: MESSAGES SUMMARY ─────────────────────────────────── */
  function loadAbMessagesSummary() {
    var list = document.getElementById('ab-messages-summary-list');
    if (!list) return;

    // Get total count from inbox (all agents)
    window.api('/api/agent_board/inbox/count').then(function(data) {
      var unread = data.unread || 0;
      var countEl = document.getElementById('ab-msg-summary-count');
      if (countEl) countEl.textContent = unread + ' unread';

      // Now get total messages count
      window.api('/api/agent_board/messages?limit=200').then(function(msgs) {
        var total = Array.isArray(msgs) ? msgs.length : 0;

        // Count sent vs received
        var sent = 0;
        var received = 0;
        if (Array.isArray(msgs)) {
          msgs.forEach(function(m) {
            if (m.from_agent && m.from_agent !== 'system') sent++;
            if (m.to_agent && m.to_agent !== 'system') received++;
          });
        }

        list.innerHTML =
          '<div class="ab-msg-summary-row"><span class="label">Total Messages</span><span class="value">' + total + '</span></div>' +
          '<div class="ab-msg-summary-row"><span class="label">Sent</span><span class="value green">' + sent + '</span></div>' +
          '<div class="ab-msg-summary-row"><span class="label">Received</span><span class="value">' + received + '</span></div>' +
          '<div class="ab-msg-summary-row"><span class="label">Unread</span><span class="value' + (unread > 0 ? ' warn' : '') + '">' + unread + '</span></div>';
      }).catch(function() {
        list.innerHTML = '<div class="ab-msg-summary-row"><span class="label">Unread</span><span class="value' + (unread > 0 ? ' warn' : '') + '">' + unread + '</span></div>';
      });
    }).catch(function(e) {
      list.innerHTML = '<div style="color:var(--danger);padding:10px;">Failed: ' + e.message + '</div>';
    });
  }

  /* ─── DASHBOARD: MCP SERVER STATUS ────────────────────────────────── */
  function loadAbMcpStatus() {
    var body = document.getElementById('ab-mcp-status-body');
    if (!body) return;

    // Ping MCP server with a tools/list JSON-RPC call
    window.api('/api/mcp', {
      method: 'POST',
      body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list', params: {} })
    }).then(function(resp) {
      var tools = resp && resp.result && resp.result.tools;
      var toolCount = Array.isArray(tools) ? tools.length : 0;
      var countEl = document.getElementById('ab-mcp-toolcount');
      if (countEl) countEl.textContent = toolCount + ' tools';
      body.innerHTML =
        '<div class="ab-mcp-status-line">' +
          '<span class="mcp-dot online"></span>' +
          '<span class="mcp-label">Online</span>' +
          '<span class="mcp-tools">' + toolCount + ' registered tool' + (toolCount !== 1 ? 's' : '') + '</span>' +
        '</div>';
    }).catch(function() {
      var countEl = document.getElementById('ab-mcp-toolcount');
      if (countEl) countEl.textContent = '';
      body.innerHTML =
        '<div class="ab-mcp-status-line">' +
          '<span class="mcp-dot offline"></span>' +
          '<span class="mcp-label">Offline</span>' +
          '<span class="mcp-tools">—</span>' +
        '</div>';
    });
  }

  /* ─── DASHBOARD: RECENT API ERRORS ────────────────────────────────── */
  function loadAbApiErrors() {
    var list = document.getElementById('ab-api-errors-list');
    if (!list) return;

    window.api('/api/events?severity=error&limit=5').then(function(events) {
      var countEl = document.getElementById('ab-error-count');
      if (countEl && Array.isArray(events)) countEl.textContent = events.length + ' recent';

      if (!Array.isArray(events) || events.length === 0) {
        list.innerHTML = '<div class="ab-empty">No recent errors.</div>';
        return;
      }

      list.innerHTML = events.map(function(e) {
        var ts = e.ts ? window.relativeTime(e.ts) : '';
        var source = e.source ? window.escHtml(e.source) : '';
        return '<div class="ab-error-item">' +
          '<span class="ab-err-icon">\u26a0</span>' +
          '<div class="ab-err-body">' +
            '<div class="ab-err-title">' + window.escHtml(e.title) + '</div>' +
            '<div class="ab-err-meta">' +
              (source ? source + ' \u00b7 ' : '') +
              ts +
            '</div>' +
          '</div>' +
        '</div>';
      }).join('');
    }).catch(function(e) {
      list.innerHTML = '<div style="color:var(--danger);padding:10px;">Failed: ' + e.message + '</div>';
    });
  }

  /* ─── DASHBOARD: TASKS LIST (for Tasks tab) ───────────────────────── */
  function loadAbTasks() {
    var el = document.getElementById('ab-tasks-content');
    if (!el) return;
    el.innerHTML = '<p class="loading">Loading\u2026</p>';
    window.api('/api/agent_board/tasks').then(function(tasks) {
      if (!Array.isArray(tasks) || tasks.length === 0) {
        el.innerHTML = '<div style="color:var(--muted);padding:20px;text-align:center;">No tasks.</div>'; return;
      }
      el.innerHTML = '<table><thead><tr><th>ID</th><th>Type</th><th>Status</th><th>Agent</th><th>Created</th></tr></thead><tbody>' +
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
      '</tbody></table>';
    }).catch(function(e) {
      el.innerHTML = '<div style="color:var(--danger);padding:10px;">Failed: ' + e.message + '</div>';
    });
  }

})();
