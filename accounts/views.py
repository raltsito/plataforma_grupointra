from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.contrib.auth.decorators import login_required
from django.shortcuts import render



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

    return render(request, 'accounts/login.html')


# Pantalla temporal después de iniciar sesión correctamente.
@login_required
def dashboard_view(request):
    return render(request, 'accounts/dashboard.html')

@login_required
def logout_view(request):
    """Maneja el cierre de sesión de manera segura mediante POST."""
    if request.method == 'POST':
        logout(request)
        return redirect('login')
    
    # Si se intenta acceder por GET, se redirige al dashboard
    return redirect('dashboard')

@login_required
def dashboard_view(request):
    user = request.user
    
    # Creamos un diccionario 'contexto' para enviar los permisos al HTML
    contexto = {
        'es_sistemas': user.groups.filter(name='Sistemas').exists() or user.is_superuser,
        'es_admin': user.groups.filter(name='Administración').exists(),
        'es_terapeuta': user.groups.filter(name='Terapeutas').exists(),
        'es_recepcion': user.groups.filter(name='Recepción').exists(),
        'es_direccion': user.groups.filter(name='Dirección').exists(),
    }
    
    return render(request, 'accounts/dashboard.html', contexto)