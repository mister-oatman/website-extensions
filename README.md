# Mister Oatman Extensions

Website extensions for **Mister Oatman**.

## Follower-count scraper

A daily [GitHub Actions workflow](.github/workflows/scrape.yml) scrapes the
Instagram and TikTok follower counts for every handle listed in
[`usernames_to_scrape`](usernames_to_scrape) (one username per line) and writes
them to `site/data.json`.

The workflow runs every morning (`05:00 UTC`) and can also be triggered manually
from the **Actions** tab. While the repository is private, the resulting JSON is
printed to the workflow log (the **Show scraped data** step) instead of being
published.

### Publishing to GitHub Pages

Once the repository is public, uncomment the Pages blocks in
[the workflow](.github/workflows/scrape.yml), then in **Settings → Pages** set
**Source** to **GitHub Actions**. The JSON will then be served at
`https://<user>.github.io/<repo>/data.json`.

### Running locally

```sh
uv sync
uv run scrape            # writes site/data.json
```

Use `uv run scrape --help` to override the input file or output directory.
