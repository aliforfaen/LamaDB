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
      summary: {
        critical: 0,
        notifications: 0,
        tasks: 0
      },
      status: [],
      headlines: [],

      async init() {
        this.setGreeting();
        this.today = new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' });
        await this.load();
      },

      setGreeting() {
        var hour = new Date().getHours();
        if (hour < 12) this.greeting = 'Good morning';
        else if (hour < 18) this.greeting = 'Good afternoon';
        else this.greeting = 'Good evening';
      },

      async load() {
        this.loading = true;
        try {
          var overview = {};
          try {
            overview = await window.api('/api/dashboard/overview');
          } catch (e) {
            if (e.status !== 403) throw e;
            var header = await window.api('/api/dashboard/header');
            overview = {
              monitors: header.monitors || { up: 0, down: 0, unknown: 0 },
              events: header.events || { today: 0 },
              documents: {},
              cache: {}
            };
          }
          var notifications = await window.api('/api/notifications/unread?aggregate=true&limit=5');
          var uptime = await window.api('/api/uptime/status');

          this.summary.critical = (uptime || []).filter(function(m) { return m.status === 0; }).length;
          this.summary.notifications = (notifications.items || notifications || []).reduce(function(sum, g) { return sum + (g.count || 1); }, 0);
          this.summary.tasks = (overview.agent_tasks || {}).pending || 0;

          this.status = [
            { label: 'Services', value: this.summary.critical > 0 ? this.summary.critical + ' down' : 'All up', ok: this.summary.critical === 0 },
            { label: 'Cache', value: ((overview.cache || {}).hit_rate || '0') + '%', ok: true },
            { label: 'Documents', value: String(((overview.documents || {}).total || 0)), ok: true }
          ];

          try {
            var briefingDocs = await window.api('/api/documents?tag=briefing&limit=1');
            var items = briefingDocs.items || briefingDocs || [];
            if (items.length) this.brief = items[0];
          } catch (e) { this.brief = null; }

          this.headlines = [];
          try {
            var docResp = await window.api('/api/documents?source_type=agent_feed&limit=5');
            this.headlines = (docResp.items || docResp || []).slice(0, 5).map(function(d) {
              return { title: d.title, date: d.created_at };
            });
          } catch (e) {}
        } catch (e) {
          safeShowError('Failed to load home data');
        } finally {
          this.loading = false;
        }
      },

      navigateToNotifications() {
        window.navigateTo('notifications');
      },

      quickAction(name) {
        if (name === 'event') window.navigateTo('events');
        else if (name === 'scene') window.navigateTo('homeassistant');
        else if (name === 'task') window.navigateTo('kanban');
        else if (name === 'note') window.navigateTo('wiki');
      }
    };
  });
});
