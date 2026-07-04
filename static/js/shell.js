document.addEventListener('alpine:init', function() {
  Alpine.data('shell', function() {
    return {
      currentPage: 'home',
      sidebarOpen: true,
      sheetOpen: false,
      morePages: [
        { id: 'overview', label: 'Overview (legacy)', section: 'Legacy' },
        { id: 'documents', label: 'Documents', section: 'Core' },
        { id: 'events', label: 'Events', section: 'Core' },
        { id: 'search', label: 'Search', section: 'Core' },
        { id: 'uptime', label: 'Uptime', section: 'Monitoring' },
        { id: 'dozzle', label: 'Dozzle', section: 'Monitoring' },
        { id: 'hermes', label: 'Hermes', section: 'Monitoring' },
        { id: 'agentboard', label: 'Agent Board', section: 'Monitoring' },
        { id: 'kanban', label: 'Kanban', section: 'Monitoring' },
        { id: 'feeds', label: 'Feeds', section: 'Data Sources' },
        { id: 'freshrss', label: 'FreshRSS', section: 'Data Sources' },
        { id: 'ntfy', label: 'Ntfy', section: 'Data Sources' },
        { id: 'notflix', label: 'Notflix', section: 'Data Sources' },
        { id: 'audiobookshelf', label: 'Audiobooks', section: 'Data Sources' },
        { id: 'wiki', label: 'Wiki', section: 'Data Sources' },
        { id: 'homeassistant', label: 'Home Assistant', section: 'Data Sources' },
        { id: 'settings', label: 'Settings', section: 'Admin' },
        { id: 'secrets', label: 'Secrets', section: 'Security' },
        { id: 'access-requests', label: 'Access Requests', section: 'Security' },
        { id: 'groups', label: 'Groups', section: 'Security' }
      ],

      init() {
        var hash = window.location.hash.replace('#', '');
        if (hash && this.pageExists(hash)) this.currentPage = hash;
        this.$watch('currentPage', function(page) {
          window.navigateTo(page);
        });
        var self = this;
        window.addEventListener('popstate', function(e) {
          var page = e.state && e.state.page ? e.state.page : (window.location.hash.replace('#', '') || 'home');
          if (self.pageExists(page) && page !== self.currentPage) {
            self.currentPage = page;
          }
        });
      },

      pageExists(page) {
        return page === 'home' || page === 'notifications' || this.morePages.some(function(p) { return p.id === page; });
      },

      go(page) {
        this.currentPage = page;
        this.sheetOpen = false;
      },

      toggleTheme() {
        if (window.toggleTheme) window.toggleTheme();
      },

      openPalette() {
        if (window.openPalette) window.openPalette();
      }
    };
  });
});
