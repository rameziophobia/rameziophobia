# Saved GitHub stats card

The profile README embeds `assets/github-stats.svg` from this repository.
Displaying this card does not call Vercel, run a function, query GitHub's API, or
wait for a refresh. GitHub serves the saved image even if the generator is unavailable.

`Refresh GitHub stats snapshot` runs hourly at minute 17 UTC, when manually
dispatched, or when its workflow/script/tests change on `main`. It requests the
public aggregate SVG from the existing Vercel generator, validates it, and commits
only the image if the bytes changed. GitHub/CDN caching and Actions queue delays
mean the displayed counts can lag behind the latest activity.

The downloader requires HTTP 200, an SVG content type, bounded response size,
the expected profile header and all six numeric metrics. It rejects redirects,
error cards, executable elements, external links/assets and incomplete XML.
Network failures are retried up to three times with a 60-second timeout per
attempt. Only a fully validated response atomically replaces the local image.
Failed jobs never publish a replacement, so the last successful image survives.
Publication uses a normal, non-force Git push; concurrent repository changes can
make a job fail safely and the next run will retry from the latest `main`.

## Permissions

- The existing `PROFILE_READ_TOKEN` stays only in the Vercel stats app. Its only
  scope remains `read:user`; it cannot read repository contents or write data.
- This workflow receives no PAT and needs no new repository secrets. It downloads
  only the same aggregate image that is already public on the profile.
- The publish step uses GitHub's short-lived `GITHUB_TOKEN` with `contents: write`
  for **this public profile repository only**. It can save the image here, but
  cannot read private contribution data or access other repositories. Other token
  configurable permissions are disabled. The checkout action is pinned to its commit and does
  not persist credentials; the download step is not given an authentication token.
- No repository names, private code, commit messages or PR titles are downloaded
  by the refresh workflow. No third-party storage or analytics service is added.

## Maintenance

Use Actions → Refresh GitHub stats snapshot → Run workflow for an immediate
refresh. A failed refresh is visible there, while the profile retains its image.
If the source changes its rendering or profile header, update the validator after
reviewing the new output. Do not weaken it to accept an error card.

GitHub can delay scheduled workflows or disable them after 60 days with no
repository activity. Even then, the image remains available; re-enable the
workflow in Actions to resume updates. The streak card is a separate service and
is unchanged by this stats-card fix.
