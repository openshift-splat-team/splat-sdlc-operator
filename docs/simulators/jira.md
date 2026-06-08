# Jira Simulator

The Jira simulator is a minimal FastAPI application that implements the Jira
REST API endpoints used by this project. Data is persisted in SQLite so it
survives container restarts.

## What It Provides

A lightweight replacement for Atlassian Jira that supports:

- Issue CRUD (create, read, update)
- JQL search
- Issue linking
- Comments
- Transitions (status changes)
- Bulk import from `.xlsx` exports
- A web UI for browsing and managing issues

## Setup

The Jira simulator starts automatically with `make dev`. No additional setup
is required.

## Configuration

Set these variables in `.env`:

| Variable | Value | Description |
|---|---|---|
| `JIRA_URL` | `http://localhost:8080` | Simulator URL (host-side) |
| `JIRA_USER` | `admin` | Username (accepted but not validated) |
| `JIRA_TOKEN` | `admin` | Token (accepted but not validated) |
| `JIRA_PROJECT_KEY` | `SDLC` | Default project key for new issues |

Inside containers, `JIRA_URL` is set to `http://jira-simulator:8080` by the
compose file.

## REST API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/rest/api/2/serverInfo` | Server metadata |
| GET | `/rest/api/2/myself` | Current user info |
| GET | `/rest/api/2/field` | Available fields |
| GET | `/rest/api/2/issueLinkType` | Link type definitions |
| GET | `/rest/api/2/issue/{key}` | Fetch a single issue |
| GET | `/rest/api/2/search` | JQL search |
| POST | `/rest/api/2/issue` | Create an issue |
| PUT | `/rest/api/2/issue/{key}` | Update an issue |
| POST | `/rest/api/2/issueLink` | Create an issue link |
| POST | `/rest/api/2/issue/{key}/comment` | Add a comment |
| GET | `/rest/api/2/issue/{key}/comment` | List comments |
| GET | `/rest/api/2/issue/{key}/transitions` | Available transitions |
| POST | `/rest/api/2/issue/{key}/transitions` | Transition an issue |

Auto-generated Swagger docs are available at **http://localhost:8080/docs**.

## Web UI

Browse at **http://localhost:8080/ui**:

| Path | Description |
|---|---|
| `/ui` | List all issues |
| `/ui/issue/{key}` | Issue detail with comments and links |
| `/ui/create` | Create a new issue |
| `/ui/issue/{key}/edit` | Edit an existing issue |

The trigger script also accepts simulator URLs (e.g.
`http://localhost:8080/ui/issue/SDLC-1`) anywhere a Jira issue key is expected.

## Seeding Test Data

Import `.xlsx` files exported from real Jira:

1. Place `.xlsx` files in the `test_data/` directory
2. Run one of:

```bash
make jira-seed          # import, skipping issues that already exist
make jira-seed-force    # re-import, overwriting existing issues and labels
```

The simulator must be running (`make dev`) before seeding.

### Programmatic Import

The simulator also exposes a bulk import endpoint:

```
POST /api/admin/import
```

This is what the `jira-seed` Makefile target calls internally via the
`scripts/jira_seed.py` script.
