// Drag-and-drop initialization for overview module cards
(function() {
  'use strict';

  var _sortable = null;

  window.initDragDrop = function(moduleCards) {
    var grid = document.getElementById('modules-grid');
    if (!grid) return;

    // Destroy previous Sortable instance to avoid duplicating handlers
    if (_sortable) {
      _sortable.destroy();
      _sortable = null;
    }

    // Clear existing content
    grid.innerHTML = '';
    moduleCards.forEach(function(card) {
      grid.appendChild(card);
    });

    // Initialize SortableJS
    if (typeof Sortable !== 'undefined') {
      _sortable = new Sortable(grid, {
        animation: 150,
        ghostClass: 'sortable-ghost',
        dragClass: 'sortable-drag',
        onEnd: function() {
          saveLayout();
        }
      });
    }
  };

  function saveLayout() {
    var grid = document.getElementById('modules-grid');
    if (!grid) return;
    var cards = grid.querySelectorAll('.module-card');
    var moduleOrder = [];
    cards.forEach(function(card) {
      moduleOrder.push(card.getAttribute('data-widget-id') || '');
    });

    window.api('/api/dashboard/user-layout?page=overview', {
      method: 'PUT',
      body: JSON.stringify({ module_order: moduleOrder })
    }).catch(function() { /* silent fail */ });
  }

  window.loadLayout = async function() {
    try {
      var data = await window.api('/api/dashboard/user-layout?page=overview');
      return data.layout.module_order || [];
    } catch (e) {
      return ['uptime', 'hermes', 'freshrss', 'ntfy', 'dozzle', 'notflix', 'wiki', 'feeds', 'notifications'];
    }
  };
})();
