document.addEventListener('alpine:init', function() {
  Alpine.data('notificationsPage', function() {
    return {
      loading: true,
      groups: [],
      filterSeverity: '',
      filterSource: '',
      showProcessed: false,
      sources: [],

      async init() {
        await this.load();
      },

      async load() {
        this.loading = true;
        try {
          if (this.showProcessed) {
            var events = await window.api('/api/events?limit=100');
            this.groups = (events || []).map(function(e) {
              return {
                key: e.id,
                title: e.title,
                source: e.source,
                severity: e.severity,
                count: 1,
                first_seen: e.ts,
                last_seen: e.ts,
                event_ids: [e.id]
              };
            });
          } else {
            var resp = await window.api('/api/notifications/unread?aggregate=true');
            this.groups = resp.items || resp || [];
          }

          var sourceSet = {};
          this.groups.forEach(function(g) { sourceSet[g.source] = true; });
          this.sources = Object.keys(sourceSet).sort();
        } catch (e) {
          window.LlamaApp.showError('Failed to load notifications');
        } finally {
          this.loading = false;
        }
      },

      filteredGroups() {
        var self = this;
        return this.groups.filter(function(g) {
          if (self.filterSeverity && g.severity !== self.filterSeverity) return false;
          if (self.filterSource && g.source !== self.filterSource) return false;
          return true;
        }).sort(function(a, b) {
          var sevOrder = { critical: 0, error: 1, warning: 2, warn: 2, info: 3 };
          var sa = sevOrder[a.severity] || 99;
          var sb = sevOrder[b.severity] || 99;
          if (sa !== sb) return sa - sb;
          return new Date(b.last_seen) - new Date(a.last_seen);
        });
      },

      async dismissGroup(group, event) {
        if (event) event.stopPropagation();
        try {
          for (var i = 0; i < group.event_ids.length; i++) {
            await window.api('/api/events/' + group.event_ids[i], {
              method: 'PATCH',
              body: JSON.stringify({ processed: true })
            });
          }
          this.groups = this.groups.filter(function(g) { return g !== group; });
        } catch (e) {
          window.LlamaApp.showError('Failed to dismiss notification group');
        }
      },

      groupIcon(source) {
        var map = {
          'uptime_kuma': '📡',
          'dozzle': '🐳',
          'hermes': '🧠',
          'ntfy': '🔔',
          'freshrss': '📰'
        };
        return map[source] || '📎';
      },

      formatTime(ts) {
        var d = new Date(ts);
        return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
      }
    };
  });
});
