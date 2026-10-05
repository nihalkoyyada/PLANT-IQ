# PlantIQ Development Instructions

## Project

PlantIQ is an industrial asset analytics platform for solar and wind power plants.

## Full-Stack Scope

The Full-Stack implementation is responsible for:

- React frontend
- TypeScript frontend development
- FastAPI backend
- Python backend development
- PostgreSQL and TimescaleDB
- SQLAlchemy
- Alembic migrations
- Authentication
- Role-based access control
- REST APIs
- Data ingestion infrastructure
- Dashboards
- Asset Explorer
- Anomaly APIs and UI integration
- Copilot API/UI integration
- Reports
- Admin functionality
- Testing
- Docker and deployment configuration

## AI Scope

The AI developer is responsible for:

- Machine learning models
- Anomaly detection algorithms
- Root cause analysis
- AI/Copilot intelligence
- Model-related processing

The Full-Stack implementation should provide the APIs, database integration,
UI integration, and infrastructure required to consume AI services.

Do not implement AI algorithms unless they are specifically required for
Full-Stack integration.

## Development Rules

- Follow the project document as the source of truth.
- Implement functionality sprint by sprint.
- Do not implement future sprint functionality prematurely.
- Use React and TypeScript for the frontend.
- Use Python and FastAPI for the backend.
- Use PostgreSQL and TimescaleDB for persistence.
- Use Alembic for database migrations.
- Use SQLAlchemy for database access.
- Use environment variables for secrets and configuration.
- Never commit passwords, API keys, JWT secrets, or other credentials.
- Write tests for backend functionality.
- Keep frontend and backend responsibilities separated.
- Do not replace PostgreSQL/TimescaleDB with SQLite.
- Do not modify the documented database schema without understanding the
  impact on the rest of the system.

## Working Style

Before implementing a major feature:

1. Read the relevant project documentation.
2. Explain the architecture and implementation approach.
3. Identify the files that need to change.
4. Implement only the requested scope.
5. Run appropriate tests or validation.
6. Report what was changed and whether validation passed.

Do not rewrite unrelated parts of the project.

## Sprint Discipline

Work on the current sprint only unless explicitly instructed otherwise.

For Sprint 1, focus on:

- Monorepo and Docker Compose foundation
- Database and Alembic migrations
- Authentication and RBAC
- Plant and Asset CRUD APIs
- Backend tests
- React application shell
- Routing
- Authentication flow
- Seeded Surya-A asset tree

Do not implement Sprint 2+ features during Sprint 1 unless explicitly requested.