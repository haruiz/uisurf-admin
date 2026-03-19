# UISurf Admin API

This service enables the UISurf application to manage UISurf agent sessions.

The API is responsible for:
- creating UISurf agent session containers on demand
- listing active sessions managed by the platform
- restoring managed sessions from Docker when the API restarts
- deleting sessions when they are no longer needed
- exposing authenticated admin endpoints for user and session management

## Purpose

UISurf needs a backend control plane that can start and stop isolated agent sessions.
This project provides that control plane.

Each session is backed by a Docker container running the `uisurf-agent:latest` image.
The API stores session metadata in memory during runtime and rebuilds that state from
Docker on startup, so existing managed sessions are preserved across API restarts.

## Stack

- FastAPI
- Pydantic and `pydantic-settings`
- Docker Python SDK
- Firebase Admin SDK

## Configuration

The project uses two settings groups:

- `AppSettings`
  - API and Firebase application configuration
- `SessionSettings`
  - UISurf agent session configuration

Important environment variables:

- `API_ROOT_PATH`
  - Base path used when the API is mounted behind a reverse proxy. Default: `/api`.
- `UI_AGENT_IMAGE`
  - Docker image used to start a new UISurf agent session container. Default: `uisurf-agent:latest`.
- `UI_AGENT_CONTAINER_PORT`
  - TCP port exposed inside the UISurf agent container. The API publishes this port to a host port for each session. Default: `6080`.
- `SESSION_BASE_PORT`
  - Starting point for host port allocation. New session ports are assigned above this value. Default: `7000`.
- `SESSION_CONTAINER_PREFIX`
  - Prefix used when generating Docker container names for managed sessions. Default: `uisurf-agent-session`.
- `SESSION_BIND_HOST`
  - Host interface used when publishing session container ports. Default: `127.0.0.1`.
- `PUBLIC_VNC_HOST`
  - Public hostname used to generate the session VNC URL returned by the API. Required if clients must receive a working session URL.
- `PUBLIC_VNC_SCHEME`
  - URL scheme used with `PUBLIC_VNC_HOST`, typically `http` or `https`. Default: `http`.
- `GEMINI_API_KEY`
  - Gemini API key forwarded into each UISurf agent session container. Optional, but at least one provider key must be set.
- `GOOGLE_API_KEY`
  - Google AI API key forwarded into each UISurf agent session container. Optional, but at least one provider key must be set.
- `FIREBASE_PROJECT_ID`
  - Firebase project identifier used by the admin backend configuration.
- `FIREBASE_CLIENT_EMAIL`
  - Firebase service-account client email, used when explicit Firebase credentials are configured.
- `FIREBASE_PRIVATE_KEY`
  - Firebase service-account private key, used when explicit Firebase credentials are configured.

`PUBLIC_VNC_HOST` is required for the API to generate valid VNC URLs for sessions.

At least one of `GEMINI_API_KEY` or `GOOGLE_API_KEY` must be configured so newly
created UISurf agent containers receive the credentials they need at startup.

## Local Run

Install dependencies:

```bash
uv sync
```

Start the API:

```bash
uv run fastapi dev src/uisurf_admin/main.py --port 8080
```

Or use:

```bash
sh run.local.sh
```

For local development, `run.local.sh` loads `uisurf-admin/.env` first and then
falls back to `../uisurf-app/.env` for missing settings. That keeps Firebase
token verification aligned with the app backend when you have not duplicated the
same `FIREBASE_*` values into the admin service config yet.

## Session Lifecycle

1. UISurf calls the session creation endpoint.
2. The API validates the session ID.
3. The API starts a Docker container using the configured UISurf agent image.
4. The API returns session metadata, including the public VNC URL.
5. On restart, the API restores managed sessions from Docker labels.

## Main Endpoints

- `GET /sessions/sessions`
- `POST /sessions/session/create`
- `GET /sessions/session/{session_id}`
- `DELETE /sessions/session/{session_id}`

## Authentication

The API uses Firebase ID tokens for authentication.

Admin-only routes require the authenticated user to have the `admin` claim set to
`true`.

## Notes

- Session state is reconstructed from Docker, not from a database.
- Containers are identified through Docker labels under the `uisurf-agent.*` namespace.
- If Docker is unavailable, session management endpoints will fail.
