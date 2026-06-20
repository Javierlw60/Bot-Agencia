(function () {
  const drawer = document.getElementById('mobile-drawer');
  const backdrop = document.getElementById('drawer-backdrop');
  const btnOpen = document.getElementById('btn-menu');
  const btnClose = document.getElementById('btn-menu-close');

  function abrirMenu() {
    if (!drawer) return;
    drawer.classList.remove('hidden');
    drawer.classList.add('open');
    document.body.style.overflow = 'hidden';
  }

  function cerrarMenu() {
    if (!drawer) return;
    drawer.classList.remove('open');
    document.body.style.overflow = '';
    window.setTimeout(function () {
      if (!drawer.classList.contains('open')) drawer.classList.add('hidden');
    }, 220);
  }

  if (btnOpen) btnOpen.addEventListener('click', abrirMenu);
  if (btnClose) btnClose.addEventListener('click', cerrarMenu);
  if (backdrop) backdrop.addEventListener('click', cerrarMenu);

  drawer && drawer.querySelectorAll('a').forEach(function (link) {
    link.addEventListener('click', cerrarMenu);
  });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') cerrarMenu();
  });

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () {
      var scope = document.body.dataset.pwaScope;
      var swUrl = document.body.dataset.swUrl;
      if (!scope || !swUrl) return;
      navigator.serviceWorker
        .register(swUrl, { scope: scope })
        .catch(function () {});
    });
  }
})();
