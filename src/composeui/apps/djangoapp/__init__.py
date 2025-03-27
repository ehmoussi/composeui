from composeui.apps.baseapp import BaseApp
from composeui.model.djangoormmodel import DjangoORMModel

import django
from django.conf import settings

import sys
from pathlib import Path
from typing import List, Optional


class DjangoApp(BaseApp):
    def __init__(
        self,
        model: DjangoORMModel,
        base_dir: Path,
        root_urlconf: str,
        is_debug: bool = True,
        secret_key: Optional[str] = None,
        allowed_hosts: Optional[List[str]] = None,
        template_dirs: Optional[List[Path]] = None,
        installed_apps: Optional[List[str]] = None,
    ) -> None:
        self.model = model
        self._base_dir = base_dir
        self._web_path = Path(Path(__file__), "..", "..", "..", "web")
        self._root_urlconf = root_urlconf
        self._is_debug = is_debug
        self._secret_key = secret_key
        self._allowed_hosts = allowed_hosts
        self._template_dirs = template_dirs if template_dirs is not None else []
        self._installed_apps = installed_apps if installed_apps is not None else []

    def _configure(self) -> None:
        settings.configure(
            BASE_DIR=self._base_dir,
            # Quick-start development settings - unsuitable for production
            # See https://docs.djangoproject.com/en/5.1/howto/deployment/checklist/
            SECRET_KEY=self._secret_key,
            DEBUG=self._is_debug,
            ALLOWED_HOSTS=self._allowed_hosts,
            INSTALLED_APPS=[
                *self._installed_apps,
                # third-party libraries
                # django
                "django.contrib.admin",
                "django.contrib.auth",
                "django.contrib.contenttypes",
                "django.contrib.sessions",
                "django.contrib.messages",
                "django.contrib.staticfiles",
            ],
            MIDDLEWARE=[
                "django.middleware.security.SecurityMiddleware",
                "django.contrib.sessions.middleware.SessionMiddleware",
                "django.middleware.common.CommonMiddleware",
                "django.middleware.csrf.CsrfViewMiddleware",
                "django.contrib.auth.middleware.AuthenticationMiddleware",
                "django.contrib.messages.middleware.MessageMiddleware",
                "django.middleware.clickjacking.XFrameOptionsMiddleware",
            ],
            ROOT_URLCONF=self._root_urlconf,
            TEMPLATES=[
                {
                    "BACKEND": "django.template.backends.django.DjangoTemplates",
                    "DIRS": [
                        Path(Path(__file__), "..", "templates").resolve(),
                        Path(self._web_path, "django", "table", "templates"),
                        *self._template_dirs,
                    ],
                    "APP_DIRS": True,
                    "OPTIONS": {
                        "context_processors": [
                            "django.template.context_processors.debug",
                            "django.template.context_processors.request",
                            "django.contrib.auth.context_processors.auth",
                            "django.contrib.messages.context_processors.messages",
                        ],
                    },
                },
            ],
            WSGI_APPLICATION="composeui.apps.djangoapp.wsgi.application",
            # Database
            # https://docs.djangoproject.com/en/5.1/ref/settings/#databases
            DATABASES=self.model.databases,
            # Password validation
            # https://docs.djangoproject.com/en/5.1/ref/settings/#auth-password-validators
            AUTH_PASSWORD_VALIDATORS=[
                {
                    "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",  # noqa: E501
                },
                {
                    "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
                },
                {
                    "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
                },
                {
                    "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
                },
            ],
            # Internationalization
            # https://docs.djangoproject.com/en/5.1/topics/i18n/
            LANGUAGE_CODE="en-us",
            TIME_ZONE="UTC",
            USE_I18N=True,
            USE_TZ=True,
            # Static files (CSS, JavaScript, Images)
            # https://docs.djangoproject.com/en/5.1/howto/static-files/
            STATIC_URL="static/",
            STATICFILES_DIRS=[
                Path(self._web_path, "django", "table", "static"),
                Path(self._web_path, "django", "table", "dist"),
            ],
            # Default primary key field type
            # https://docs.djangoproject.com/en/5.1/ref/settings/#default-auto-field
            DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
        )

    def run(self) -> None:
        self._configure()
        django.setup()
        try:
            from django.core.management import execute_from_command_line
        except ImportError as exc:
            raise ImportError(
                "Couldn't import Django. Are you sure it's installed and "
                "available on your PYTHONPATH environment variable? Did you "
                "forget to activate a virtual environment?"
            ) from exc
        execute_from_command_line(sys.argv)
