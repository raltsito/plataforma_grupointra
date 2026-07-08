from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.core.configuracion.modulos import modulos_para


@login_required
def dashboard_view(request):
    modulos = modulos_para(request.user)
    accesos_rapidos = [m for m in modulos if m['disponible']][:3]

    contexto = {
        'modulos': modulos,
        'accesos_rapidos': accesos_rapidos,
    }
    return render(request, 'core/dashboard.html', contexto)
