(function () {
  var sidebar = document.getElementById('core-sidebar');
  var pinBtn = document.getElementById('core-pin-btn');
  var pinLabel = document.getElementById('core-pin-label');
  if (!sidebar || !pinBtn) return;

  var pinned = false;
  var hoverTimer = null;

  function actualizar() {
    sidebar.classList.toggle('expanded', pinned || sidebar.dataset.hovering === '1');
    pinBtn.title = pinned ? 'Contraer menú' : 'Fijar menú abierto';
    pinLabel.textContent = pinned ? 'Contraer' : 'Fijar menú';
  }

  sidebar.addEventListener('mouseenter', function () {
    clearTimeout(hoverTimer);
    hoverTimer = setTimeout(function () {
      sidebar.dataset.hovering = '1';
      actualizar();
    }, 140);
  });

  sidebar.addEventListener('mouseleave', function () {
    clearTimeout(hoverTimer);
    sidebar.dataset.hovering = '0';
    actualizar();
  });

  pinBtn.addEventListener('click', function () {
    pinned = !pinned;
    actualizar();
  });

  actualizar();
})();
