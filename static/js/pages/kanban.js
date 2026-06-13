// Page: Kanban
(function() {
  'use strict';

  var _boards = [];
  var _currentBoardId = null;
  var _tasks = {};
  var _sortables = {};
  var _users = [];
  var _taskTypes = [
    { value: 'research', label: 'Research' },
    { value: 'agent-driven', label: 'Agent-Driven Development' },
    { value: 'plan', label: 'Plan' },
    { value: 'brainstorm', label: 'Brainstorm' },
    { value: 'backend-only', label: 'Backend Only' },
    { value: 'frontend-only', label: 'Frontend Only' },
    { value: 'other', label: 'Other' },
  ];

  window.loadKanbanPage = async function() {
    try {
      // Load users for assignee dropdown
      try { _users = await window.api('/api/users'); } catch(e) { _users = []; }
      _boards = await window.api('/api/kanban/boards');
      renderBoardSelector();
      if (_boards.length > 0) {
        await window.selectKanbanBoard(_boards[0].id);
      } else {
        document.getElementById('kanban-columns').innerHTML =
          '<div class="kanban-empty-state">No boards yet. <a href="#" onclick="window.newKanbanBoard();return false;">Create one!</a></div>';
      }
    } catch(e) {
      document.getElementById('kanban-columns').innerHTML =
        '<div class="kanban-error-state">Failed to load boards: ' + e.message + '</div>';
    }
  };

  function renderBoardSelector() {
    var el = document.getElementById('kanban-board-selector');
    if (!el) return;
    el.innerHTML = _boards.map(function(b) {
      var active = b.id === _currentBoardId ? ' active' : '';
      return '<div class="kanban-selector-item">' +
        '<button class="btn btn-sm tab-btn' + active + ' kanban-selector-btn" data-board-id="' + b.id + '" onclick="window.selectKanbanBoard(\'' + b.id + '\')">' +
          window.escHtml(b.name) + ' <span class="kanban-selector-count">(' + b.task_count + ')</span>' +
        '</button>' +
        '<button class="btn btn-sm btn-ghost kanban-delete-btn" onclick="event.stopPropagation(); window.deleteKanbanBoard(\'' + b.id + '\', \'' + window.escAttr(b.name) + '\')" title="Delete board">\u2715</button>' +
      '</div>';
    }).join('') +
    '<button class="btn btn-sm btn-primary kanban-btn-new" onclick="window.newKanbanBoard()">+ New Board</button>';
  }

  window.selectKanbanBoard = async function(boardId) {
    _currentBoardId = boardId;
    renderBoardSelector();
    try {
      var board = await window.api('/api/kanban/boards/' + boardId);
      renderBoard(board);
    } catch(e) {
      document.getElementById('kanban-columns').innerHTML =
        '<div class="kanban-error-state">Failed: ' + e.message + '</div>';
    }
  };

  function renderBoard(board) {
    var el = document.getElementById('kanban-columns');
    if (!el) return;
    if (!board.columns || board.columns.length === 0) {
      el.innerHTML = '<div class="kanban-empty-columns">No columns</div>';
      return;
    }

    // Destroy old sortables
    Object.values(_sortables).forEach(function(s) { if (s) s.destroy(); });
    _sortables = {};

    el.innerHTML = board.columns.map(function(col) {
      return '<div class="kanban-col kanban-column" data-col-id="' + col.id + '">' +
        '<div class="kanban-col-header">' +
          '<h4 class="kanban-col-title">' + window.escHtml(col.name) +
            (col.wip_limit ? ' <span class="kanban-col-wip">' + col.task_count + '/' + col.wip_limit + '</span>' : '') +
          '</h4>' +
          '<span class="kanban-col-count">' + col.task_count + '</span>' +
        '</div>' +
        '<div class="kanban-task-list" data-col-id="' + col.id + '">' +
          '<div class="loading kanban-task-list-loading">Loading\u2026</div>' +
        '</div>' +
        '<button class="btn btn-sm kanban-add-btn" onclick="window.quickAddTask(\'' + col.id + '\')">+ Add</button>' +
      '</div>';
    }).join('');

    // Load tasks for this board
    window.api('/api/kanban/boards/' + board.id + '/tasks').then(function(tasks) {
      _tasks = {};
      tasks.forEach(function(t) {
        if (!_tasks[t.column_id]) _tasks[t.column_id] = [];
        _tasks[t.column_id].push(t);
      });
      board.columns.forEach(function(col) {
        renderTaskList(col.id, _tasks[col.id] || []);
      });
      initSortable();
    });
  }

  function renderTaskList(colId, tasks) {
    var list = document.querySelector('.kanban-task-list[data-col-id="' + colId + '"]');
    if (!list) return;
    if (tasks.length === 0) {
      list.innerHTML = '<div class="kanban-empty-list">Empty</div>';
      return;
    }
    list.innerHTML = tasks.map(function(t) {
      var subProgress = t.subtask_count > 0 ? ' <span class="kanban-card-subtask">' + t.subtask_done + '/' + t.subtask_count + '</span>' : '';
      var completedCls = t.completed_at ? ' kanban-card-completed' : '';
      var taskType = (t.metadata && t.metadata.task_type) ? t.metadata.task_type : '';
      var typeBadge = taskType ? ' <span class="kanban-card-type">' + window.escHtml(taskType) + '</span>' : '';
      return '<div class="kanban-card' + completedCls + '" data-task-id="' + t.id + '" onclick="window.openTaskDetail(\'' + t.id + '\')">' +
        '<div class="kanban-card-header">' +
          '<span class="kanban-card-title">' + window.escHtml(t.title) + '</span>' +
          '<span class="kanban-card-prio-dot kanban-prio-' + (t.priority || 'low') + '">●</span>' +
        '</div>' +
        '<div class="kanban-card-footer">' +
          '<span class="kanban-card-number">#' + t.task_number + '</span>' +
          '<span class="kanban-card-assignee">' +
            (t.assignee_name || '') +
            (t.help_wanted ? ' <span class="kanban-card-help">⚠</span>' : '') +
          '</span>' +
          typeBadge +
          subProgress +
        '</div>' +
      '</div>';
    }).join('');
  }

  function initSortable() {
    document.querySelectorAll('.kanban-task-list').forEach(function(el) {
      if (window.Sortable) {
        _sortables[el.dataset.colId] = new Sortable(el, {
          group: 'kanban',
          animation: 150,
          onEnd: function(evt) {
            var taskId = evt.item.dataset.taskId;
            // Use closest .kanban-column from the dropped item for reliable column detection
            var targetCol = evt.item.closest('.kanban-column');
            var newColId = targetCol ? targetCol.dataset.colId : null;
            if (taskId && newColId) {
              window.api('/api/kanban/tasks/' + taskId + '/move', {
                method: 'PATCH',
                body: JSON.stringify({ column_id: newColId, position: evt.newIndex })
              });
            }
          }
        });
      }
    });
  }

  window.openTaskDetail = async function(taskId) {
    try {
      var task = await window.api('/api/kanban/tasks/' + taskId);
      showTaskModal(task);
    } catch(e) {
      if (window.showToast) window.showToast('Failed to load task: ' + e.message, 'error');
    }
  };

  function showTaskModal(task) {
    var existing = document.querySelector('.modal-overlay');
    if (existing) existing.remove();

    var modal = document.createElement('div');
    modal.className = 'modal-overlay';

    var currentType = (task.metadata && task.metadata.task_type) || '';

    // ── Subtasks HTML ──
    var subtasksHtml = '';
    if (task.subtasks && task.subtasks.length > 0) {
      subtasksHtml = task.subtasks.map(function(s) {
        return '<div class="kanban-modal-subtask-item" onclick="window.toggleSubtask(\'' + s.id + '\', ' + !s.completed + ', \'' + task.id + '\')">' +
          '<span class="kanban-subtask-checkbox">' + (s.completed ? '\u2705' : '\u2b1c') + '</span> ' +
          '<span class="kanban-subtask-title' + (s.completed ? ' completed' : '') + '">' + window.escHtml(s.title) + '</span>' +
        '</div>';
      }).join('');
    }

    // ── Dependencies HTML ──
    var depsHtml = '';
    if (task.dependencies && task.dependencies.length > 0) {
      depsHtml = task.dependencies.map(function(d) {
        return '<div class="kanban-modal-dependency-item ' + (d.depends_on_completed ? 'kanban-dep-completed' : 'kanban-dep-pending') + '">' +
          (d.depends_on_completed ? '\u2705 ' : '\u23f3 ') + window.escHtml(d.depends_on_title) +
        '</div>';
      }).join('');
    }

    // ── Comments HTML ──
    var commentsHtml = '';
    if (task.comments && task.comments.length > 0) {
      commentsHtml = task.comments.map(function(c) {
        var ts = c.created_at ? window.relativeTime(c.created_at) : '';
        return '<div class="kanban-modal-comment">' +
          '<span class="kanban-modal-comment-author">' + window.escHtml(c.user_name || 'unknown') + '</span> ' +
          '<span class="kanban-modal-comment-ts">' + ts + '</span><br>' +
          window.escHtml(c.body) +
        '</div>';
      }).join('');
    }

    // ── Status History / Agent Logs HTML ──
    var logsHtml = '';
    if (task.agent_logs && task.agent_logs.length > 0) {
      logsHtml = task.agent_logs.map(function(l) {
        var ts = l.created_at ? window.relativeTime(l.created_at) : '';
        var actionLabel = l.action.replace(/_/g, ' ');
        return '<div class="kanban-modal-log-item">' +
          '<span class="kanban-modal-log-action">' + window.escHtml(actionLabel) + '</span> ' +
          (l.details ? '<span class="kanban-modal-log-details">' + window.escHtml(l.details) + '</span>' : '') +
          '<span class="kanban-modal-log-ts">' + ts + '</span>' +
          (l.user_name ? '<span class="kanban-modal-log-user">by ' + window.escHtml(l.user_name) + '</span>' : '') +
        '</div>';
      }).join('');
    } else {
      logsHtml = '<p style="color:var(--muted);font-size:12px;">No status history yet.</p>';
    }

    // ── Assignee dropdown HTML ──
    var assigneeOptions = '<option value="">Unassigned</option>';
    _users.forEach(function(u) {
      var sel = u.id === task.assignee_id ? ' selected' : '';
      assigneeOptions += '<option value="' + u.id + '"' + sel + '>' + window.escHtml(u.name) + ' (' + u.type + ')</option>';
    });

    // ── Task type dropdown HTML ──
    var typeOptions = '<option value="">None</option>';
    _taskTypes.forEach(function(tt) {
      var sel = tt.value === currentType ? ' selected' : '';
      typeOptions += '<option value="' + tt.value + '"' + sel + '>' + window.escHtml(tt.label) + '</option>';
    });

    var subtaskCount = task.subtask_count || (task.subtasks ? task.subtasks.length : 0);
    var subtaskDone = task.subtask_done || 0;
    var commentCount = task.comments ? task.comments.length : 0;
    var logCount = task.agent_logs ? task.agent_logs.length : 0;

    modal.innerHTML = '<div class="modal kanban-modal">' +
      '<div class="kanban-modal-header">' +
        '<h3 class="kanban-modal-title">#' + task.task_number + ' ' + window.escHtml(task.title) + '</h3>' +
        '<div class="kanban-modal-header-actions">' +
          '<button class="btn btn-sm btn-secondary" onclick="window.saveTaskDetails(\'' + task.id + '\')" title="Save changes">\u2713 Save</button>' +
          '<button class="btn btn-sm btn-secondary" onclick="this.closest(\'.modal-overlay\').remove()" aria-label="Close">&times;</button>' +
        '</div>' +
      '</div>' +
      '<div class="kanban-modal-tabs">' +
        '<button class="kanban-tab-btn active" data-ktab="details">Details</button>' +
        '<button class="kanban-tab-btn" data-ktab="subtasks">Subtasks (' + subtaskDone + '/' + subtaskCount + ')</button>' +
        '<button class="kanban-tab-btn" data-ktab="comments">Comments (' + commentCount + ')</button>' +
        '<button class="kanban-tab-btn" data-ktab="logs">Status (' + logCount + ')</button>' +
      '</div>' +

      // ── Details Tab ──
      '<div class="kanban-tab-content active" data-ktab="details">' +
        '<div class="kanban-modal-editable">' +
          '<label class="kanban-modal-label">Description</label>' +
          '<textarea id="kanban-edit-description" class="kanban-modal-input" rows="3" style="width:100%;resize:vertical;">' + window.escHtml(task.description || '') + '</textarea>' +
        '</div>' +
        '<div class="kanban-modal-meta">' +
          '<div class="kanban-modal-meta-field">' +
            '<label class="kanban-modal-label">Priority</label>' +
            '<select id="kanban-edit-priority" class="kanban-modal-input">' +
              '<option value="low"' + (task.priority === 'low' ? ' selected' : '') + '>Low</option>' +
              '<option value="medium"' + (task.priority === 'medium' ? ' selected' : '') + '>Medium</option>' +
              '<option value="high"' + (task.priority === 'high' ? ' selected' : '') + '>High</option>' +
              '<option value="critical"' + (task.priority === 'critical' ? ' selected' : '') + '>Critical</option>' +
            '</select>' +
          '</div>' +
          '<div class="kanban-modal-meta-field">' +
            '<label class="kanban-modal-label">Task Type</label>' +
            '<select id="kanban-edit-task-type" class="kanban-modal-input">' + typeOptions + '</select>' +
          '</div>' +
          '<div class="kanban-modal-meta-field">' +
            '<label class="kanban-modal-label">Assignee</label>' +
            '<select id="kanban-edit-assignee" class="kanban-modal-input">' + assigneeOptions + '</select>' +
          '</div>' +
          '<div class="kanban-modal-meta-field">' +
            '<label class="kanban-modal-label">Estimate</label>' +
            '<input type="text" id="kanban-edit-estimate" class="kanban-modal-input" value="' + window.escAttr(task.estimate || '') + '" placeholder="e.g. 2h" />' +
          '</div>' +
          '<div class="kanban-modal-meta-field">' +
            '<label class="kanban-modal-label">Due</label>' +
            '<input type="date" id="kanban-edit-due" class="kanban-modal-input" value="' + (task.due_at ? task.due_at.slice(0, 10) : '') + '" />' +
          '</div>' +
        '</div>' +
        (depsHtml ? '<div class="kanban-modal-section"><h4 class="kanban-modal-section-title">Dependencies</h4>' + depsHtml + '</div>' : '') +
      '</div>' +

      // ── Subtasks Tab ──
      '<div class="kanban-tab-content" data-ktab="subtasks">' +
        '<div class="kanban-modal-subtask-list">' +
          (subtasksHtml || '<p style="color:var(--muted);font-size:12px;">No subtasks.</p>') +
        '</div>' +
        '<div class="kanban-modal-input-row" style="margin-top:8px;">' +
          '<input type="text" id="kanban-subtask-input" placeholder="Add subtask\u2026" class="kanban-modal-input" />' +
          '<button class="btn btn-sm btn-primary" onclick="window.addKanbanSubtask(\'' + task.id + '\')">Add</button>' +
        '</div>' +
      '</div>' +

      // ── Comments Tab ──
      '<div class="kanban-tab-content" data-ktab="comments">' +
        '<div class="kanban-modal-comment-list">' +
          (commentsHtml || '<p style="color:var(--muted);font-size:12px;">No comments yet.</p>') +
        '</div>' +
        '<div class="kanban-modal-input-row">' +
          '<input type="text" id="kanban-comment-input" placeholder="Add comment\u2026" class="kanban-modal-input" />' +
          '<button class="btn btn-sm btn-primary" onclick="window.addKanbanComment(\'' + task.id + '\')">Post</button>' +
        '</div>' +
      '</div>' +

      // ── Status History Tab ──
      '<div class="kanban-tab-content" data-ktab="logs">' +
        logsHtml +
      '</div>' +
    '</div>';
    document.body.appendChild(modal);
    modal.classList.add('open');
    modal.addEventListener('click', function(e) { if (e.target === modal) modal.remove(); });

    // Tab switching
    modal.querySelectorAll('.kanban-tab-btn').forEach(function(btn) {
      btn.addEventListener('click', function() {
        var tab = this.getAttribute('data-ktab');
        modal.querySelectorAll('.kanban-tab-btn').forEach(function(b) { b.classList.remove('active'); });
        this.classList.add('active');
        modal.querySelectorAll('.kanban-tab-content').forEach(function(c) { c.classList.remove('active'); });
        var content = modal.querySelector('.kanban-tab-content[data-ktab="' + tab + '"]');
        if (content) content.classList.add('active');
      });
    });

    // Enter key for comment and subtask inputs
    var commentInp = document.getElementById('kanban-comment-input');
    if (commentInp) {
      commentInp.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') window.addKanbanComment(task.id);
      });
    }
    var subtaskInp = document.getElementById('kanban-subtask-input');
    if (subtaskInp) {
      subtaskInp.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') window.addKanbanSubtask(task.id);
      });
    }
  }

  window.saveTaskDetails = async function(taskId) {
    var desc = document.getElementById('kanban-edit-description');
    var prio = document.getElementById('kanban-edit-priority');
    var type = document.getElementById('kanban-edit-task-type');
    var assignee = document.getElementById('kanban-edit-assignee');
    var estimate = document.getElementById('kanban-edit-estimate');
    var due = document.getElementById('kanban-edit-due');

    var updates = {};
    if (desc) updates.description = desc.value || null;
    if (prio) updates.priority = prio.value;
    if (assignee) updates.assignee_id = assignee.value || null;
    if (estimate) updates.estimate = estimate.value || null;
    if (due) updates.due_at = due.value ? due.value + 'T00:00:00Z' : null;

    // Handle task type in metadata
    if (type) {
      var taskType = type.value || null;
      // Get existing metadata
      try {
        var task = await window.api('/api/kanban/tasks/' + taskId);
        var metadata = task.metadata || {};
        if (taskType) {
          metadata.task_type = taskType;
        } else {
          delete metadata.task_type;
        }
        updates.metadata = Object.keys(metadata).length > 0 ? metadata : null;
      } catch(e) {
        if (window.showToast) window.showToast('Failed to load task for metadata', 'error');
        return;
      }
    }

    try {
      await window.api('/api/kanban/tasks/' + taskId, {
        method: 'PATCH',
        body: JSON.stringify(updates)
      });
      // Refresh board
      window.selectKanbanBoard(_currentBoardId);
      if (window.showToast) window.showToast('Task updated', 'success');
    } catch(e) {
      if (window.showToast) window.showToast('Failed to save: ' + e.message, 'error');
    }
  };

  window.addKanbanSubtask = async function(taskId) {
    var input = document.getElementById('kanban-subtask-input');
    if (!input || !input.value.trim()) return;
    try {
      await window.api('/api/kanban/tasks/' + taskId + '/subtasks', {
        method: 'POST',
        body: JSON.stringify({ title: input.value.trim() })
      });
      input.value = '';
      window.openTaskDetail(taskId);
    } catch(e) {
      if (window.showToast) window.showToast('Failed: ' + e.message, 'error');
    }
  };

  window.addKanbanComment = async function(taskId) {
    var input = document.getElementById('kanban-comment-input');
    if (!input || !input.value.trim()) return;
    try {
      await window.api('/api/kanban/tasks/' + taskId + '/comments', {
        method: 'POST',
        body: JSON.stringify({ body: input.value.trim() })
      });
      input.value = '';
      window.openTaskDetail(taskId);
    } catch(e) {
      if (window.showToast) window.showToast('Failed: ' + e.message, 'error');
    }
  };

  window.toggleSubtask = async function(subtaskId, completed, taskId) {
    try {
      await window.api('/api/kanban/subtasks/' + subtaskId, {
        method: 'PATCH',
        body: JSON.stringify({ completed: completed })
      });
      window.openTaskDetail(taskId);
    } catch(e) {
      if (window.showToast) window.showToast('Failed: ' + e.message, 'error');
    }
  };

  window.quickAddTask = function(colId) {
    var list = document.querySelector('.kanban-task-list[data-col-id="' + colId + '"]');
    if (!list) return;
    var existing = document.getElementById('quick-add-' + colId);
    if (existing) { existing.remove(); return; }

    var input = document.createElement('div');
    input.id = 'quick-add-' + colId;
    input.className = 'kanban-quick-add-row';
    input.innerHTML = '<input type="text" id="quick-add-input-' + colId + '" placeholder="Task title…" class="kanban-quick-add-input" />' +
      '<button class="btn btn-sm btn-primary" onclick="window.submitQuickTask(\'' + colId + '\')">Add</button>';
    list.parentNode.insertBefore(input, list.nextSibling);

    var inp = document.getElementById('quick-add-input-' + colId);
    if (inp) {
      inp.focus();
      inp.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') window.submitQuickTask(colId);
        if (e.key === 'Escape') { document.getElementById('quick-add-' + colId).remove(); }
      });
    }
  };

  window.submitQuickTask = async function(colId) {
    var input = document.getElementById('quick-add-input-' + colId);
    if (!input || !input.value.trim()) return;
    try {
      await window.api('/api/kanban/boards/' + _currentBoardId + '/tasks', {
        method: 'POST',
        body: JSON.stringify({ title: input.value.trim(), column_id: colId })
      });
      document.getElementById('quick-add-' + colId).remove();
      window.selectKanbanBoard(_currentBoardId);
    } catch(e) {
      if (window.showToast) window.showToast('Failed: ' + e.message, 'error');
    }
  };

  window.newKanbanBoard = function() {
    var existing = document.querySelector('.modal-overlay');
    if (existing) existing.remove();

    var modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.innerHTML = '<div class="modal kanban-modal" style="max-width:420px;">' +
      '<div class="kanban-modal-header">' +
        '<h3 class="kanban-modal-title">New Board</h3>' +
        '<button class="btn btn-sm btn-secondary" onclick="this.closest(\'.modal-overlay\').remove()" aria-label="Close">&times;</button>' +
      '</div>' +
      '<div style="display:flex;flex-direction:column;gap:12px;">' +
        '<div><label style="font-size:12px;color:var(--muted);display:block;margin-bottom:4px;">Name</label>' +
          '<input type="text" id="new-board-name" class="kanban-modal-input" placeholder="My Board" style="width:100%;" /></div>' +
        '<div><label style="font-size:12px;color:var(--muted);display:block;margin-bottom:4px;">Type</label>' +
          '<div style="display:flex;gap:12px;">' +
            '<label style="font-size:13px;color:var(--fg);cursor:pointer;"><input type="radio" name="new-board-type" value="agentic" checked /> Agentic</label>' +
            '<label style="font-size:13px;color:var(--fg);cursor:pointer;"><input type="radio" name="new-board-type" value="personal" /> Personal</label>' +
          '</div></div>' +
        '<div><label style="font-size:12px;color:var(--muted);display:block;margin-bottom:4px;">Description <span style="font-weight:400;">(optional)</span></label>' +
          '<textarea id="new-board-desc" class="kanban-modal-input" rows="2" style="width:100%;resize:vertical;" placeholder="What is this board for?"></textarea></div>' +
      '</div>' +
      '<div style="display:flex;gap:8px;margin-top:16px;justify-content:flex-end;">' +
        '<button class="btn btn-sm btn-secondary" onclick="this.closest(\'.modal-overlay\').remove()">Cancel</button>' +
        '<button class="btn btn-sm btn-primary" id="btn-create-board">Create</button>' +
      '</div>' +
    '</div>';
    document.body.appendChild(modal);
    modal.classList.add('open');
    modal.addEventListener('click', function(e) { if (e.target === modal) modal.remove(); });

    var createBtn = document.getElementById('btn-create-board');
    createBtn.addEventListener('click', async function() {
      var name = document.getElementById('new-board-name').value.trim();
      if (!name) { if (window.showToast) window.showToast('Name is required', null, null, 3000); return; }
      var type = document.querySelector('input[name="new-board-type"]:checked');
      type = type ? type.value : 'agentic';
      var desc = document.getElementById('new-board-desc').value.trim();
      try {
        await window.api('/api/kanban/boards', {
          method: 'POST',
          body: JSON.stringify({ name: name, type: type, instructions: desc || undefined })
        });
        modal.remove();
        window.loadKanbanPage();
      } catch(e) {
        if (window.showToast) window.showToast('Failed: ' + e.message, null, null, 5000);
      }
    });

    // Focus name input
    var nameInput = document.getElementById('new-board-name');
    if (nameInput) nameInput.focus();

    // Enter key submits
    document.getElementById('new-board-name').addEventListener('keydown', function(e) {
      if (e.key === 'Enter') document.getElementById('btn-create-board').click();
    });
  };

  window.deleteKanbanBoard = async function(boardId, boardName) {
    if (!confirm('Delete "' + boardName + '" and all its tasks?\nThis cannot be undone.')) return;
    try {
      await window.api('/api/kanban/boards/' + boardId, { method: 'DELETE' });
      if (window.showToast) window.showToast('Deleted board: ' + boardName, 'success');
      window.loadKanbanPage();
    } catch(e) {
      if (window.showToast) window.showToast('Failed to delete: ' + e.message, 'error');
    }
  };

  // SSE listener for real-time updates
  // The SSE handler in app.js broadcasts to callbacks; register one
  if (!window._kanbanSseRegistered) {
    window._kanbanSseRegistered = true;
    var origHandler = window._sseCallbacks && window._sseCallbacks['kanban_task_updated'];
    if (!window._sseCallbacks) window._sseCallbacks = {};
    window._sseCallbacks['kanban_task_updated'] = function() {
      if (_currentBoardId) window.selectKanbanBoard(_currentBoardId);
    };
  }
})();
