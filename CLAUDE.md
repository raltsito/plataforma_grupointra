# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Portal interno de Grupo Intra (Instituto de Atención Integral y Desarrollo Humano A.C.), construido por módulos. El proyecto se organiza en `apps/`: `apps/core` (autenticación, dashboard, permisos — el "núcleo" del portal) y un módulo de negocio por carpeta, empezando por `apps/finanzas`. Los módulos siguientes (RH, académico, clínico, etc.) se agregan de la misma forma, uno a la vez.

Stack: Django 5.2.10 (el docstring de `config/settings.py` dice 6.0.6 generado por scaffold, pero el paquete instalado es 5.2.10), Python 3.14, SQLite (`db.sqlite3`), sin frontend framework (HTML + CSS servidos vía Django templates/staticfiles).

No hay `requirements.txt` ni `pyproject.toml` en el repo — las dependencias no están fijadas en ningún archivo todavía.

## Commands

```bash
# Run dev server
python manage.py runserver

# Migrations
python manage.py makemigrations
python manage.py migrate

# Create a superuser (necesario para entrar, no hay registro público)
python manage.py createsuperuser

# Tests (framework Django estándar; no hay tests reales todavía)
python manage.py test
```

## Architecture

- **`config/`** — proyecto Django raíz (`settings.py`, `urls.py`, `asgi.py`, `wsgi.py`). `config/urls.py` incluye `apps.core.urls` en la raíz (`''`) y `apps.finanzas.urls` bajo `finanzas/`. `admin/` es la otra ruta de nivel superior.
- **`apps/`** — paquete contenedor de todas las apps del portal. Cada módulo de negocio vive en su propia carpeta (`apps/finanzas/`, y los que sigan). `apps/__init__.py` existe solo para que el paquete sea importable; no contiene lógica.
- **`apps/core/`** — una sola app Django (label `core`) que agrupa el núcleo del portal en sub-paquetes organizativos (no son apps Django separadas, no tienen su propio `INSTALLED_APPS`/migraciones):
  - `autenticacion/` — login, logout, recuperación de contraseña (usa las vistas genéricas de `django.contrib.auth.views`).
  - `permisos/grupos.py` — `crear_grupos_sistema_intra` (migración de datos que crea los grupos base) y `usuario_pertenece_a(user, *nombres_grupo)`, el helper de RBAC que reutilizan los módulos de negocio (ej. `apps/finanzas`) en vez de repetir `user.groups.filter(...)` a mano.
  - `usuarios/`, `auditoria/`, `configuracion/` — reservados para el futuro (RF-19 bitácora de auditoría, RF-20 catálogos administrables, perfil de usuario). Solo tienen un `__init__.py` con comentario, sin implementación.
  - El dashboard/launcher del portal (`dashboard_view`, `templates/core/dashboard.html`) vive en la raíz de `apps/core/`, no dentro de `usuarios/` — es el punto de entrada del portal, no un dato de perfil.
- **Roles vía `django.contrib.auth.Group`, no un modelo custom.** Los roles base (`Terapeutas`, `Recepción`, `Administración`, `Dirección`, `Sistemas`) se crean en `apps/core/migrations/0001_initial.py` vía `crear_grupos_sistema_intra` (`get_or_create`, idempotente). El grupo `Finanzas` se crea igual en `apps/finanzas/migrations/0002_grupo_finanzas.py`. Si se necesita agregar/renombrar un rol, hacerlo con una nueva migración de datos, no editando una ya aplicada.
- **Dashboard = sidebar con el catálogo de módulos del portal, no tarjetas sueltas.** `apps/core/configuracion/modulos.py` define `MODULOS` (los 8 módulos de "Centralización Intra": Agenda, Finanzas, OrbitaEdu, OrbitaControl, RH, Capacitación, Mesa de Ayuda, Comunicados) y `modulos_para(user)`, que resuelve para cada uno si está `disponible` (requiere `construido=True` **y** pertenecer a alguno de sus `grupos`, vía `usuario_pertenece_a`) y por qué no lo está si no (`motivo_bloqueo`: `'proximamente'` si no está construido, `'sin_permiso'` si sí lo está pero el usuario no tiene el grupo). `apps/core/views.py::dashboard_view` solo llama `modulos_para(request.user)` y pasa el resultado al template — la lógica de permisos vive en `configuracion/modulos.py`, no en la vista. Los íconos SVG de cada módulo están en `apps/core/templatetags/core_extras.py` (tag `{% icono_modulo key color size %}`), reutilizados en el sidebar y en la grilla de módulos. Hoy solo `finanzas` tiene `construido=True`; agregar un módulo nuevo es añadir una entrada a `MODULOS` (y, cuando exista de verdad, poner `construido=True` y su `url_name`).
- **Login sin JS, POST normal.** `apps/core/templates/core/login.html` es solo la tarjeta (con el logo real de Grupo Intra) — el `<form>` hace un POST normal a `login_view`, que autentica y redirige directo a `/dashboard/`. Hubo una versión con animación de bienvenida (colapso de tarjeta + grilla de módulos + vuelo hacia el sidebar) implementada con `fetch` + JS; se quitó a propósito por decisión del usuario para simplificar — si se retoma en el futuro, cuidado con el bug que tuvo: una regla CSS de autor (`display: flex`) sobre un elemento con el atributo `hidden` gana sobre la regla `[hidden]{display:none}` del navegador, así que hace falta un selector explícito `.clase[hidden] { display: none; }` para que `el.hidden = true` funcione de verdad.
- **Autorización basada en pertenencia a grupos, resuelta fuera de la vista.** El patrón general del portal es: la lógica de qué grupos pueden ver qué vive en un catálogo o helper (no en el template), y las vistas solo lo consultan. Dentro de cada módulo de negocio, el control de acceso a las vistas usa `usuario_pertenece_a` (ej. `apps/finanzas/views.py::acceso_finanzas_requerido`).
- **`apps/finanzas/`** — primer módulo de negocio, con backend real (modelos + migraciones + Django admin), siguiendo la SRS interna (`SRS-FIN-001`). Modelos: `Tabulador` (tarifas por categoría de terapeuta, versionado — nunca se edita uno vigente, se agrega uno nuevo), `Ingreso`, `Egreso`, `Honorario` (bono/total se calculan una sola vez en `save()`, para que honorarios ya cerrados no cambien si el tabulador se actualiza después), `Donativo` (captura manual de CFDI — folio, XML, PDF —, sin integración a un PAC todavía). 5 vistas (`tablero`, `ingresos`, `honorarios`, `donativos`, `reportes`), todas protegidas por `acceso_finanzas_requerido` (grupo `Finanzas`, `Dirección` o `Sistemas`). La captura de datos por ahora es vía `/admin/`; formularios propios dentro de la UI de Finanzas quedan para una sesión futura. Gráficos (barras, dona) son CSS puro (`conic-gradient`, alturas por `%`), no SVG ni JS — ver `apps/finanzas/static/finanzas/css/finanzas.css`. Filtro de plantilla `{{ valor|dinero }}` (en `apps/finanzas/templatetags/finanzas_extras.py`) formatea montos como `$1,234` / `-$1,234`.
- **Password reset apunta a templates que no existen todavía.** `apps/core/autenticacion/urls.py` referencia `core/password_reset_sent.html`, `core/password_reset_form.html` y `core/password_reset_done.html`, pero solo `apps/core/templates/core/password_reset.html` existe en el repo. El flujo de "olvidé mi contraseña" romperá en producción hasta crear esos tres templates (gap preexistente, no introducido por la reestructura a `apps/`).
- **Email backend está en modo consola.** `config/settings.py` configura primero SMTP de Gmail con credenciales placeholder y luego sobreescribe `EMAIL_BACKEND` a `django.core.mail.backends.console.EmailBackend` — los correos de recuperación de contraseña se imprimen en consola, no se envían de verdad, hasta que se configure un correo institucional real.
- **Estáticos y templates son por-app**, bajo `apps/<app>/static/<label>/` y `apps/<app>/templates/<label>/` (convención estándar de Django vía `APP_DIRS`, no hay carpeta `static/`/`templates/` global). Nota: el `label` de cada `AppConfig` (`core`, `finanzas`) es lo que determina la carpeta de templates/estáticos, no el nombre de la carpeta física — por eso `apps/core/templates/core/...` y no `apps/core/templates/apps.core/...`.
- **`apps/finanzas` usa herencia de templates** (`{% extends %}`/`{% block %}`) vía `finanzas/_base.html` — una excepción deliberada y acotada solo a `apps/finanzas`, para no duplicar el sidebar/header en las 5 vistas. El resto del proyecto (login, dashboard, password reset) sigue sin herencia, cada template es un documento HTML independiente.
- **URLs de `apps/finanzas` usan namespace** (`app_name = 'finanzas'` en `apps/finanzas/urls.py`) — se referencian como `{% url 'finanzas:tablero' %}`, etc. Las de `apps/core` siguen siendo planas (`login`, `dashboard`, `logout`) para no romper `LOGIN_URL`/`LOGIN_REDIRECT_URL` en `settings.py`.
- Comentarios de código y mensajes de usuario están en español; mantener ese idioma al editar cualquier app del proyecto.
