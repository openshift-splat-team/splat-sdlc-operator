# Gitea Simulator

Gitea provides a GitHub-compatible REST API for local development. It replaces
GitHub so workflows can fork repos, create branches, open PRs, and post
comments without touching real repositories.

## Setup

Gitea starts automatically with `make dev`. After the stack is running, run the
one-time setup:

```bash
make gitea-setup        # create admin user, API token, and staging org
make gitea-seed-repos   # create orgs and staging repositories
```

### Create a reviewer user (optional)

```bash
make gitea-reviewer     # creates user: reviewer / reviewer123
```

This user can be used for manual PR reviews in the Gitea UI.

## Configuration

After running `gitea-setup`, copy the printed API token into your `.env`:

```bash
# Print the token if you missed it
make gitea-token
```

Set these variables in `.env`:

| Variable | Value | Description |
|---|---|---|
| `GITHUB_TOKEN` | (from `make gitea-token`) | Gitea API token |
| `GITHUB_BASE_URL` | `http://localhost:3000/api/v1` | Gitea REST API base (host-side) |
| `GITHUB_BOT_USER` | `gitea` | Bot username for PR operations |
| `STAGING_GITHUB_ORG` | `staging` | Organization where forks and staging repos are created |

Inside containers, `GITHUB_BASE_URL` is set to `http://gitea:3000/api/v1`
(container DNS) by the compose file.

## Browsing

Open **http://localhost:3000** and log in with `gitea` / `gitea123`.

The UI shows organizations, repositories, pull requests, and issues. It
mirrors the GitHub experience for development and testing.

## Mirroring Repositories

To mirror a real GitHub repository into Gitea:

```bash
make gitea-mirror-repo REPO=openshift/enhancements
```

This creates the org (if needed), clones the repo from GitHub, and sets up
an 8-hour mirror interval. The workflow also mirrors repos on demand during
execution.

## Seeding Staging Repos

`make gitea-seed-repos` creates empty staging repositories under the staging
org. These are the targets for fork and PR operations during workflow execution.

## Switching Back to Real GitHub

To run workflows against real GitHub instead of Gitea:

1. Set `GITHUB_TOKEN` to a GitHub personal access token
2. Remove or comment out `GITHUB_BASE_URL` (defaults to the GitHub API)
3. Set `GITHUB_BOT_USER` to your GitHub username
4. Set `STAGING_GITHUB_ORG` to your GitHub organization

Restart workers after changing `.env`:

```bash
make dev-reload
```
