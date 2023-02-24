"""
ASGI config for {{ cookiecutter.project_name }} project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/dev/howto/deployment/asgi/

"""
import os
import sys
from pathlib import Path

from django.urls import re_path
from django.core.asgi import get_asgi_application


# This allows easy placement of apps within the interior
# {{ cookiecutter.project_slug }} directory.
BASE_DIR = Path(__file__).resolve(strict=True).parent.parent
sys.path.append(str(BASE_DIR / "{{ cookiecutter.project_slug }}"))

# If DJANGO_SETTINGS_MODULE is unset, default to the local settings
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
django_asgi_app = get_asgi_application()

from channels.auth import AuthMiddlewareStack  # noqa isort:skip
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa isort:skip

from notification.consumers import NotificationConsumer  # noqa isort:skip

application = ProtocolTypeRouter(
    {
        # Django's ASGI application to handle traditional HTTP requests
        "http": django_asgi_app,
        # WebSocket chat handler
        "websocket": AuthMiddlewareStack(
            URLRouter(
                [
                    re_path(r"^notify/message/$", NotificationConsumer.as_asgi()),
                ]
            )
        ),
    }
)
