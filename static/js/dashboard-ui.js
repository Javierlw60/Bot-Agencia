(function () {
  const TOAST_DURATION_MS = 4200;

  function ensureToastContainer() {
    let el = document.getElementById('toast-container');
    if (!el) {
      el = document.createElement('div');
      el.id = 'toast-container';
      el.setAttribute('aria-live', 'polite');
      el.setAttribute('aria-atomic', 'true');
      document.body.appendChild(el);
    }
    return el;
  }

  function showToast(message, type) {
    const container = ensureToastContainer();
    const toast = document.createElement('div');
    toast.className = 'ui-toast ui-toast-' + (type === 'error' ? 'error' : 'success');
    toast.textContent = message;
    container.appendChild(toast);
    requestAnimationFrame(function () {
      toast.classList.add('ui-toast-visible');
    });
    setTimeout(function () {
      toast.classList.remove('ui-toast-visible');
      setTimeout(function () { toast.remove(); }, 300);
    }, TOAST_DURATION_MS);
  }

  function initFriendlyValidation() {
    const mensajes = {
      nombre: 'Ingresá el nombre de la agencia.',
      marca: 'Ingresá la marca del vehículo.',
      modelo: 'Ingresá el modelo del vehículo.',
      ano: 'Ingresá el año del vehículo.',
      precio: 'Ingresá el precio en pesos.',
      patente: 'Ingresá la patente del vehículo.',
    };

    document.querySelectorAll('.ui-input[required], .ui-select[required]').forEach(function (el) {
      el.addEventListener('invalid', function () {
        const key = el.getAttribute('name');
        const custom = mensajes[key];
        if (custom) {
          el.setCustomValidity(custom);
        } else {
          const label = el.closest('label');
          const texto = label && label.querySelector('.ui-label');
          const nombre = texto ? texto.textContent.replace('*', '').trim().toLowerCase() : 'este campo';
          el.setCustomValidity('Completá ' + nombre + '.');
        }
      });
      el.addEventListener('input', function () { el.setCustomValidity(''); });
      el.addEventListener('change', function () { el.setCustomValidity(''); });
    });
  }

  function marcarGuardando(btn, texto) {
    if (!btn || btn.disabled) return false;
    btn.disabled = true;
    btn.dataset.labelOriginal = btn.textContent;
    btn.textContent = texto || 'Guardando...';
    btn.classList.add('is-saving');
    return true;
  }

  function initSaveForms() {
    document.querySelectorAll('form.js-save-form').forEach(function (form) {
      form.addEventListener('submit', function (e) {
        if (!form.checkValidity()) {
          form.reportValidity();
          e.preventDefault();
          return;
        }
        const btn = form.querySelector('[type="submit"]');
        if (btn && !marcarGuardando(btn, btn.dataset.savingText || 'Guardando...')) {
          e.preventDefault();
        }
      });
    });
  }

  function limpiarQueryParam(param) {
    const url = new URL(window.location.href);
    if (!url.searchParams.has(param)) return;
    url.searchParams.delete(param);
    ['n', 'omitidos', 'msg', 'total'].forEach(function (p) {
      if (param === 'ok') url.searchParams.delete(p);
    });
    window.history.replaceState({}, '', url.pathname + (url.search || ''));
  }

  function initToastFromQuery() {
    const params = new URLSearchParams(window.location.search);
    const ok = params.get('ok');
    if (!ok) return;

    const mensajes = {
      guardado: 'Cambios guardados correctamente.',
      creado: 'Vehículo creado. Ya podés subir fotos.',
      foto: 'Foto agregada correctamente.',
      portada: 'Portada actualizada.',
      foto_eliminada: 'Foto eliminada.',
      eliminado: 'Vehículo eliminado del inventario.',
      import: 'Importación completada: ' + (params.get('total') || '0') + ' vehículos.',
    };

    if (ok === 'fotos') {
      showToast((params.get('n') || '0') + ' foto(s) subida(s) correctamente.');
    } else if (mensajes[ok]) {
      showToast(mensajes[ok]);
    }

    limpiarQueryParam('ok');
  }

  window.DashboardUI = {
    showToast: showToast,
    marcarGuardando: marcarGuardando,
  };

  document.addEventListener('DOMContentLoaded', function () {
    initFriendlyValidation();
    initSaveForms();
    initToastFromQuery();
  });
})();
