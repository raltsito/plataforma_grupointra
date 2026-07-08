(function () {
  // Debe coincidir en orden con apps/core/configuracion/modulos.py::MODULOS
  // y con apps/core/templatetags/core_extras.py (mismos íconos).
  var MODULOS = [
    { key: 'agenda', nombre: 'Agenda Intra', desc: 'Gestión de citas y disponibilidad.', accent: '#2D5F8B', tint: '#E9F0F7' },
    { key: 'finanzas', nombre: 'Sistema de Finanzas', desc: 'Pagos, cobros y reportes financieros.', accent: '#C9A24B', tint: '#F6EFDD' },
    { key: 'orbitaedu', nombre: 'OrbitaEdu', desc: 'Plataforma educativa institucional.', accent: '#2A9D9D', tint: '#E2F1F1' },
    { key: 'orbitacontrol', nombre: 'OrbitaControl', desc: 'Administración y gestión escolar.', accent: '#1B2C4F', tint: '#E8EBF2' },
    { key: 'rh', nombre: 'Recursos Humanos', desc: 'Expedientes, incidencias y nómina.', accent: '#2D5F8B', tint: '#E9F0F7' },
    { key: 'capacitacion', nombre: 'Capacitación y Cumplimiento', desc: 'Seguimiento NOM-035 y cursos obligatorios.', accent: '#C9A24B', tint: '#F6EFDD' },
    { key: 'soporte', nombre: 'Mesa de Ayuda', desc: 'Soporte técnico y reporte de incidencias.', accent: '#2A9D9D', tint: '#E2F1F1' },
    { key: 'comunicados', nombre: 'Comunicados Internos', desc: 'Avisos, circulares y documentos.', accent: '#1B2C4F', tint: '#E8EBF2' }
  ];

  var ICONOS = {
    agenda: '<rect x="3" y="4.5" width="18" height="16" rx="2"></rect><line x1="3" y1="9" x2="21" y2="9"></line><line x1="8" y1="2.5" x2="8" y2="6"></line><line x1="16" y1="2.5" x2="16" y2="6"></line><circle cx="8" cy="13.5" r="1.1" fill="{color}" stroke="none"></circle><circle cx="12" cy="13.5" r="1.1" fill="{color}" stroke="none"></circle>',
    finanzas: '<line x1="4" y1="20" x2="20" y2="20"></line><rect x="5" y="12" width="3.2" height="6" rx=".6"></rect><rect x="10.4" y="8" width="3.2" height="10" rx=".6"></rect><rect x="15.8" y="5" width="3.2" height="13" rx=".6"></rect>',
    orbitaedu: '<path d="M2.5 8.5 12 4l9.5 4.5L12 13 2.5 8.5Z"></path><path d="M6 10.5V15c0 1.4 2.7 2.8 6 2.8s6-1.4 6-2.8v-4.5"></path><line x1="21.5" y1="8.5" x2="21.5" y2="13"></line>',
    orbitacontrol: '<line x1="4" y1="7" x2="20" y2="7"></line><line x1="4" y1="12" x2="20" y2="12"></line><line x1="4" y1="17" x2="20" y2="17"></line><circle cx="9" cy="7" r="2" fill="#fff"></circle><circle cx="15" cy="12" r="2" fill="#fff"></circle><circle cx="8" cy="17" r="2" fill="#fff"></circle>',
    rh: '<circle cx="9" cy="8" r="3"></circle><path d="M3.5 19a5.5 5.5 0 0 1 11 0"></path><circle cx="17" cy="9" r="2.3"></circle><path d="M16 14.6a4.6 4.6 0 0 1 4.5 4.4"></path>',
    capacitacion: '<path d="M12 3 5 6v5.5c0 4.3 3 7.4 7 9 4-1.6 7-4.7 7-9V6l-7-3Z"></path><path d="M9 12l2 2 4-4"></path>',
    soporte: '<circle cx="12" cy="12" r="8.5"></circle><circle cx="12" cy="12" r="3.4"></circle><line x1="14.4" y1="9.6" x2="18" y2="6"></line><line x1="9.6" y1="14.4" x2="6" y2="18"></line><line x1="14.4" y1="14.4" x2="18" y2="18"></line><line x1="9.6" y1="9.6" x2="6" y2="6"></line>',
    comunicados: '<path d="M4 10v4a1 1 0 0 0 1 1h2l9 4V5L7 9H5a1 1 0 0 0-1 1Z"></path><path d="M19 9a3 3 0 0 1 0 6"></path><line x1="8" y1="15" x2="9" y2="20"></line>'
  };

  function svgIcono(key, color, size) {
    size = size || 22;
    var contenido = (ICONOS[key] || '<circle cx="12" cy="12" r="8"></circle>').replace(/\{color\}/g, color);
    return '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="' + color +
      '" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">' + contenido + '</svg>';
  }

  var form = document.getElementById('login-form');
  if (!form || typeof window.fetch !== 'function') return; // sin JS/fetch: el <form> normal ya funciona solo.

  var submitBtn = document.getElementById('login-submit');
  var spinner = document.getElementById('login-spinner');
  var submitLabel = document.getElementById('login-submit-label');
  var errorEl = document.getElementById('login-error-js');
  var loginStage = document.getElementById('login-stage');
  var loginCard = document.getElementById('login-card');
  var scene = document.getElementById('login-scene');
  var sceneGrid = document.getElementById('login-scene-grid');
  var ghostNav = document.getElementById('ghost-nav');
  var sceneUserName = document.getElementById('scene-user-name');
  var sceneUserAvatar = document.getElementById('scene-user-avatar');
  var destinoFallback = form.dataset.redirect || '/dashboard/';

  var ghostRefs = MODULOS.map(function (m) {
    var item = document.createElement('span');
    item.className = 'core-nav-item';
    item.innerHTML = '<span class="core-nav-icon">' + svgIcono(m.key, '#9DB0D0', 18) + '</span><span class="core-nav-label">' + m.nombre + '</span>';
    ghostNav.appendChild(item);
    return item;
  });

  var loading = false;

  form.addEventListener('submit', function (ev) {
    if (loading) { ev.preventDefault(); return; }
    ev.preventDefault();
    loading = true;
    submitBtn.disabled = true;
    spinner.hidden = false;
    submitLabel.textContent = 'Ingresando…';
    errorEl.hidden = true;

    var usuario = form.querySelector('[name=username]').value;
    var datos = new FormData(form);
    var inicio = Date.now();

    fetch(window.location.href, {
      method: 'POST',
      body: datos,
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      credentials: 'same-origin'
    }).then(function (resp) {
      return resp.json().then(function (data) { return { status: resp.status, data: data }; });
    }).then(function (res) {
      var espera = Math.max(0, 420 - (Date.now() - inicio));
      setTimeout(function () {
        if (res.data.ok) {
          iniciarSecuenciaExito(res.data.redirect_url || destinoFallback, usuario);
        } else {
          fallarLogin(res.data.error || 'Usuario o contraseña incorrectos.');
        }
      }, espera);
    }).catch(function () {
      // Si fetch falla por cualquier motivo, degradamos a un submit normal.
      loading = false;
      form.submit();
    });
  });

  function fallarLogin(mensaje) {
    loading = false;
    submitBtn.disabled = false;
    spinner.hidden = true;
    submitLabel.textContent = 'Iniciar sesión';
    errorEl.textContent = mensaje;
    errorEl.hidden = false;
  }

  function iniciarSecuenciaExito(destino, usuario) {
    submitLabel.textContent = 'Bienvenido';
    loginCard.classList.add('is-collapsing');

    setTimeout(function () {
      loginStage.hidden = true;
      mostrarEscena(destino, usuario);
    }, 480);
  }

  function mostrarEscena(destino, usuario) {
    sceneUserName.textContent = usuario;
    sceneUserAvatar.textContent = usuario.slice(0, 2).toUpperCase();

    sceneGrid.innerHTML = '';
    var refs = MODULOS.map(function (m, i) {
      var card = document.createElement('div');
      card.className = 'login-scene-card';
      card.style.animationDelay = (180 + i * 105) + 'ms, ' + (i * 0.45) + 's';
      card.innerHTML =
        '<div class="login-scene-card-inner">' +
        '<span class="login-scene-accent" style="background:' + m.accent + ';"></span>' +
        '<span class="login-scene-icon" style="background:' + m.tint + ';">' + svgIcono(m.key, m.accent, 24) + '</span>' +
        '<div class="login-scene-name">' + m.nombre + '</div>' +
        '<div class="login-scene-desc">' + m.desc + '</div>' +
        '</div>';
      sceneGrid.appendChild(card);
      return card;
    });
    scene.hidden = false;

    setTimeout(function () { converger(refs, destino); }, 2100);
  }

  function converger(refs, destino) {
    var flips = refs.map(function (card, i) {
      var g = card.getBoundingClientRect();
      var r = ghostRefs[i].getBoundingClientRect();
      var cx = g.left + g.width / 2, cy = g.top + 40;
      var tx = (r.left + 24) - cx;
      var ty = (r.top + r.height / 2) - cy;
      var scale = Math.max(0.14, 26 / g.width);
      return { tx: tx, ty: ty, scale: scale, dist: Math.hypot(tx, ty) };
    });
    flips.map(function (f, i) { return { i: i, d: f.dist }; })
      .sort(function (a, b) { return b.d - a.d; })
      .forEach(function (o, rank) { flips[o.i].delay = rank * 40; });

    refs.forEach(function (card, i) {
      var f = flips[i];
      card.style.transitionDelay = f.delay + 'ms';
      card.style.transform = 'translate(' + f.tx + 'px,' + f.ty + 'px) scale(' + f.scale + ')';
      card.classList.add('is-flying');
    });

    setTimeout(function () { window.location.href = destino; }, 760);
  }
})();
