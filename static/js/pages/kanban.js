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
    modal.innerHTML = '<div class="modal kanban-modal">' +
      '<div class="kanban-modal-header">' +
        '<h3 class="kanban-modal-title">#' + task.task_number + ' ' + window.escHtml(task.title) + '</h3>' +
        '<button class="btn btn-sm btn-secondary" onclick="this.closest(\'.modal-overlay\').remove()">×</button>' +
      '</div>' +
      (task.description ? '<div class="kanban-modal-description">' + window.escHtml(task.description) + '</div>' : '') +
      '<div class="kanban-modal-meta">' +
        '<span>Priority: <strong>' + task.priority + '</strong></span>' +
        '<span>Assignee: <strong>' + (task.assignee_name || 'unassigned') + '</strong></span>' +
        (task.estimate ? '<span>Estimate: <strong>' + task.estimate + '</strong></span>' : '') +
        (task.due_at ? '<span>Due: <strong>' + new Date(task.due_at).toLocaleDateString() + '</strong></span>' : '') +
      '</div>' +
      (task.subtasks.length > 0 ? '<div class="kanban-modal-section"><h4 class="kanban-modal-section-title">Subtasks (' + task.subtask_done + '/' + task.subtask_count + ')</h4>' +
        task.subtasks.map(function(s) {
          return '<div class="kanban-modal-subtask-item" onclick="window.toggleSubtask(\'' + s.id + '\', ' + !s.completed + ', \'' + task.id + '\')">' +
            (s.completed ? '✅ ' : '⬜ ') + window.escHtml(s.title) +
          '</div>';
        }).join('') +
      '</div>' : '') +
      (task.dependencies.length > 0 ? '<div class="kanban-modal-section"><h4 class="kanban-modal-section-title">Dependencies</h4>' +
        task.dependencies.map(function(d) {
          return '<div class="kanban-modal-dependency-item ' + (d.depends_on_completed ? 'kanban-dep-completed' : 'kanban-dep-pending') + '">' +
            (d.depends_on_completed ? '✅ ' : '⏳ ') + window.escHtml(d.depends_on_title) +
          '</div>';
        }).join('') +
      '</div>' : '') +
      (task.comments.length > 0 ? '<div class="kanban-modal-section"><h4 class="kanban-modal-section-title">Comments</h4>' +
        task.comments.map(function(c) {
          var ts = c.created_at ? window.relativeTime(c.created_at) : '';
          return '<div class="kanban-modal-comment">' +
            '<span class="kanban-modal-comment-author">' + window.escHtml(c.user_name || 'unknown') + '</span> ' +
            '<span class="kanban-modal-comment-ts">' + ts + '</span><br>' +
            window.escHtml(c.body) +
          '</div>';
        }).join('') +
      '</div>' : '') +
      '<div class="kanban-modal-input-row">' +
        '<input type="text" id="kanban-comment-input" placeholder="Add comment…" class="kanban-modal-input" />' +
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
