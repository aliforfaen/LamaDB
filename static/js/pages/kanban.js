// Page: Kanban
(function() {
  'use strict';

  var _boards = [];
  var _currentBoardId = null;
  var _tasks = {};
  var _sortables = {};

  window.loadKanbanPage = async function() {
    try {
      _boards = await window.api('/api/kanban/boards');
      renderBoardSelector();
      if (_boards.length > 0) {
        await window.selectKanbanBoard(_boards[0].id);
      } else {
        document.getElementById('kanban-columns').innerHTML =
          '<div style="color:var(--muted);padding:40px;text-align:center;">No boards yet. <a href="#" onclick="window.newKanbanBoard();return false;">Create one!</a></div>';
      }
    } catch(e) {
      document.getElementById('kanban-columns').innerHTML =
        '<div style="color:var(--danger);padding:20px;">Failed to load boards: ' + e.message + '</div>';
    }
  };

  function renderBoardSelector() {
    var el = document.getElementById('kanban-board-selector');
    if (!el) return;
    el.innerHTML = _boards.map(function(b) {
      var active = b.id === _currentBoardId ? ' active' : '';
      return '<button class="btn btn-sm tab-btn' + active + '" data-board-id="' + b.id + '" onclick="window.selectKanbanBoard(\'' + b.id + '\')" style="border:1px solid var(--border);">' +
        window.escHtml(b.name) + ' <span style="color:var(--muted);font-size:11px;">(' + b.task_count + ')</span>' +
      '</button>';
    }).join('') +
    '<button class="btn btn-sm btn-primary" onclick="window.newKanbanBoard()" style="margin-left:4px;">+ New Board</button>';
  }

  window.selectKanbanBoard = async function(boardId) {
    _currentBoardId = boardId;
    renderBoardSelector();
    try {
      var board = await window.api('/api/kanban/boards/' + boardId);
      renderBoard(board);
    } catch(e) {
      document.getElementById('kanban-columns').innerHTML =
        '<div style="color:var(--danger);padding:20px;">Failed: ' + e.message + '</div>';
    }
  };

  function renderBoard(board) {
    var el = document.getElementById('kanban-columns');
    if (!el) return;
    if (!board.columns || board.columns.length === 0) {
      el.innerHTML = '<div style="color:var(--muted);padding:20px;">No columns</div>';
      return;
    }

    // Destroy old sortables
    Object.values(_sortables).forEach(function(s) { if (s) s.destroy(); });
    _sortables = {};

    el.innerHTML = board.columns.map(function(col) {
      return '<div class="kanban-col" data-col-id="' + col.id + '" style="background:var(--surface-2);border-radius:var(--radius);padding:10px;min-height:100px;">' +
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">' +
          '<h4 style="margin:0;font-size:13px;color:var(--fg);">' + window.escHtml(col.name) +
            (col.wip_limit ? ' <span style="color:var(--muted);font-size:11px;">' + col.task_count + '/' + col.wip_limit + '</span>' : '') +
          '</h4>' +
          '<span style="font-size:11px;color:var(--muted);">' + col.task_count + '</span>' +
        '</div>' +
        '<div class="kanban-task-list" data-col-id="' + col.id + '" style="min-height:40px;">' +
          '<div class="loading" style="font-size:12px;color:var(--muted);">Loading\u2026</div>' +
        '</div>' +
        '<button class="btn btn-sm" style="width:100%;margin-top:8px;color:var(--muted);background:transparent;border:1px dashed var(--border);" onclick="window.quickAddTask(\'' + col.id + '\')">+ Add</button>' +
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
      list.innerHTML = '<div style="color:var(--muted);font-size:12px;padding:10px;text-align:center;">Empty</div>';
      return;
    }
    list.innerHTML = tasks.map(function(t) {
      var prioColor = {low:'var(--success)', medium:'var(--accent-yellow)', high:'var(--warn)', critical:'var(--danger)'}[t.priority] || 'var(--muted)';
      var subProgress = t.subtask_count > 0 ? ' <span style="font-size:10px;color:var(--muted);">' + t.subtask_done + '/' + t.subtask_count + '</span>' : '';
      return '<div class="kanban-card" data-task-id="' + t.id + '" style="background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-sm);padding:8px;margin-bottom:6px;cursor:grab;' + (t.completed_at ? 'opacity:0.5;' : '') + '" onclick="window.openTaskDetail(\'' + t.id + '\')">' +
        '<div style="display:flex;justify-content:space-between;align-items:flex-start;">' +
          '<span style="font-size:13px;color:var(--fg);font-weight:500;flex:1;">' + window.escHtml(t.title) + '</span>' +
          '<span style="color:' + prioColor + ';font-size:16px;line-height:1;margin-left:4px;">●</span>' +
        '</div>' +
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-top:6px;">' +
          '<span style="font-size:11px;color:var(--muted);font-family:var(--font-mono);">#' + t.task_number + '</span>' +
          '<span style="font-size:11px;color:var(--fg-2);">' +
            (t.assignee_name || '') +
            (t.help_wanted ? ' <span style="color:var(--warn);">⚠</span>' : '') +
          '</span>' +
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
            var newColId = evt.to.dataset.colId;
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
    modal.innerHTML = '<div class="modal" style="max-width:600px;max-height:80vh;overflow-y:auto;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:20px;position:relative;">' +
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">' +
        '<h3 style="margin:0;">#' + task.task_number + ' ' + window.escHtml(task.title) + '</h3>' +
        '<button class="btn btn-sm btn-secondary" onclick="this.closest(\'.modal-overlay\').remove()">×</button>' +
      '</div>' +
      (task.description ? '<div style="color:var(--fg-2);font-size:13px;margin-bottom:12px;line-height:1.5;">' + window.escHtml(task.description) + '</div>' : '') +
      '<div style="display:flex;gap:12px;font-size:12px;color:var(--muted);margin-bottom:12px;flex-wrap:wrap;">' +
        '<span>Priority: <strong>' + task.priority + '</strong></span>' +
        '<span>Assignee: <strong>' + (task.assignee_name || 'unassigned') + '</strong></span>' +
        (task.estimate ? '<span>Estimate: <strong>' + task.estimate + '</strong></span>' : '') +
        (task.due_at ? '<span>Due: <strong>' + new Date(task.due_at).toLocaleDateString() + '</strong></span>' : '') +
      '</div>' +
      (task.subtasks.length > 0 ? '<div style="margin-bottom:12px;"><h4 style="font-size:12px;color:var(--muted);margin-bottom:4px;">Subtasks (' + task.subtask_done + '/' + task.subtask_count + ')</h4>' +
        task.subtasks.map(function(s) {
          return '<div style="font-size:12px;padding:4px 0;cursor:pointer;" onclick="window.toggleSubtask(\'' + s.id + '\', ' + !s.completed + ', \'' + task.id + '\')">' +
            (s.completed ? '✅ ' : '⬜ ') + window.escHtml(s.title) +
          '</div>';
        }).join('') +
      '</div>' : '') +
      (task.dependencies.length > 0 ? '<div style="margin-bottom:12px;"><h4 style="font-size:12px;color:var(--muted);margin-bottom:4px;">Dependencies</h4>' +
        task.dependencies.map(function(d) {
          return '<div style="font-size:12px;padding:2px 0;color:' + (d.depends_on_completed ? 'var(--success)' : 'var(--muted)') + ';">' +
            (d.depends_on_completed ? '✅ ' : '⏳ ') + window.escHtml(d.depends_on_title) +
          '</div>';
        }).join('') +
      '</div>' : '') +
      (task.comments.length > 0 ? '<div style="margin-bottom:12px;"><h4 style="font-size:12px;color:var(--muted);margin-bottom:4px;">Comments</h4>' +
        task.comments.map(function(c) {
          var ts = c.created_at ? window.relativeTime(c.created_at) : '';
          return '<div style="background:var(--surface-2);padding:8px;border-radius:var(--radius-sm);margin-bottom:4px;font-size:12px;">' +
            '<span style="color:var(--accent);font-weight:500;">' + window.escHtml(c.user_name || 'unknown') + '</span> ' +
            '<span style="color:var(--muted);font-size:10px;">' + ts + '</span><br>' +
            window.escHtml(c.body) +
          '</div>';
        }).join('') +
      '</div>' : '') +
      '<div style="display:flex;gap:8px;border-top:1px solid var(--border);padding-top:12px;">' +
        '<input type="text" id="kanban-comment-input" placeholder="Add comment…" style="flex:1;background:var(--surface-2);border:1px solid var(--border);border-radius:var(--radius-sm);padding:6px 10px;color:var(--fg);font-size:13px;" />' +
        '<button class="btn btn-sm btn-primary" onclick="window.addKanbanComment(\'' + task.id + '\')">Post</button>' +
      '</div>' +
    '</div>';
    document.body.appendChild(modal);
    modal.classList.add('open');
    modal.addEventListener('click', function(e) { if (e.target === modal) modal.remove(); });

    // Focus comment input
    var inp = document.getElementById('kanban-comment-input');
    if (inp) {
      inp.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') window.addKanbanComment(task.id);
      });
    }
  }

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
    input.style.cssText = 'display:flex;gap:4px;margin-top:4px;';
    input.innerHTML = '<input type="text" id="quick-add-input-' + colId + '" placeholder="Task title…" style="flex:1;background:var(--surface);border:1px solid var(--accent);border-radius:var(--radius-sm);padding:5px 8px;color:var(--fg);font-size:12px;" />' +
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

  window.newKanbanBoard = async function() {
    var name = prompt('Board name:');
    if (!name) return;
    var type = confirm('Agentic board?\n(OK = agentic, Cancel = personal)') ? 'agentic' : 'personal';
    try {
      await window.api('/api/kanban/boards', {
        method: 'POST',
        body: JSON.stringify({ name: name, type: type })
      });
      window.loadKanbanPage();
    } catch(e) {
      if (window.showToast) window.showToast('Failed: ' + e.message, 'error');
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
