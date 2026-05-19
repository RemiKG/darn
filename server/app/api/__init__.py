"""API routers — all mounted under /api by app.main."""

from app.api import demo, incidents, settings_api, state, yours

routers = [
    state.router,
    demo.router,
    incidents.router,
    yours.router,
    settings_api.router,
]
