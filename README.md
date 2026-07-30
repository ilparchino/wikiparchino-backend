# Wiki Parchino Backend

The backend service for Wiki Parchino. It provides authentication, structured storage, media handling, search, relationships, and weighted random/daily activities through a versioned HTTP API. The companion frontend is maintained as a separate repository.

## Features

- Fixed user accounts with password hashing and opaque Bearer sessions.
- Self-service password changes that preserve the current session and revoke other sessions.
- Administrator-only account management with user creation, reversible deactivation, role changes, password resets, and session revocation.
- Paginated content, account, and authentication activity with 90-day retention for authentication events.
- CRUD APIs for people, places, epochs, and events.
- Gregorian partial dates for events and epoch boundaries, with conservative range validation.
- Shared pullable identifiers and configurable rarity weights.
- Person-event and person-place relationships.
- Authenticated image upload, download, deletion, and batched list previews.
- Cross-entity search, random pulls, and deterministic daily pulls.
- Hard deletion with database cascades and protected place/epoch references.
- Constrained activity history identifying users who create, update, delete, or relink content.

## Technology

- Python 3.11+
- FastAPI and Pydantic
- SQLAlchemy 2.x
- Alembic
- SQLite
- pytest and HTTPX

## Project Layout

```text
.
|-- alembic/             Database migration environment and revisions
|-- app/
|   |-- api/             FastAPI route modules and dependencies
|   |-- config.py        Environment-driven runtime settings
|   |-- database.py      SQLAlchemy engine and session setup
|   |-- main.py          Application entry point
|   |-- models.py        Database models
|   |-- partial_dates.py Shared partial-date validation and comparison semantics
|   |-- schemas.py       Request and response schemas
|   |-- security.py      Password and session helpers
|   |-- security_events.py Security-event recording and retention
|   `-- seed.py          Anonymized local demo and minimal test data
|-- tests/               API, behavior, and migration tests
|-- alembic.ini
|-- Makefile             Short environment-aware development commands
`-- pyproject.toml
```

The SQLite database and uploaded media are runtime data. They are intentionally excluded from Git.

## Development Workflow

Run all commands from the backend repository root. The Makefile uses the project-local virtual environment and loads the selected environment file for migrations, seeding, tests, and the server.

### First-time setup

Requirements are Python 3.11 or newer and GNU Make.

1. Create the virtual environment and install the application with its development dependencies:

   ```bash
   make install
   ```

2. Create the local configuration file:

   ```bash
   cp .env.example .env
   ```

3. Review `.env` before continuing. For the standard laptop setup, keep the SQLite database and media paths local and set `WIKI_PARCHINO_FRONTEND_ORIGINS` to the exact comma-separated origins used by the frontend. Do not put production secrets in the example file nor commit `.env`.

4. Create or update the database through Alembic:

   ```bash
   make migrate
   ```

5. Optionally load the anonymized local demo accounts and sample content into an empty database:

   ```bash
   make seed
   ```

   The demo contains 8 generic accounts, 24 people, 12 places, 5 epochs, 40 events, relationships, activity history, and generated sample images. The usernames are `admin`, `admin2`, and `utente1` through `utente6`; they all use the development-only password `demo-password-123`. The final account is inactive, `admin` and `admin2` are administrators, and `admin` is the protected Owner.

   The seed intentionally refuses to mix demo records with an existing database or non-empty media directory. To rebuild the disposable local demo, stop the server and run:

   ```bash
   rm -f wiki_parchino.db
   rm -rf media
   make migrate
   make seed
   ```

   For non-demo instances, create each fixed account through a hidden password prompt instead:

   ```bash
   make user
   ```

   After creating the intended production administrator, assign or transfer the singular protected Owner role:

   ```bash
   make owner USERNAME=francesco
   ```

   The target must already be an active administrator. A transfer keeps the previous Owner active as an ordinary administrator.

6. Verify the installation, then start the development server:

   ```bash
   make test
   make dev
   ```

The API is ready when `http://127.0.0.1:8000/api/health` returns `{"status":"ok"}`. Interactive API documentation is available at `http://127.0.0.1:8000/docs` and the OpenAPI schema at `http://127.0.0.1:8000/openapi.json`.

### Routine development

After switching branches or pulling changes:

1. Run `make install` when `pyproject.toml` changed. It is safe to run again at any time.
2. Run `make migrate` before starting the server. Alembic applies only pending revisions, so this is safe when the database is already current.
3. Run `make test` to catch API, schema, and migration regressions.
4. Run `make dev` to start Uvicorn with automatic reload.

You do not need to migrate after ordinary Python changes when no Alembic revision was added, but running `make migrate` remains harmless. Never update the schema manually or use SQLAlchemy `create_all()` as a substitute for migrations.

### Changing the database schema

When a SQLAlchemy model changes:

1. Generate a migration with a descriptive name:

   ```bash
   make revision MESSAGE="describe the schema change"
   ```

2. Review the generated file under `alembic/versions/`. Autogenerated migrations must be checked for constraints, foreign-key behavior, data conversion, and downgrade correctness.
3. Apply the revision with `make migrate`.
4. Run `make test` and commit the model and migration changes together.

Existing migration files should not be edited after they have been shared or applied to another environment. Add a new revision instead.

### Other commands

Use another environment file with `make ENV_FILE=.env.test test`, override the development bind address with `make HOST=0.0.0.0 PORT=8080 dev`, or run an arbitrary environment-aware command with:

```bash
make run CMD="alembic current"
```

Run `make help` for the complete command list. `make clean` removes reproducible caches and build output while preserving `.env`, `.venv`, SQLite databases, and `media/`.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `WIKI_PARCHINO_DATABASE_URL` | `sqlite:///./wiki_parchino.db` | SQLAlchemy database URL. |
| `WIKI_PARCHINO_MEDIA_DIR` | `./media` | Uploaded media directory. |
| `WIKI_PARCHINO_FRONTEND_ORIGINS` | `http://127.0.0.1:5173` | Comma-separated browser origins allowed by CORS. |
| `WIKI_PARCHINO_FRONTEND_URL` | First configured origin | Complete public frontend URL included in Telegram notifications. |
| `WIKI_PARCHINO_SESSION_DAYS` | `14` | Session validity in days. |
| `WIKI_PARCHINO_ROOT_PATH` | empty | Public URL prefix removed by a reverse proxy, such as `/wikiparchino`. |
| `WIKI_PARCHINO_TELEGRAM_BOT_TOKEN` | empty | Secret token used only for outbound maintenance notifications. |
| `WIKI_PARCHINO_TELEGRAM_CHAT_ID` | empty | Target group for maintenance notifications. |

Relative paths are resolved from the current working directory when supplied through environment variables. Run backend commands from this repository root for predictable results.

All complete timestamps are generated and exchanged in UTC. SQLite stores the normalized UTC clock value without an offset, while the SQLAlchemy UTC type restores timezone information when rows are loaded; API responses therefore include `Z` or `+00:00`. Clients may convert these explicit UTC instants to the user's local timezone for display. Event dates and epoch boundaries are separate partial Gregorian calendar values and are not affected by this policy.

Keep `WIKI_PARCHINO_ROOT_PATH` empty for direct local access. When a reverse proxy strips a public path prefix before forwarding requests, set it to that exact prefix so FastAPI generates working OpenAPI and OAuth redirect URLs.

## API Overview

All application endpoints are under `/api`:

- `/auth/login`, `/auth/logout`, and `/me`
- `/maintenance/status` (public and non-cacheable)
- `/profile` and `/profile/password`
- `/admin/summary`, `/admin/users`, and `/admin/activity` (administrators only)
- `/people`, `/places`, `/epochs`, and `/events`
- relationship endpoints nested under people, places, epochs, and events
- `/search`
- `/pulls/random` and `/pulls/daily`
- `/media`, `/media/previews`, and `/media/{id}`

Except for health, maintenance status, and login, application endpoints require `Authorization: Bearer <token>`. Login returns the opaque token once; the server stores only its hash. Routes below `/api/admin` additionally require an active account with `is_admin = true`; this is enforced by the backend and does not depend on frontend visibility.

Epochs may define an optional partial start and/or end date. Partial dates support year, year-month, or complete Gregorian precision. Event writes are rejected only when their possible date interval is definitely outside the selected epoch boundary; ambiguous overlaps remain valid. Updating an epoch is rejected when its proposed boundaries would exclude an existing linked event.

Administrators deactivate accounts instead of deleting them. Deactivation immediately revokes all sessions while preserving attribution and activity history; reactivation permits a future login but does not create a session. Content actions remain in `activity_log`. Account and access actions are stored separately in `security_event_log`; authentication events are pruned after 90 days and credential material is never logged. The OpenAPI UI is the authoritative interactive endpoint reference.

At most one active administrator can be the protected Owner. Other administrators may inspect that account but cannot change its name, role, status, password, or sessions. Ownership is never assigned through the API or frontend; use `make owner USERNAME=<active-admin>` from the trusted backend host.

## Maintenance Mode

Maintenance is controlled from the backend command line, not from the administrator API. Scheduling immediately prevents new logins while existing sessions remain usable until the deadline. At the deadline, the first request atomically revokes every session and all routes return `503 Service Unavailable` except `/api/maintenance/status`, `/api/health`, and CORS preflights.

```bash
make maintenance-schedule MINUTES=15 MESSAGE="Aggiornamento del server"
make maintenance-status
make maintenance-end
```

`MINUTES` must be between `0` and `10080`. Ending before the deadline cancels maintenance; ending afterward reopens the API, but revoked sessions remain invalid.

When both Telegram variables are configured, scheduling and ending maintenance send short-lived outbound notifications to the configured group. The sender performs one HTTPS request and exits: it does not read messages, poll Telegram, expose a webhook, or run as a service. Delivery is best-effort, so a Telegram failure prints a warning without undoing the maintenance transition. Retry or verify notifications with:

```bash
make maintenance-notify
make telegram-test
```

Keep the real bot token only in the protected backend environment file. Never put it in command arguments, Git, frontend variables, or SQLite.

## Testing

Run the complete backend suite:

```bash
make test
```

The suite uses a small isolated seed rather than the larger manual demo dataset. It covers authentication and session reuse, maintenance enforcement and Telegram delivery failures, administrator authorization and account safeguards, account deactivation, activity/security history, profile activity, password changes, CRUD, database constraints, hard-delete behavior, relationships, media previews and storage, search, pulls, demo seeding, and fresh Alembic migrations.

## Deployment

Production deployments should use persistent database and media paths outside the source checkout, load secrets from a protected environment file, and expose the application through an HTTPS reverse proxy. Restrict CORS to the exact frontend origins and never expose the development server directly to the internet.

Apply pending schema revisions with `make migrate` before starting a new backend version. Create production accounts with `make user`, assign the protected Owner through `make owner USERNAME=<active-admin>`, and never use the demo seed in production.

Back up SQLite and the media directory together before updates. For disruptive operations, use the maintenance commands to prevent new logins, notify active users, and block access while the deployment is in progress. Network deployments must provide the corresponding source code as required by AGPLv3.

## Security guidelines

- Keep `.env`, SQLite databases, uploaded media, backups, logs, session data, and real credentials out of Git.
- The seeded accounts and shared demo password are for local development only and must be replaced before deployment.
- New passwords must contain 12–200 printable characters. Printable Unicode and ordinary internal spaces are accepted; leading/trailing whitespace and control or non-printable characters are rejected without modifying the submitted password.
- Expose the API only through HTTPS, restrict CORS to the exact frontend origin, keep dependencies updated, and back up the database together with the media directory.

## License

Copyright (C) 2026 Francesco Borri. Licensed under the GNU Affero General Public License version 3 only. See [LICENSE](LICENSE).
