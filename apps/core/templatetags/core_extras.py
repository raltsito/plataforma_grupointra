from django import template
from django.utils.safestring import mark_safe

register = template.Library()

# Mismos trazos que el mockup "Centralización Intra" (método icon()).
_ICONOS = {
    'agenda': (
        '<rect x="3" y="4.5" width="18" height="16" rx="2"></rect>'
        '<line x1="3" y1="9" x2="21" y2="9"></line>'
        '<line x1="8" y1="2.5" x2="8" y2="6"></line>'
        '<line x1="16" y1="2.5" x2="16" y2="6"></line>'
        '<circle cx="8" cy="13.5" r="1.1" fill="{color}" stroke="none"></circle>'
        '<circle cx="12" cy="13.5" r="1.1" fill="{color}" stroke="none"></circle>'
    ),
    'finanzas': (
        '<line x1="4" y1="20" x2="20" y2="20"></line>'
        '<rect x="5" y="12" width="3.2" height="6" rx=".6"></rect>'
        '<rect x="10.4" y="8" width="3.2" height="10" rx=".6"></rect>'
        '<rect x="15.8" y="5" width="3.2" height="13" rx=".6"></rect>'
    ),
    'orbitaedu': (
        '<path d="M2.5 8.5 12 4l9.5 4.5L12 13 2.5 8.5Z"></path>'
        '<path d="M6 10.5V15c0 1.4 2.7 2.8 6 2.8s6-1.4 6-2.8v-4.5"></path>'
        '<line x1="21.5" y1="8.5" x2="21.5" y2="13"></line>'
    ),
    'orbitacontrol': (
        '<line x1="4" y1="7" x2="20" y2="7"></line>'
        '<line x1="4" y1="12" x2="20" y2="12"></line>'
        '<line x1="4" y1="17" x2="20" y2="17"></line>'
        '<circle cx="9" cy="7" r="2" fill="#fff"></circle>'
        '<circle cx="15" cy="12" r="2" fill="#fff"></circle>'
        '<circle cx="8" cy="17" r="2" fill="#fff"></circle>'
    ),
    'rh': (
        '<circle cx="9" cy="8" r="3"></circle>'
        '<path d="M3.5 19a5.5 5.5 0 0 1 11 0"></path>'
        '<circle cx="17" cy="9" r="2.3"></circle>'
        '<path d="M16 14.6a4.6 4.6 0 0 1 4.5 4.4"></path>'
    ),
    'capacitacion': (
        '<path d="M12 3 5 6v5.5c0 4.3 3 7.4 7 9 4-1.6 7-4.7 7-9V6l-7-3Z"></path>'
        '<path d="M9 12l2 2 4-4"></path>'
    ),
    'soporte': (
        '<circle cx="12" cy="12" r="8.5"></circle>'
        '<circle cx="12" cy="12" r="3.4"></circle>'
        '<line x1="14.4" y1="9.6" x2="18" y2="6"></line>'
        '<line x1="9.6" y1="14.4" x2="6" y2="18"></line>'
        '<line x1="14.4" y1="14.4" x2="18" y2="18"></line>'
        '<line x1="9.6" y1="9.6" x2="6" y2="6"></line>'
    ),
    'comunicados': (
        '<path d="M4 10v4a1 1 0 0 0 1 1h2l9 4V5L7 9H5a1 1 0 0 0-1 1Z"></path>'
        '<path d="M19 9a3 3 0 0 1 0 6"></path>'
        '<line x1="8" y1="15" x2="9" y2="20"></line>'
    ),
}


@register.simple_tag
def icono_modulo(key, color='currentColor', size=22):
    contenido = _ICONOS.get(key, '<circle cx="12" cy="12" r="8"></circle>').replace('{color}', color)
    svg = (
        f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{contenido}</svg>'
    )
    return mark_safe(svg)
