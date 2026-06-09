// Page: Feeds
(function() {
  'use strict';

  window.loadFeeds = async function() {
    try {
      var feeds = await window.api('/api/feeds');
      renderFeedsTable(feeds);
      if (feeds.length > 0) loadFeedPreview(feeds[0].slug);
    } catch (e) {
      window.showError('Failed to load feeds: ' + e.message);
    }
  };

  function renderFeedsTable(feeds) {
    var tbody = document.querySelector('#page-feeds .feeds-table-wrap tbody');
    if (!tbody) return;
    if (!feeds || feeds.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" style="color:var(--muted);text-align:center;padding:20px;">No feeds yet. Create one above.</td></tr>';
      return;
    }
    tbody.innerHTML = feeds.map(function(f) {
      var tags = (f.filter_tags || []).map(function(t) { return '<span class="tag-pill">' + t + '</span>'; }).join(' ');
      var created = f.created_at ? new Date(f.created_at).toLocaleDateString('en-US', { year: 'numeric', month: '2-digit', day: '2-digit' }) : '';
      var truncatedDesc = f.description ? f.description.substring(0, 40) : '';
      return '<tr data-feed-slug="' + f.slug + '">' +
        '<td class="nowrap">' + f.name + '</td>' +
        '<td class="mono nowrap">' + f.slug + '</td>' +
        '<td class="truncate-cell" title="' + (f.description || '') + '">' + truncatedDesc + '</td>' +
        '<td>' + tags + '</td>' +
        '<td class="mono">' + (f.max_items || 0) + '</td>' +
        '<td class="mono nowrap">' + created + '</td>' +
        '<td class="nowrap">' +
          '<button class="btn btn-ghost btn-sm" onclick="editFeed(this)">Edit</button>' +
          '<button class="btn btn-ghost btn-sm" style="color:var(--danger);" onclick="deleteFeed(this)">Del</button>' +
        '</td>' +
      '</tr>';
    }).join('');
  }

  async function loadFeedPreview(slug) {
    try {
      var resp = await fetch('/feeds/' + slug + '.xml');
      if (resp.ok) {
        var xml = await resp.text();
        var preview = document.querySelector('#page-feeds .rss-preview');
        if (preview) {
          var panelHead = document.querySelector('#page-feeds .panel-head');
          if (panelHead) panelHead.textContent = 'RSS Preview \u2014 ' + slug;
          preview.textContent = xml.length > 2000 ? xml.substring(0, 2000) + '\n...' : xml;
        }
      }
    } catch (e) {
      var preview = document.querySelector('#page-feeds .rss-preview');
      if (preview) preview.textContent = 'Preview not available.';
    }
  }

  window.editFeed = function(btn) {
    var row = btn.closest('tr');
    var slug = row.dataset.feedSlug;
    window.api('/api/feeds/' + slug).then(function(feed) {
      document.getElementById('feed-name').value = feed.name;
      document.getElementById('feed-slug').value = feed.slug;
      document.getElementById('feed-desc').value = feed.description || '';
      document.getElementById('feed-max-items').value = feed.max_items || 500;
      var tagWrap = document.getElementById('feed-tags');
      tagWrap.querySelectorAll('.tag-pill').forEach(function(t) { t.remove(); });
      (feed.filter_tags || []).forEach(function(t) {
        var tag = document.createElement('span');
        tag.className = 'tag-pill';
        tag.innerHTML = t + ' <span class="remove" onclick="this.parentElement.remove()">\u00d7</span>';
        tagWrap.insertBefore(tag, tagWrap.querySelector('input'));
      });
      document.getElementById('modal-feed').classList.add('open');
    }).catch(function(e) { alert('Failed to load feed: ' + e.message); });
  };

  window.deleteFeed = function(btn) {
    var row = btn.closest('tr');
    var slug = row.dataset.feedSlug || row.cells[1].textContent.trim();
    if (!confirm('Delete feed "' + slug + '"? This action cannot be undone.')) return;
    window.api('/api/feeds/' + slug, { method: 'DELETE' }).then(function() { row.remove(); }).catch(function(e) { alert('Failed to delete feed: ' + e.message); });
  };

  window.createFeed = function() {
    var name = document.getElementById('feed-name').value.trim();
    if (!name) { alert('Please enter a feed name.'); return; }
    var slug = document.getElementById('feed-slug').value.trim() || name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    var desc = document.getElementById('feed-desc').value.trim();
    var maxItems = parseInt(document.getElementById('feed-max-items').value, 10) || 500;
    var tags = window.getTagValues('feed-tags');
    window.api('/api/feeds', {
      method: 'POST',
      body: JSON.stringify({ name: name, slug: slug, description: desc, filter_tags: tags, max_items: maxItems })
    }).then(function() {
      window.closeModal('modal-feed');
      document.getElementById('feed-name').value = '';
      document.getElementById('feed-slug').value = '';
      document.getElementById('feed-desc').value = '';
      document.getElementById('feed-tags').querySelectorAll('.tag-pill').forEach(function(t) { t.remove(); });
      window.loadFeeds();
    }).catch(function(e) { alert('Failed to create feed: ' + e.message); });
  };
})();
