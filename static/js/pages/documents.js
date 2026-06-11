// Page: Documents
(function() {
  'use strict';

  var _docs = [];
  var _docPage = 0;
  var _docPerPage = 20;
  var _docHasMore = false;
  var _docFilter = '';
  var _docFilterTimeout = null;
  var _docSortField = 'created_at';
  var _docSortDir = -1;
  var _docSelected = {};

  window._docFilter = _docFilter;

  window.loadDocuments = async function() {
    try {
      var data = await window.api('/api/documents?limit=' + _docPerPage + '&offset=' + (_docPage * _docPerPage));
      _docs = data || [];
      _docHasMore = _docs.length === _docPerPage;
      renderDocumentTable();
    } catch (e) {
      window.showError('Failed to load documents: ' + e.message);
    }
  };

  function renderDocumentTable() {
    var tbody = document.getElementById('doc-tbody');
    if (!tbody) return;
    var filtered = _docs;
    if (window._docFilter) {
      var q = window._docFilter.toLowerCase();
      filtered = _docs.filter(function(d) { return d.title && d.title.toLowerCase().indexOf(q) !== -1; });
    }
    var sorted = filtered.slice().sort(function(a, b) {
      var va, vb;
      if (_docSortField === 'tags') {
        va = (a.tags || []).join(',').toLowerCase();
        vb = (b.tags || []).join(',').toLowerCase();
      } else {
        va = (a[_docSortField] || '').toString().toLowerCase();
        vb = (b[_docSortField] || '').toString().toLowerCase();
      }
      if (va < vb) return -1 * _docSortDir;
      if (va > vb) return 1 * _docSortDir;
      return 0;
    });
    if (sorted.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" style="color:var(--muted);text-align:center;padding:30px;">No documents found.</td></tr>';
      updateDocPagination();
      updateDocBulkToolbar();
      return;
    }
    tbody.innerHTML = sorted.map(function(doc) {
      var tags = (doc.tags || []).map(function(t) {
        return '<span class="tag-pill" style="font-size:11px;">' + window.escHtml(t) + '</span>';
      }).join(' ');
      var sourceClass = doc.source_type === 'rss' ? 'rss' : doc.source_type === 'api' ? 'api' : 'manual';
      var date = doc.created_at ? new Date(doc.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : '';
      var checked = _docSelected[doc.id] ? 'checked' : '';
      return '<tr draggable="true" class="doc-row" data-doc-id="' + doc.id + '" ' +
        'ondragstart="window.docDragStart(event)" ondragover="event.preventDefault()" ' +
        'ondrop="window.docDrop(event)" ondragend="this.classList.remove(\'dragging\')">' +
        '<td style="text-align:center;"><input type="checkbox" class="doc-select" data-id="' + doc.id + '" ' + checked + ' onchange="window.docSelectChange(this)" /></td>' +
        '<td><span class="doc-title-text" onclick="window.docEditTitle(this)" title="Click to edit">' + window.escHtml(doc.title) + '</span></td>' +
        '<td><span class="source-badge ' + sourceClass + '">' + window.escHtml(doc.source_type) + '</span></td>' +
        '<td><span class="doc-tags-display" onclick="window.docEditTags(this)" title="Click to edit tags">' + (tags || '<span style="color:var(--muted);font-size:11px;">\u2014</span>') + '</span></td>' +
        '<td class="mono" style="font-size:11px;">' + date + '</td>' +
        '<td><button class="btn btn-sm btn-secondary" onclick="event.stopPropagation();window.openDocDetailFromId(\'' + doc.id + '\')" title="View details" style="font-size:12px;padding:2px 6px;">\u00b7\u00b7\u00b7</button></td>' +
        '</tr>';
    }).join('');
    updateDocPagination();
    updateDocBulkToolbar();
    updateDocSortIndicators();
  }

  function updateDocPagination() {
    var info = document.getElementById('doc-page-info');
    var prevBtn = document.getElementById('doc-prev-btn');
    var nextBtn = document.getElementById('doc-next-btn');
    if (info) info.textContent = 'Page ' + (_docPage + 1);
    if (prevBtn) prevBtn.disabled = _docPage === 0;
    if (nextBtn) nextBtn.disabled = !_docHasMore;
  }

  function updateDocBulkToolbar() {
    var count = 0;
    for (var k in _docSelected) { if (_docSelected.hasOwnProperty(k)) count++; }
    var toolbar = document.getElementById('doc-bulk-toolbar');
    var countEl = document.getElementById('doc-bulk-count');
    if (!toolbar) return;
    if (count > 0) {
      toolbar.style.display = 'flex';
      if (countEl) countEl.textContent = count + ' selected';
    } else {
      toolbar.style.display = 'none';
    }
  }

  function updateDocSortIndicators() {
    document.querySelectorAll('#doc-table .sortable .sort-indicator').forEach(function(el) {
      var th = el.parentElement;
      var field = th ? th.dataset.sort : null;
      if (field === _docSortField) {
        el.textContent = _docSortDir === 1 ? ' \u25b2' : ' \u25bc';
      } else {
        el.textContent = '';
      }
    });
  }

  window.docSort = function(field) {
    if (_docSortField === field) { _docSortDir *= -1; }
    else { _docSortField = field; _docSortDir = 1; }
    renderDocumentTable();
  };

  window.docPage = function(dir) {
    var newPage = _docPage + dir;
    if (newPage < 0) return;
    _docPage = newPage;
    window.loadDocuments();
  };

  window.docFilterInput = function() {
    clearTimeout(_docFilterTimeout);
    _docFilterTimeout = setTimeout(function() {
      window._docFilter = document.getElementById('doc-filter-input').value.trim();
      _docPage = 0;
      window.loadDocuments();
    }, 300);
  };

  window.docToggleSelectAll = function() {
    var cb = document.getElementById('doc-select-all');
    var checked = !!cb.checked;
    _docSelected = {};
    if (checked) {
      document.querySelectorAll('#doc-tbody .doc-row').forEach(function(row) {
        var id = row.dataset.docId;
        if (id) _docSelected[id] = true;
      });
    }
    document.querySelectorAll('#doc-tbody .doc-select').forEach(function(cb2) { cb2.checked = checked; });
    updateDocBulkToolbar();
  };

  window.docSelectChange = function(cb) {
    var id = cb.dataset.id;
    if (cb.checked) { _docSelected[id] = true; }
    else { delete _docSelected[id]; }
    var totalCbs = document.querySelectorAll('#doc-tbody .doc-select').length;
    var checkedCbs = document.querySelectorAll('#doc-tbody .doc-select:checked').length;
    document.getElementById('doc-select-all').checked = totalCbs > 0 && totalCbs === checkedCbs;
    updateDocBulkToolbar();
  };

  window.docBulkClear = function() {
    _docSelected = {};
    document.querySelectorAll('#doc-tbody .doc-select').forEach(function(cb) { cb.checked = false; });
    document.getElementById('doc-select-all').checked = false;
    updateDocBulkToolbar();
  };

  window.docBulkDelete = function() {
    var ids = [];
    for (var k in _docSelected) { if (_docSelected.hasOwnProperty(k)) ids.push(k); }
    if (ids.length === 0) return;
    if (!confirm('Delete ' + ids.length + ' document(s)? This cannot be undone.')) return;
    var key = window.getApiKey ? window.getApiKey() : localStorage.getItem('lamadb_api_key');
    var headers = { 'Authorization': 'Bearer ' + key };
    Promise.all(ids.map(function(id) {
      return fetch('/api/documents/' + id, { method: 'DELETE', headers: headers });
    })).then(function(responses) {
      var hasError = responses.some(function(r) { return !r.ok; });
      if (hasError) { window.showError('Some documents could not be deleted.'); }
      _docSelected = {};
      window.loadDocuments();
    }).catch(function(e) {
      window.showError('Bulk delete failed: ' + e.message);
    });
  };

  window.docBulkChangeSourceType = function() {
    var ids = Object.keys(_docSelected).filter(function(id) { return _docSelected[id]; });
    if (ids.length === 0) return alert('No documents selected.');
    if (!confirm('Change source_type for ' + ids.length + ' document(s)?\nThis will update the source_type field for all selected documents.')) return;
    var newType = prompt('Enter new source_type:');
    if (!newType || !newType.trim()) return;
    newType = newType.trim();
    var promises = ids.map(function(id) {
      return window.api('/api/documents/' + id, {
        method: 'PUT',
        body: JSON.stringify({ source_type: newType })
      });
    });
    Promise.all(promises).then(function() {
      window.loadDocuments();
      window.showToast('Source type changed for ' + ids.length + ' document(s)', 'success');
    }).catch(function(e) {
      window.showError('Bulk source_type update failed: ' + e.message);
    });
  };

  window.docBulkTag = function() {
    var ids = [];
    for (var k in _docSelected) { if (_docSelected.hasOwnProperty(k)) ids.push(k); }
    if (ids.length === 0) return;
    var tag = prompt('Enter tag to add to ' + ids.length + ' selected document(s):');
    if (!tag || !tag.trim()) return;
    var tagVal = tag.trim();
    Promise.all(ids.map(function(id) {
      return window.api('/api/documents/' + id).then(function(doc) {
        var currentTags = doc.tags || [];
        if (currentTags.indexOf(tagVal) === -1) {
          currentTags = currentTags.slice();
          currentTags.push(tagVal);
        }
        return window.api('/api/documents/' + id, {
          method: 'PUT',
          body: JSON.stringify({ tags: currentTags })
        });
      });
    })).then(function() { window.loadDocuments(); }).catch(function(e) { window.showError('Bulk tag failed: ' + e.message); });
  };

  window.docEditTitle = function(span) {
    var current = span.textContent;
    var input = document.createElement('input');
    input.type = 'text';
    input.value = current;
    input.className = 'doc-inline-input';
    input.style.width = Math.max(current.length * 8 + 20, 80) + 'px';
    span.parentElement.replaceChild(input, span);
    input.focus();
    input.select();
    function save() {
      var val = input.value.trim();
      var row = input.closest('.doc-row');
      var id = row ? row.dataset.docId : null;
      if (val && val !== current && id) {
        var indicator = document.createElement('span');
        indicator.className = 'save-indicator';
        indicator.textContent = 'saving\u2026';
        input.parentElement.appendChild(indicator);
        window.api('/api/documents/' + id, { method: 'PUT', body: JSON.stringify({ title: val }) }).then(function() {
          indicator.textContent = '\u2713';
          setTimeout(function() { indicator.remove(); }, 1500);
        }).catch(function(e) {
          indicator.textContent = '\u2717';
          setTimeout(function() { indicator.remove(); }, 2000);
        });
      }
      var newSpan = document.createElement('span');
      newSpan.className = 'doc-title-text';
      newSpan.onclick = function() { window.docEditTitle(this); };
      newSpan.title = 'Click to edit';
      newSpan.textContent = val || current;
      input.parentElement.replaceChild(newSpan, input);
    }
    input.addEventListener('blur', save);
    input.addEventListener('keydown', function(e) {
      if (e.key === 'Enter') { input.blur(); e.preventDefault(); }
      if (e.key === 'Escape') { input.value = current; input.blur(); e.preventDefault(); }
    });
  };

  window.docEditTags = function(span) {
    var currentTags = [];
    var pills = span.querySelectorAll('.tag-pill');
    pills.forEach(function(p) { currentTags.push(p.textContent); });
    var current = currentTags.join(', ');
    var input = document.createElement('input');
    input.type = 'text';
    input.value = current;
    input.className = 'doc-inline-input';
    input.style.width = Math.max(current.length * 8 + 20, 120) + 'px';
    input.placeholder = 'comma-separated tags';
    span.parentElement.replaceChild(input, span);
    input.focus();
    input.select();
    function save() {
      var val = input.value.trim();
      var newTags = val ? val.split(',').map(function(t) { return t.trim(); }).filter(Boolean) : [];
      var changed = newTags.join(',') !== currentTags.join(',');
      var row = input.closest('.doc-row');
      var id = row ? row.dataset.docId : null;
      if (changed && id) {
        var indicator = document.createElement('span');
        indicator.className = 'save-indicator';
        indicator.textContent = 'saving\u2026';
        input.parentElement.appendChild(indicator);
        window.api('/api/documents/' + id, { method: 'PUT', body: JSON.stringify({ tags: newTags }) }).then(function() {
          indicator.textContent = '\u2713';
          setTimeout(function() { indicator.remove(); }, 1500);
          var newSpan = document.createElement('span');
          newSpan.className = 'doc-tags-display';
          newSpan.onclick = function() { window.docEditTags(this); };
          newSpan.title = 'Click to edit tags';
          newSpan.innerHTML = newTags.map(function(t) { return '<span class="tag-pill" style="font-size:11px;">' + window.escHtml(t) + '</span>'; }).join(' ') || '<span style="color:var(--muted);font-size:11px;">\u2014</span>';
          input.parentElement.replaceChild(newSpan, input);
        }).catch(function(e) {
          indicator.textContent = '\u2717';
          setTimeout(function() { indicator.remove(); }, 2000);
        });
        return;
      }
      var newSpan = document.createElement('span');
      newSpan.className = 'doc-tags-display';
      newSpan.onclick = function() { window.docEditTags(this); };
      newSpan.title = 'Click to edit tags';
      newSpan.innerHTML = newTags.map(function(t) { return '<span class="tag-pill" style="font-size:11px;">' + window.escHtml(t) + '</span>'; }).join(' ') || '<span style="color:var(--muted);font-size:11px;">\u2014</span>';
      input.parentElement.replaceChild(newSpan, input);
    }
    input.addEventListener('blur', save);
    input.addEventListener('keydown', function(e) {
      if (e.key === 'Enter') { input.blur(); e.preventDefault(); }
      if (e.key === 'Escape') { input.value = current; input.blur(); e.preventDefault(); }
    });
  };

  window.docEditContent = function(docId) {
    var contentEl = document.getElementById('doc-detail-content');
    if (!contentEl) return;
    var current = contentEl.textContent;
    var textarea = document.createElement('textarea');
    textarea.value = current || '';
    textarea.className = 'doc-content-editor';
    textarea.style.width = '100%';
    textarea.style.minHeight = '150px';
    textarea.style.padding = '8px';
    textarea.style.fontSize = '0.85rem';
    textarea.style.background = 'var(--surface)';
    textarea.style.color = 'var(--fg)';
    textarea.style.border = '1px solid var(--border)';
    textarea.style.borderRadius = '4px';
    textarea.style.resize = 'vertical';
    contentEl.parentElement.replaceChild(textarea, contentEl);
    textarea.focus();

    var editBtn = document.getElementById('doc-detail-edit-btn');
    if (editBtn) editBtn.style.display = 'none';

    var saveBtn = document.createElement('button');
    saveBtn.textContent = 'Save';
    saveBtn.className = 'btn btn-primary btn-sm';
    saveBtn.style.marginLeft = '8px';
    saveBtn.onclick = function() {
      var val = textarea.value;
      var indicator = document.createElement('span');
      indicator.textContent = 'saving\u2026';
      indicator.style.marginLeft = '8px';
      textarea.parentElement.appendChild(indicator);
      window.api('/api/documents/' + docId, { method: 'PUT', body: JSON.stringify({ content: val }) }).then(function() {
        indicator.textContent = '\u2713';
        var newContent = document.createElement('div');
        newContent.id = 'doc-detail-content';
        newContent.textContent = val;
        textarea.parentElement.replaceChild(newContent, textarea);
        if (editBtn) editBtn.style.display = '';
        indicator.remove();
        saveBtn.remove();
        cancelBtn && cancelBtn.remove();
      }).catch(function(e) {
        indicator.textContent = '\u2717 ' + e.message;
      });
    };
    var cancelBtn = document.createElement('button');
    cancelBtn.textContent = 'Cancel';
    cancelBtn.className = 'btn btn-sm';
    cancelBtn.style.marginLeft = '4px';
    cancelBtn.onclick = function() {
      var newContent = document.createElement('div');
      newContent.id = 'doc-detail-content';
      newContent.textContent = current;
      textarea.parentElement.replaceChild(newContent, textarea);
      if (editBtn) editBtn.style.display = '';
      saveBtn.remove();
      cancelBtn.remove();
    };
    textarea.parentElement.appendChild(saveBtn);
    textarea.parentElement.appendChild(cancelBtn);
  };

  window.docDragStart = function(e) {
    var row = e.target.closest('.doc-row');
    if (!row) return;
    row.classList.add('dragging');
    e.dataTransfer.setData('text/plain', row.dataset.docId);
    e.dataTransfer.effectAllowed = 'move';
  };

  window.docDrop = function(e) {
    e.preventDefault();
    var targetRow = e.target.closest('.doc-row');
    if (!targetRow) return;
    targetRow.classList.remove('over');
    var sourceId = e.dataTransfer.getData('text/plain');
    var targetId = targetRow.dataset.docId;
    if (!sourceId || !targetId || sourceId === targetId) return;
    document.getElementById('link-source-id').value = sourceId;
    document.getElementById('link-target-id').value = targetId;
    document.getElementById('link-source-label').textContent = 'Source: ' + sourceId.substring(0, 8) + '\u2026';
    document.getElementById('link-target-label').textContent = 'Target: ' + targetId.substring(0, 8) + '\u2026';
    document.getElementById('modal-doc-link').classList.add('open');
  };

  document.addEventListener('dragover', function(e) {
    if (e.target.closest('.doc-row')) {
      document.querySelectorAll('.doc-row.over').forEach(function(r) { r.classList.remove('over'); });
      e.target.closest('.doc-row').classList.add('over');
    }
  });
  document.addEventListener('dragend', function() {
    document.querySelectorAll('.doc-row.dragging, .doc-row.over').forEach(function(r) { r.classList.remove('dragging', 'over'); });
  });

  window.createDocLink = function() {
    var sourceId = document.getElementById('link-source-id').value;
    var targetId = document.getElementById('link-target-id').value;
    var linkType = document.getElementById('link-type-select').value;
    var context = document.getElementById('link-context').value.trim();
    if (!sourceId || !targetId) return;
    window.api('/api/documents/' + sourceId + '/links', {
      method: 'POST',
      body: JSON.stringify({ target_id: targetId, link_type: linkType, context: context || null })
    }).then(function() {
      window.closeModal('modal-doc-link');
      document.getElementById('link-context').value = '';
    }).catch(function(e) { alert('Failed to create link: ' + e.message); });
  };

  window.openDocDetailFromId = function(docId) {
    var fakeCard = { dataset: { docId: docId } };
    window.openDocDetail(fakeCard);
  };

  window.createDoc = function() {
    var title = document.getElementById('doc-title-input').value.trim();
    if (!title) { alert('Please enter a document title.'); return; }
    var sourceType = document.getElementById('doc-source-type').value;
    var content = document.getElementById('doc-content').value;
    var tags = window.getTagValues('doc-tags');
    window.api('/api/documents', {
      method: 'POST',
      body: JSON.stringify({ title: title, source_type: sourceType, content: content, tags: tags })
    }).then(function() {
      window.closeModal('modal-doc');
      window.loadDocuments();
      document.getElementById('doc-title-input').value = '';
      document.getElementById('doc-content').value = '';
      document.getElementById('doc-tags').querySelectorAll('.tag-pill').forEach(function(t) { t.remove(); });
    }).catch(function(e) { alert('Failed to create document: ' + e.message); });
  };

  window.openDocDetail = async function(card) {
    var docId = card.dataset.docId;
    if (!docId) {
      document.getElementById('doc-detail-title').textContent = 'Error';
      document.getElementById('doc-detail-content').textContent = 'No document ID found on card.';
      document.getElementById('doc-detail-date').textContent = '';
      document.getElementById('doc-detail-meta').innerHTML = '';
      document.getElementById('doc-detail-json').textContent = '';
      document.getElementById('doc-graph').innerHTML = '<span>No document ID</span>';
      document.getElementById('modal-doc-detail').classList.add('open');
      return;
    }
    document.getElementById('doc-detail-title').textContent = 'Loading...';
    document.getElementById('doc-detail-content').textContent = '';
    document.getElementById('doc-detail-date').textContent = '';
    document.getElementById('doc-detail-meta').innerHTML = '';
    document.getElementById('doc-detail-json').textContent = '';
    document.getElementById('doc-graph').innerHTML = '<span class="loading-text">Loading...</span>';
    document.getElementById('modal-doc-detail').classList.add('open');
    try {
      var [doc, linksData] = await Promise.all([
        window.api('/api/documents/' + docId),
        window.api('/api/documents/' + docId + '/links')
      ]);
      document.getElementById('doc-detail-title').textContent = doc.title || 'Untitled';
      document.getElementById('doc-detail-content').textContent = doc.content || '';
      window._openDocId = doc.id;
      var ts = doc.created_at ? new Date(doc.created_at).toLocaleString('en-US', { month: 'short', day: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }) : '';
      var updated = doc.updated_at ? new Date(doc.updated_at).toLocaleString() : '';
      document.getElementById('doc-detail-date').innerHTML = 'Created: ' + ts + (updated ? ' &middot; Updated: ' + updated : '');
      var meta = document.getElementById('doc-detail-meta');
      if (meta) {
        var tags = (doc.tags || []).map(function(t) { return '<span class="tag-pill">' + window.escHtml(t) + '</span>'; }).join(' ');
        meta.innerHTML = '<span class="source-badge">' + window.escHtml(doc.source_type) + '</span> ' + tags;
      }
      document.getElementById('doc-detail-json').textContent = JSON.stringify(doc.metadata || {}, null, 2);
      var links = linksData || [];
      var graphEl = document.getElementById('doc-graph');
      if (links.length === 0) {
        graphEl.innerHTML = '<div style="color:var(--muted);font-size:12px;">No linked documents</div>';
      } else {
        var linkHtml = links.map(function(l) {
          if (l.target_id === docId) {
            return '<span class="tag-pill" style="cursor:pointer;" onclick="window.openDocDetailFromId(\'' + window.escAttr(l.source_id) + '\')" title="Click to view">\u2190 ' + window.escHtml(l.link_type || 'related') + ': ' + window.escHtml(l.source_title || l.source_id || '') + '</span>';
          } else {
            return '<span class="tag-pill" style="cursor:pointer;" onclick="window.openDocDetailFromId(\'' + window.escAttr(l.target_id) + '\')" title="Click to view">\u2192 ' + window.escHtml(l.link_type || 'related') + ': ' + window.escHtml(l.target_title || l.target_id || '') + '</span>';
          }
        }).join(' ');
        graphEl.innerHTML = linkHtml;
      }
    } catch (e) {
      document.getElementById('doc-detail-title').textContent = 'Error';
      document.getElementById('doc-detail-content').textContent = 'Could not load document: ' + (e.message || 'Not found');
      document.getElementById('doc-detail-date').textContent = '';
      document.getElementById('doc-detail-meta').innerHTML = '';
      document.getElementById('doc-detail-json').textContent = '';
      document.getElementById('doc-graph').innerHTML = '<span style="color:var(--danger);">Failed to load</span>';
    }
  };
})();
