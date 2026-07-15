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
[SerpApi](https://serpapi.com) Google search. The fallback needs a SerpApi API
key, supplied via the `SERPAPI_KEY` environment variable (see
[Running locally](#running-locally)); without it, the direct scrape still runs
and only the fallback is skipped.

If both the direct scrape and the search fail for a profile, the scraper carries
that profile's **last known count** forward instead of leaving a gap. It takes
the value from the previous `data.json` — the local `site/data.json` if present,
otherwise the previously published copy (`--previous-data-url`, default the
GitHub Pages URL), since `site/` is gitignored and CI starts from a clean
checkout. Only if no previous count exists is `followers` recorded as `null`.

The workflow fires every morning (`05:00 UTC`), but the script itself decides
on which days to actually scrape: it asks the (free) SerpApi Account API how
many searches are left in the billing period and when the period renews,
assumes the worst case of every profile needing the search fallback with both
search prefixes, and spreads the runs that budget affords evenly over the
rest of the period ([`scraper/app/quota.py`](scraper/app/quota.py)).
Days that don't fit the budget are skipped without touching the output. The
script also memorises which search prefix (`site:` or none) last worked per
platform in `.scraper-state.json` (persisted via the CI cache) and tries that
one first, which usually halves the fallback's search usage.

The workflow can also be triggered manually from the **Actions** tab. It reads `SERPAPI_KEY` from a repository secret
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

# Optional: enable the SerpApi search fallback.
SERPAPI_KEY=<your-key> uv run scrape
```

Use `uv run scrape --help` to override the input files or output directory.

## Badges

Each run also renders a set of **SVG follower-count badges** into `site/badges/`
— a pure-HTML alternative for pages that can't run JavaScript. A page embeds one
with a plain `<img>` tag, and it refreshes whenever the site is republished:

```html
<img src="https://<user>.github.io/<repo>/badges/<username>-<platform>-<variant>.svg"
     alt="Instagram followers">
```

Filenames are `<username>-<platform>-<variant>.svg` (all lower-case). Every
account is rendered in four variants:

| Variant      | Layout                                          | Colour | Best on           |
| ------------ | ----------------------------------------------- | ------ | ----------------- |
| `logo-white` | count followed by the platform logo             | white  | dark backgrounds  |
| `logo-black` | count followed by the platform logo             | black  | light backgrounds |
| `name-white` | platform name in caps before the count, no logo | white  | dark backgrounds  |
| `name-black` | platform name in caps before the count, no logo | black  | light backgrounds |

The count is Inter text on an otherwise transparent background; the logo
variants append the Instagram or TikTok glyph, while the name variants prefix
`INSTAGRAM` / `TIKTOK`. For example, `alinafrie-instagram-name-white.svg` reads
`INSTAGRAM 251K`.

A normal `uv run scrape` regenerates the badges. To rebuild them from an existing
`data.json` without scraping — and without spending any SerpApi quota, handy for
iterating on the design — run `uv run render-badges`. The manual
[**Rebuild badges** workflow](.github/workflows/badges.yml) does the same on CI
and redeploys Pages without scraping.
