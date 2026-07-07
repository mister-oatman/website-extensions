# Mister Oatman Extensions

Website extensions for **Mister Oatman**.

## Follower-count scraper

A daily [GitHub Actions workflow](.github/workflows/scrape.yml) scrapes the
follower counts for every handle listed in
[`instagram_profiles`](instagram_profiles) and
[`tiktok_profiles`](tiktok_profiles) (one username per line, one file per
platform) and writes them to `site/data.json`.

For each profile the scraper reads the follower count from the public profile
page directly. Only if that fails does it fall back to a
[Serper](https://serper.dev) Google search. The fallback needs a Serper API key,
supplied via the `SERPER_API_KEY` environment variable (see
[Running locally](#running-locally)); without it, the direct scrape still runs
and only the fallback is skipped.

The workflow runs every morning (`05:00 UTC`) and can also be triggered manually
from the **Actions** tab. It reads `SERPER_API_KEY` from a repository secret
(**Settings → Secrets and variables → Actions**); add it there to enable the
fallback in CI. While the repository is private, the resulting JSON is printed to
the workflow log (the **Show scraped data** step) instead of being published.

### Publishing to GitHub Pages

Once the repository is public, uncomment the Pages blocks in
[the workflow](.github/workflows/scrape.yml), then in **Settings → Pages** set
**Source** to **GitHub Actions**. The JSON will then be served at
`https://<user>.github.io/<repo>/data.json`.

### Running locally

```sh
uv sync
uv run scrape            # writes site/data.json

# Optional: enable the Serper search fallback.
SERPER_API_KEY=<your-key> uv run scrape
```

Use `uv run scrape --help` to override the input files or output directory.
