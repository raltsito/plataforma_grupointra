from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse


def _es_peticion_ajax(request):
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


# Muestra el login y valida las credenciales con el sistema de usuarios de Django.
# Responde JSON cuando el login.html lo llama por fetch (para poder correr la
# animación de acceso antes de navegar al dashboard); si no hay JS, el <form>
# normal sigue funcionando exactamente igual que antes (POST + redirect).
def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(
            request,
            username=username,
            password=password
        )

        if user is not None:
            login(request, user)
            if _es_peticion_ajax(request):
                return JsonResponse({'ok': True, 'redirect_url': reverse('dashboard')})
            return redirect('dashboard')

        if _es_peticion_ajax(request):
            return JsonResponse({'ok': False, 'error': 'Usuario o contraseña incorrectos.'}, status=401)
        messages.error(request, 'Usuario o contraseña incorrectos.')

    return render(request, 'core/login.html')


@login_required
def logout_view(request):
    """Maneja el cierre de sesión de manera segura mediante POST."""
    if request.method == 'POST':
        logout(request)
        return redirect('login')

    # Si se intenta acceder por GET, se redirige al dashboard
    return redirect('dashboard')
