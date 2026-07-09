from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render


# Muestra el login y valida las credenciales con el sistema de usuarios de Django.
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
            return redirect('dashboard')

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
