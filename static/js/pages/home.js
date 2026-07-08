function safeShowError(msg) {
  if (window.LlamaApp && window.LlamaApp.showError) {
    window.LlamaApp.showError(msg);
  } else {
    console.error('[LamaDB]', msg);
  }
}

document.addEventListener('alpine:init', function() {
  Alpine.data('homePage', function() {
    return {
      loading: true,
      greeting: 'Good day',
      today: '',
      presence: null,
      brief: null,
      attentionNotes: [],
      activityItems: [],

      async init() {
        var self = this;
        console.log('[home] init start');
        this.setGreeting();
        this.today = new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' });

        // Expose refresh functions on window so SSE handlers and navigateTo can call them
        window.loadHome = function() { return self.load(); };
        window.loadHomeAttention = function() { return self.loadAttention(); };
        window.loadHomeRecentActivity = function() { return self.loadRecentActivity(); };

        if (window.LlamaApp && window.LlamaApp.getApiKey && window.LlamaApp.getApiKey()) {
          console.log('[home] api key present, loading');
          await this.load();
        } else {
          console.log('[home] no api key yet, waiting for auth event');
        }
        window.addEventListener('lamadb:authenticated', function() {
          console.log('[home] authenticated event');
          self.load();
        }, { once: true });
        console.log('[home] init done');
      },

      setGreeting() {
        var hour = new Date().getHours();
        if (hour < 12) this.greeting = 'Good morning';
        else if (hour < 18) this.greeting = 'Good afternoon';
        else this.greeting = 'Good evening';
      },

      async load() {
        console.log('[home] load start');
        this.loading = true;
        try {
          // Fetch briefing (keep existing behavior)
          try {
            var briefingDocs = await window.api('/api/documents?tag=briefing&limit=1');
            var items = briefingDocs.items || briefingDocs || [];
            if (items.length) this.brief = items[0];
          } catch (e) { this.brief = null; }

          // Load attention notes and recent activity in parallel
          await Promise.all([
            this.loadAttention(),
            this.loadRecentActivity()
          ]);
          console.log('[home] load success, attentionNotes:', this.attentionNotes.length, 'activityItems:', this.activityItems.length);
        } catch (e) {
          console.error('[home] load error', e);
          safeShowError('Failed to load home data');
        } finally {
          this.loading = false;
        }
      },

      // ─── SmartNote attention cards ──────────────────────────────────────
      async loadAttention() {
        var notes = [];

        // 1. Kanban tasks in progress
        try {
          var tasks = [];
          try {
            var taskResp = await window.api('/api/kanban/me/tasks?status=in_progress&limit=5');
            tasks = taskResp.items || taskResp || [];
          } catch (e) {
            if (e.status === 404) {
              // /me/tasks may not exist; try the general endpoint
              try {
                var altResp = await window.api('/api/kanban/tasks?status=in_progress&limit=5');
                tasks = altResp.items || altResp || [];
              } catch (e2) { /* kanban module may be disabled */ }
            }
          }
          if (tasks.length > 0) {
            var taskCount = tasks.length;
            notes.push({
              id: 'kanban-tasks',
              type: 'heads-up',
              icon: '\uD83D\uDCCB',
              title: window.escHtml(tasks[0].title) + (taskCount > 1 ? ' +' + (taskCount - 1) + ' more' : ''),
              meta: taskCount + ' task' + (taskCount > 1 ? 's' : '') + ' in progress',
              cta: 'Kanban',
              click: function() { window.navigateTo('kanban'); }
            });
          }
        } catch (e) { /* skip kanban note */ }

        // 2. Unread notifications
        try {
          var notifResp = await window.api('/api/notifications/unread?aggregate=true&limit=1');
          var groups = notifResp.items || notifResp || [];
          if (groups.length > 0) {
            var top = groups[0];
            notes.push({
              id: 'alert-notif',
              type: 'alert',
              icon: '\uD83D\uDD14',
              title: window.escHtml(top.title || 'Unread notifications'),
              meta: (top.count || 1) + ' from ' + (top.source || 'unknown'),
              cta: 'View',
              click: function() { window.navigateTo('notifications'); }
            });
          }
        } catch (e) { /* skip alert note */ }

        // 3. System warnings
        try {
          var warnResp = await window.api('/api/events?severity=warning&limit=1&processed=false');
          var warnings = warnResp.items || warnResp || [];
          if (warnings.length > 0) {
            var warn = warnings[0];
            notes.push({
              id: 'sys-warning',
              type: 'alert',
              icon: '\u26A0\uFE0F',
              title: window.escHtml(warn.title || 'System warning'),
              meta: 'From ' + (warn.source || 'unknown'),
              cta: 'View',
              click: function() { window.navigateTo('events'); }
            });
          }
        } catch (e) { /* skip warning note */ }

        this.attentionNotes = notes;
      },

      // ─── Recent activity feed ──────────────────────────────────────────
      async loadRecentActivity() {
        try {
          var eventsResp = await window.api('/api/events?limit=20&order=desc');
          var events = eventsResp.items || eventsResp || [];

          this.activityItems = events.map(function(e) {
            var icon = '\uD83D\uDCC4';
            var source = (e.source || '').toLowerCase();
            if (source.indexOf('uptime') !== -1) icon = '\uD83D\uDCE1';
            else if (source.indexOf('dozzle') !== -1) icon = '\uD83D\uDC33';
            else if (source.indexOf('hermes') !== -1) icon = '\uD83E\uDDE0';
            else if (source.indexOf('ntfy') !== -1) icon = '\uD83D\uDD14';
            else if (source.indexOf('freshrss') !== -1) icon = '\uD83D\uDCF0';
            else if (source.indexOf('kanban') !== -1) icon = '\uD83D\uDCCB';
            else if (e.severity === 'critical' || e.severity === 'error') icon = '\uD83D\uDD34';
            else if (e.severity === 'warning' || e.severity === 'warn') icon = '\u26A0\uFE0F';

            var sev = e.severity || 'info';
            return {
              id: e.id,
              title: window.escHtml(e.title),
              source: e.source || 'unknown',
              severity: sev,
              icon: icon,
              timeAgo: window.relativeTime(e.ts || e.created_at),
              showBadge: sev !== 'info',
              click: function() { window.navigateTo('events'); }
            };
          });
        } catch (e) {
          this.activityItems = [];
        }
      },

      // ─── Navigation helpers ────────────────────────────────────────────
      quickAction(name) {
        if (name === 'event') window.navigateTo('events');
        else if (name === 'scene') window.navigateTo('homeassistant');
        else if (name === 'task') window.navigateTo('kanban');
        else if (name === 'note') window.navigateTo('wiki');
      }
    };
  });
});
