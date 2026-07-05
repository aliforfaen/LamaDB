// Page: Briefing — Feed reader with morning brief
(function() {
  'use strict';

  var _autoRefreshTimer = null;
  var FEED_CONFIGS = [
    { slug: 'lamalab', label: 'LamaLab', color: 'var(--accent)' },
    { slug: 'media', label: 'Media', color: 'var(--accent-cyan)' },
    { slug: 'life', label: 'Life', color: 'var(--info)' },
    { slug: 'briefing', label: 'Briefing', color: 'var(--warn)' }
  ];

  window.loadBriefing = async function() {
    try {
      var results = await Promise.all(
        FEED_CONFIGS.map(function(f) {
          return window.api('/api/documents?tag=' + f.slug + '&source_type=agent_feed&limit=30');
        })
      );
      renderBriefing(results);
      var statusEl = document.getElementById('briefing-status');
      if (statusEl) statusEl.textContent = 'Updated ' + new Date().toLocaleTimeString();
    } catch (e) {
      window.showError('Failed to load feeds: ' + e.message);
    }
  };

  function renderBriefing(feedResults) {
    var morningBrief = null;
    var feedEntries = [];

    feedResults.forEach(function(data, idx) {
      var items = data.items || data || [];
      if (!Array.isArray(items)) items = [];
      var config = FEED_CONFIGS[idx];

      items.forEach(function(doc) {
        var tags = doc.tags || [];
        // Detect morning brief
        if (config.slug === 'briefing' && tags.indexOf('digest') !== -1 && tags.indexOf('morning') !== -1) {
          if (!morningBrief || new Date(doc.created_at) > new Date(morningBrief.created_at)) {
            morningBrief = doc;
          }
        }
        feedEntries.push({
          id: doc.id,
          title: doc.title || 'Untitled',
          content: doc.content || '',
          source: config.label,
          sourceColor: config.color,
          date: doc.created_at,
          metadata: doc.metadata || {}
        });
      });
    });

    // Sort by date descending
    feedEntries.sort(function(a, b) {
      return new Date(b.date) - new Date(a.date);
    });

    var container = document.getElementById('briefing-content');
    if (!container) return;

    var html = '';

    // Morning brief card
    if (morningBrief) {
      var briefContent = morningBrief.content || '';
      var sections = parseBriefSections(briefContent);

      html += '<div class="brief-card" onclick="window.openBriefDetail(\'' + morningBrief.id + '\')">';
      html += '<div class="brief-card-header">';
      html += '<span class="brief-card-icon">&#x2600;</span>';
      html += '<span class="brief-card-label">Morning Brief</span>';
      html += '<span class="brief-card-date">' + window.relativeTime(morningBrief.created_at) + '</span>';
      html += '</div>';
      html += '<div class="brief-card-title">' + window.escHtml(morningBrief.title || 'Morning Brief') + '</div>';
      html += '<div class="brief-card-preview">';
      sections.forEach(function(s, i) {
        if (i < 4) {
          html += '<div class="brief-section-preview">';
          html += '<span class="brief-section-heading">' + window.escHtml(s.heading) + '</span>';
          html += '<span class="brief-section-count">' + s.items.length + ' item' + (s.items.length !== 1 ? 's' : '') + '</span>';
          html += '</div>';
        }
      });
      html += '</div>';
      html += '</div>';
    } else {
      html += '<div class="brief-card brief-card-empty">';
      html += '<div class="brief-card-header">';
      html += '<span class="brief-card-icon">&#x1F31E;</span>';
      html += '<span class="brief-card-label">No Morning Brief Yet</span>';
      html += '</div>';
      html += '<div class="brief-card-body">Run <code>modules/feeds/briefing.py</code> to generate one.</div>';
      html += '</div>';
    }

    // Filter bar with refresh
    html += '<div class="briefing-filter-bar">';
    html += '<span class="briefing-entry-count">' + feedEntries.length + ' entries</span>';
    html += '<span style="flex:1;"></span>';
    html += '<button class="btn btn-sm btn-secondary" onclick="window.loadBriefing()">&#x21BB; Refresh</button>';
    html += '</div>';

    // Feed entries grouped by source
    FEED_CONFIGS.forEach(function(config) {
      var entries = feedEntries.filter(function(e) { return e.source === config.label; });
      if (entries.length === 0) return;

      html += '<div class="feed-group">';
      html += '<div class="feed-group-header">';
      html += '<span class="feed-source-tag" style="--source-color:' + config.color + '">' + window.escHtml(config.label) + '</span>';
      html += '<span class="feed-group-count">' + entries.length + '</span>';
      html += '</div>';

      entries.forEach(function(entry) {
        html += '<div class="feed-entry" onclick="window.openBriefDetail(\'' + entry.id + '\')">';
        html += '<div class="feed-entry-title">' + window.escHtml(entry.title) + '</div>';
        html += '<div class="feed-entry-meta">';
        html += '<span class="feed-entry-date">' + window.relativeTime(entry.date) + '</span>';
        html += '</div>';
        html += '</div>';
      });

      html += '</div>';
    });

    container.innerHTML = html;

    // Auto-refresh every 5 minutes
    if (_autoRefreshTimer) clearTimeout(_autoRefreshTimer);
    _autoRefreshTimer = setTimeout(window.loadBriefing, 300000);
  }

  function parseBriefSections(content) {
    var sections = [];
    if (!content) return sections;

    var lines = content.split('\n');
    var currentHeading = '';
    var currentItems = [];

    lines.forEach(function(line) {
      line = line.trim();
      if (line.indexOf('## ') === 0) {
        if (currentHeading) {
          sections.push({ heading: currentHeading, items: currentItems });
          currentItems = [];
        }
        currentHeading = line.replace(/^##\s+/, '');
      } else if (line.indexOf('- ') === 0 && currentHeading) {
        currentItems.push(line.replace(/^- /, ''));
      } else if (line && currentHeading) {
        currentItems.push(line);
      }
    });

    if (currentHeading) {
      sections.push({ heading: currentHeading, items: currentItems });
    }

    return sections;
  }

  window.openBriefDetail = async function(docId) {
    try {
      var doc = await window.api('/api/documents/' + docId);
      var modal = document.getElementById('modal-brief-detail');
      if (!modal) return;

      var content = doc.content || '';
      var html = renderBriefContent(content);

      document.getElementById('brief-detail-title').textContent = doc.title || 'Untitled';
      document.getElementById('brief-detail-date').textContent = doc.created_at
        ? new Date(doc.created_at).toLocaleString()
        : '';
      document.getElementById('brief-detail-content').innerHTML = html;
      modal.classList.add('open');
    } catch (e) {
      window.showError('Failed to load detail: ' + e.message);
    }
  };

  function renderBriefContent(content) {
    if (!content) return '<p class="empty" style="color:var(--muted);">No content</p>';

    var sections = parseBriefSections(content);
    if (sections.length === 0) {
      return '<div style="white-space:pre-wrap;line-height:1.6;">' + window.escHtml(content) + '</div>';
    }

    var html = '';
    sections.forEach(function(s) {
      html += '<div class="brief-detail-section">';
      html += '<h3 class="brief-detail-heading">' + window.escHtml(s.heading) + '</h3>';
      html += '<ul class="brief-detail-list">';
      s.items.forEach(function(item) {
        html += '<li>' + window.escHtml(item) + '</li>';
      });
      html += '</ul>';
      html += '</div>';
    });

    return html;
  }

})();
