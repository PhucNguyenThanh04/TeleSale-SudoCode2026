from datetime import datetime, timezone

from starlette.requests import HTTPConnection

from app.auth import current_user
from app.voice_main import create_app as production_app

USER = dict(id='offline-operator', username='offline', customer_id='C-OFFLINE', name='Offline Customer',
            phone='0984726714', zalo_id='zalo_dung99', fb_id='fb_offline', active=True)


def create_app(settings):
    app = production_app(settings)

    async def authenticated(connection: HTTPConnection):
        connection.state.auth_expires = datetime.now(timezone.utc).timestamp() + 3600
        connection.state.demo_user = USER
        return USER

    app.dependency_overrides[current_user] = authenticated
    return app
