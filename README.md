<p align="center">
  <img src="static/brand/frame-mark.svg" width="80" height="80" alt="Frame logo" />
</p>
<h1 align="center">Frame</h1>
<p align="center">Your photo library. From first edit to final post.</p>
<p align="center">
  <a href="#docker-quick-start">Get started</a> &middot;
  <a href="#configuration">Configuration</a> &middot;
  <a href="#container-images-ghcr">Container images</a> &middot;
  <a href="https://github.com/bizbazboz/Frame/issues">Issues</a>
</p>
<p align="center">
  <a href="https://github.com/bizbazboz/Frame/actions/workflows/ci.yml"><img src="https://github.com/bizbazboz/Frame/actions/workflows/ci.yml/badge.svg" alt="CI and publish" /></a>
  <img src="https://img.shields.io/badge/self--hosted-111315?style=flat&labelColor=111315&color=c3f26b" alt="Self-hosted" />
  <a href="#pocket-id"><img src="https://img.shields.io/badge/Pocket_ID-ready-c3f26b?labelColor=111315" alt="Pocket ID ready" /></a>
</p>

---

A private, self-hosted photo library and social-post tracker. Organise photo groups and edits, review your Pool, and track campaigns across accounts. Built with Flask, SQLite and OIDC authentication, including Pocket ID. Posts are recorded manually; Frame never publishes through platform APIs.

## Features

- Multi-file and folder imports, managed image versions, and exact-content duplicate prevention.
- Pool review with metadata, histogram, category tags, and Staging/Never Post decisions.
- Local projects with a sidebar switcher, separate photo sets and project-aware galleries.
- Filterable galleries, bulk editing and deletion, and configurable tags and tag groups.
- Reusable platforms and accounts, campaigns with multiple destinations, and planned/published tracking.
- Dark interface, authenticated image access, CSRF protection, and local logout.

## Docker quick start

1. Copy `.env.example` to `.env` and replace the placeholders. Generate a secret with `python -c "import secrets; print(secrets.token_hex(32))"`.
2. Register your exact callback URL with your OIDC provider, for example `https://photos.example.com/auth/callback`.
3. Run `docker compose up -d --build` and open port 8000 through your HTTPS reverse proxy.

The database is persisted at `./data/app.db` and images at `./media/`. Back up both. Containers apply Alembic migrations before starting Gunicorn. Existing pre-Alembic libraries must follow the adoption steps below first.

## Projects

Choose a project from the sidebar dropdown. The adjacent **+** opens project management, where you can create or rename projects and delete empty ones. Each project has its own photos, workflow counts, review queue and campaigns. Tags, classifications, platforms and social accounts are shared and reusable across projects. Projects organise one local library; they are not separate user permissions or tenants.

Existing libraries upgrade into **Main library** automatically through migration `0002`; image paths, tags, campaigns and publication history are preserved. To reorganise existing photos, select them in a gallery, open **Bulk edit**, and choose **Move to project**. Versions and campaign records move with their group; files stay in the managed media folder. Duplicate prevention still spans all projects, and duplicate messages name the project containing the image.

Project context is included in links and forms so another tab's project switch cannot redirect an upload or edit into the wrong set. The most recent sidebar selection is remembered in the current login session. A project containing photos and the last remaining project cannot be deleted.

## Large and resumable uploads

Imports and edited versions use separate **8 MiB HTTP requests**, rather than sending the whole selection in one request. This follows [Cloudflare's smaller-request upload guidance](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/4xx-client-error/error-413/) and avoids the per-request body limit. Frame has no total file or selection size cap; available storage and image-format/browser capabilities still apply. JavaScript is required for chunking; non-JavaScript multipart uploads remain subject to your proxy's request limits.

`UPLOAD_CHUNK_SIZE_MB` defaults to `8` and accepts `1`–`16` (MiB). Set your reverse proxy's per-request allowance above the configured chunk size. Progress, automatic retries and Pause/Resume work while the selected files remain open in the page. Closing/reloading the page requires reselecting files. Already completed files stay saved. Import completion stays on the import screen with a summary; **View Pool** opens the imported photos.

Upload IDs are bound to the signed-in subject and project. Replayed chunks and completion requests are idempotent. Partial data stays in `media/.uploads/` and is never served as library media. Completed files are hashed in bounded blocks, checked for duplicates, then moved into the managed library. Existing content hashes are indexed on first use. Gunicorn's worker timeout is 300 seconds to accommodate large-file verification.

Uploads and completion receipts inactive for 24 hours are removed when another upload starts, or manually with:

```sh
docker compose exec app flask --app app uploads-cleanup
```

## Inspiration

Each project has an **Inspiration** page for Reddit posts/comments and Instagram posts/reels. Save a full post URL and an optional title to create an embedded card. Tracking parameters are stripped, and repeat links within the same project are skipped. The same link can be saved in different projects.

Cards use isolated frames served by Reddit or Instagram, with a permanent **Open post** link. Private, removed or embedding-disabled posts may not render. No platform API credentials or server-side social API calls are used. Inspiration is not cached offline. Remove a project's inspiration links before deleting the empty project.

## Install as an app

Frame is an installable Progressive Web App. Serve it over HTTPS (localhost/127.0.0.1 works over HTTP for development). In supporting desktop and Android browsers, use **Install Frame** in the sidebar when available, or the browser's install menu. On iPhone/iPad, open Frame in Safari and choose **Share → Add to Home Screen**. Installed windows use Frame's icon and dark theme; Pocket ID/OIDC sign-in remains required.

The service worker caches only the public offline screen and app icons. Your library, uploaded photos, account details and authentication responses stay network-only, and private responses use `Cache-Control: no-store`. When disconnected, opening the app shows an offline screen; edits and uploads require a connection and are never queued for later. Reconnect and choose **Try again**. App updates take effect on the next page load without automatically reloading an unsaved form.

## Configuration

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | Required, long random Flask session secret. |
| `OIDC_ISSUER` | Provider issuer URL, without the discovery suffix. |
| `OIDC_CLIENT_ID` | OIDC confidential client ID. |
| `OIDC_CLIENT_SECRET` | OIDC confidential client secret. |
| `OIDC_ALLOWED_SUBJECTS` | Comma-separated subject IDs; blank permits all authenticated identities. |
| `TRUST_PROXY` | Set true only behind a trusted proxy providing forwarded headers. |
| `COOKIE_SECURE` | Keep true for HTTPS; false for local HTTP only. |
| `UPLOAD_CHUNK_SIZE_MB` | Transport chunk size in MiB, from 1 to 16; default 8. |

No real credentials are included. Runtime configuration, databases and photos are ignored by Git and excluded from Docker builds.

### Pocket ID

Create a confidential OIDC client, register the exact callback URL, and permit the appropriate users/groups in its Access tab. Use Pocket ID's issuer/APP_URL for `OIDC_ISSUER`. Subject allowlist entries are user IDs from the `sub` claim, not usernames or emails. Frame uses discovery, `openid profile email`, and PKCE S256. The issuer must be reachable from the container. Local logout clears Frame's session only.

## Development

Use Python 3.12 or 3.13. Create and activate a virtual environment, then:

```sh
python -m pip install -r requirements.txt
# Copy .env.example to .env and configure it.
flask --app app db upgrade
flask --app app run
```

Tests use temporary libraries and mocked authentication; no real OIDC configuration is required:

```sh
python -m pytest -q
```

## Existing databases

Back up `data/app.db` and `media/`. Stop the application while adopting a library created before Alembic support:

```sh
docker compose stop app
docker compose build
docker compose run --rm --entrypoint flask app --app app adopt-legacy-db
docker compose up -d
```

The adoption command compares all tables against the frozen initial schema and refuses mismatched or already tracked databases. It stamps revision `0001` without changing library records or media. Startup then applies subsequent migrations. Fresh installations do not need adoption. For local development, run `flask --app app adopt-legacy-db` followed by `flask --app app db upgrade`.

## Schema changes

Alembic through Flask-Migrate replaces the old delete-and-recreate workflow. Do not delete your database to apply schema changes. After updating models:

```sh
flask --app app db migrate -m "Describe the schema change"
# Review the generated revision before applying it.
flask --app app db upgrade
flask --app app db check
python -m pytest -q
```

Commit revisions with their model changes. SQLite alterations use batch mode. Back up before upgrading or downgrading. `flask --app app db downgrade` runs a revision's downgrade; downgrading revision 0001 removes library tables. Alembic never changes media files. See the [Flask-Migrate documentation](https://flask-migrate.readthedocs.io/en/latest/) for the migration CLI.

## Library behaviour

Tags are created only on the Tags page and assigned to photo groups through category dropdowns. Groups move between Pool, Staging and Never Post explicitly. Never Post blocks new campaigns. Marking a campaign's first destination published moves its group to Final. Publication times and date filters use UTC.

Imports and version uploads compare SHA-256 hashes against every tracked image, including existing libraries. Renamed exact duplicates are skipped, including simultaneous uploads. Different edits and re-encoded files remain distinct. Existing duplicates are not removed automatically. Browser selection also removes exact duplicates before submission.

Bulk operations support up to 500 groups. Deleting a group removes its versions, campaigns, destinations and tracked files; shared tags/accounts and untracked files remain. A version cannot be deleted if it is the last version or is used by a campaign. Files are staged and restored if a database deletion fails.

The sidebar shows the OIDC display name and uses a DiceBear Notionists avatar with an opaque HMAC seed; raw subjects and emails are not sent as seeds. Metadata inspection reads EXIF/IPTC/XMP and other Pillow-supported fields without modifying files. Proprietary camera MakerNotes are not decoded.

## GitHub and licensing

GitHub Actions tests Python 3.12 and 3.13, checks migration drift, and builds and smoke-tests the Docker image. CI needs no secrets. Keep `.env`, data, media, caches, virtual environments and editor settings private; the ignore files cover these paths.

Bundled fonts retain their SIL Open Font License notices in `static/fonts/`. No application license has been selected. Choose a license before granting others redistribution or modification rights.

## Container images (GHCR)

After tests and the Docker smoke test pass, pushes to `main` publish `ghcr.io/bizbazboz/frame:latest`, `:main`, and a `:sha-<commit>` tag. Version tags such as `v1.2.3` publish `:v1.2.3`, `:1.2.3`, `:1.2`, and a commit tag. `latest` follows `main`. Pull requests and other branches do not publish images. The workflow can also be run manually on `main` or a version tag.

Publishing uses GitHub's built-in `GITHUB_TOKEN` with package-write permission, following the [GitHub Container Registry workflow](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images). No personal token or deployment credentials need to be stored in Actions. The package is linked to this repository through its image source label. To permit anonymous pulls, set the package's visibility to Public in GitHub package settings; otherwise authenticate Docker with an account that has package-read permission.

Images include Linux amd64 and arm64 variants. Docker automatically selects the correct architecture. To use the prebuilt image, create a `compose.yml` beside your private `.env`:

```yaml
services:
  app:
    image: ghcr.io/bizbazboz/frame:latest
    ports:
      - "8000:8000"
    env_file: .env
    volumes:
      - ./data:/app/data
      - ./media:/app/media
    restart: unless-stopped
```

Then run:

```sh
docker compose pull
docker compose up -d
```

Configure OIDC and back up your library as described above. Existing pre-Alembic databases still require the one-time adoption command before the first start. For production deployments, choose a version or image digest when you need a fixed release.

## Raspberry Pi

Use a Raspberry Pi with a **64-bit OS**, such as Raspberry Pi OS Lite (64-bit) on a Pi 3, 4 or 5, and install [Docker Engine and the Compose plugin](https://docs.docker.com/engine/install/debian/). `uname -m` should report `aarch64`. The published image supports `linux/arm64`; 32-bit Raspberry Pi OS (`armv7l`/`armhf`) is not supported.

```sh
git clone https://github.com/bizbazboz/Frame.git
cd Frame
cp .env.example .env
# Configure .env with your OIDC/Pocket ID client and a random SECRET_KEY.
docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d
```

The prebuilt Compose file works on both Raspberry Pi and amd64 hosts without a platform override or an on-device build. It persists the library in `./data/` and `./media/`. Register the callback using the Pi's actual hostname/domain, not `localhost` on another device. Use HTTPS for secure cookies and PWA installation; set `COOKIE_SECURE=false` only if testing over plain HTTP.

For an existing pre-Alembic library, stop the old app and back up its data and media, then adopt it before starting this image:

```sh
docker compose -f docker-compose.ghcr.yml run --rm --entrypoint flask app --app app adopt-legacy-db
```

Update the running installation with:

```sh
docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d
```

CI builds and smoke-tests the application on native amd64 and arm64 runners before publishing a [multi-platform image](https://docs.docker.com/build/ci/github-actions/multi-platform/). This validates the ARM64 container; physical Raspberry Pi hardware is not part of the CI environment.
