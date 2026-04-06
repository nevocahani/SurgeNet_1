// SurgeNet Service Worker
const CACHE_NAME = 'surgenet-v1';

// Install
self.addEventListener('install', function(e) {
  self.skipWaiting();
});

// Activate
self.addEventListener('activate', function(e) {
  e.waitUntil(clients.claim());
});

// Push notification received
self.addEventListener('push', function(e) {
  var data = {};
  try {
    data = e.data.json();
  } catch(err) {
    data = { title: 'SurgeNet', body: e.data ? e.data.text() : 'בקשת חירום חדשה' };
  }

  var options = {
    body: data.body || 'בקשת חירום חדשה',
    icon: '/static/icon-192.png',
    badge: '/static/icon-192.png',
    vibrate: [200, 100, 200, 100, 200],
    tag: 'surgenet-alert',
    requireInteraction: true,
    dir: 'rtl',
    data: {
      url: data.url || '/'
    },
    actions: [
      { action: 'open', title: 'פתח' },
      { action: 'close', title: 'סגור' }
    ]
  };

  e.waitUntil(
    self.registration.showNotification(data.title || '🚨 SurgeNet - בקשת חירום', options)
  );
});

// Notification click
self.addEventListener('notificationclick', function(e) {
  e.notification.close();

  if (e.action === 'close') return;

  var url = (e.notification.data && e.notification.data.url) || '/';

  e.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function(clientList) {
      for (var i = 0; i < clientList.length; i++) {
        var client = clientList[i];
        if (client.url.includes(self.location.origin) && 'focus' in client) {
          return client.focus();
        }
      }
      if (clients.openWindow) {
        return clients.openWindow(url);
      }
    })
  );
});
