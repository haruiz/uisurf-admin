from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging
from fastapi.responses import JSONResponse
from fastapi import status
from uisurf_admin.routers import sessions, users
from uisurf_admin.config import get_app_settings, get_firebase_app
from uisurf_admin.services.session_manager import get_session_manager

logger = logging.getLogger(__name__)

def create_app():
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Initialize shared services before the API starts serving requests."""
        logger.info("Api is starting")
        initialize_firebase_app()
        session_manager = get_session_manager()
        session_manager.restore_sessions()
        app.state.session_manager = session_manager
        logger.info(
            "Restored %s managed UISurf agent sessions from Docker",
            len(session_manager.list_sessions()),
        )
        yield
        logger.info("Api is stopping")

    app_settings = get_app_settings()
    app = FastAPI(
        title="Uisurf  Session Manager API",
        description=(
            "This api enable admin users and authorized login to dynamically create ui agent sections"
        ),
        version="0.2.0",
        root_path=app_settings.api_root_path,
        swagger_ui_parameters={"defaultModelsExpandDepth": 1},
        lifespan=lifespan,
    )

    origins = ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(Exception)
    async def validation_exception_handler(request, err):
        """Convert uncaught exceptions into a JSON 500 response."""
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"detail": str(err)}
        )


    @app.get("/")
    async def health_check():
        """Return a basic health response for the API process."""
        return JSONResponse(
            status_code=200, content={"message": "API is up and running"}
        )

    app.include_router(
        users.router,
        prefix="/users",
        tags=["users"],
        responses={404: {"description": "Not found"}},
    )

    app.include_router(
        sessions.router,
        prefix="/sessions",
        tags=["sessions"],
        responses={404: {"description": "Not found"}},
    )

    return app


def initialize_firebase_app():
    """Initialize and return the default Firebase Admin application."""
    return get_firebase_app()
