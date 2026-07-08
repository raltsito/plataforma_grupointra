from django import template

register = template.Library()


@register.filter
def dinero(valor):
    """Formatea un número como moneda: 1234.5 -> $1,234."""
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return valor
    return f'-${abs(numero):,.0f}' if numero < 0 else f'${numero:,.0f}'
