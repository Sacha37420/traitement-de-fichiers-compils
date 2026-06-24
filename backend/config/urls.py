import os
from django.urls import path, include
from django.http import HttpResponseRedirect
from django.views.static import serve as static_serve
from django.conf import settings
import drf_spectacular_sidecar
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView


class CustomSwaggerUIView(SpectacularSwaggerView):
    template_name = "drf_spectacular/swagger_ui.html"
    extra_context = {
        "KEYCLOAK_ISSUER_URI": getattr(settings, "KEYCLOAK_ISSUER_URI", ""),
        "KEYCLOAK_CLIENT_ID": getattr(settings, "KEYCLOAK_CLIENT_ID", "swagger-ui"),
    }


_SIDECAR_DIR = os.path.join(
    os.path.dirname(drf_spectacular_sidecar.__file__),
    'static', 'drf_spectacular_sidecar', 'swagger-ui-dist',
)

urlpatterns = [
    path('api/docs/sidecar/<path:path>', static_serve, {'document_root': _SIDECAR_DIR}),
    path('api/docs/oauth2-redirect.html', static_serve, {
        'path': 'oauth2-redirect.html', 'document_root': _SIDECAR_DIR,
    }, name='oauth2-redirect'),
    path('api/docs/oauth2-redirect.js', static_serve, {
        'path': 'oauth2-redirect.js', 'document_root': _SIDECAR_DIR,
    }),
    path('', lambda request: HttpResponseRedirect(request.META.get('SCRIPT_NAME', '') + '/api/docs/')),
    path('api/', include('api.urls')),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', CustomSwaggerUIView.as_view(), name='swagger-ui'),
]
