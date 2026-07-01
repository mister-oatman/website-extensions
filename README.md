# Mister Oatman Extensions

Website extensions for **Mister Oatman**.

## Follower-count scraper

A daily [GitHub Actions workflow](.github/workflows/scrape.yml) scrapes the
Instagram and TikTok follower counts for every handle listed in
[`usernames_to_scrape`](usernames_to_scrape) (one username per line) and
publishes the results to GitHub Pages:

- `data.json` — machine-readable counts, e.g. `https://<user>.github.io/<repo>/data.json`

The workflow runs every morning (`05:00 UTC`) and can also be triggered manually
from the **Actions** tab.

### One-time setup

1. Push this repository to GitHub.
2. In **Settings → Pages**, set **Source** to **GitHub Actions**.
3. Trigger the **Scrape follower counts** workflow once from the **Actions** tab
   (or wait for the next scheduled run). The Pages URL appears in the workflow
   summary once it completes.

### Running locally

```sh
uv sync
uv run scrape            # writes site/data.json
```

Use `uv run scrape --help` to override the input file or output directory.
