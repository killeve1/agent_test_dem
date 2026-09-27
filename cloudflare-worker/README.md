# Cloudflare cron trigger for the oil-news-agent

GitHub's own scheduled-workflow cron is unreliable on the free tier:
`run_agent.yml` is configured for every 10 minutes but was observed
actually firing every 2-6 hours. This Worker does no agent logic
itself — it just calls GitHub's `workflow_dispatch` API on a real,
reliable Cloudflare Cron Trigger schedule, so the existing workflow
runs on time. GitHub's own `schedule:` trigger is left in place as a
free backstop (in case this Worker's token expires or it stops
running) — the two triggers overlapping just means an occasional
extra "hold" cycle, which is harmless.

## One-time setup

1. **Create a GitHub PAT** (fine-grained, scoped to just this repo):
   - GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token
   - Repository access: only select `killeve1/agent_test_dem`
   - Permissions: **Actions: Read and write** (this is the only permission needed — it's what lets the token call `workflow_dispatch`)
   - Copy the token; you won't be able to see it again.

2. **Log into Cloudflare** (from this directory):
   ```bash
   npx wrangler login
   ```
   Opens a browser to authorize your Cloudflare account.

3. **Store the GitHub token as a Worker secret** (never committed):
   ```bash
   npx wrangler secret put GITHUB_TOKEN
   ```
   Paste the PAT from step 1 when prompted.

4. **Deploy:**
   ```bash
   npx wrangler deploy
   ```
   Prints the Worker's URL (e.g. `https://oil-agent-cron-trigger.<your-subdomain>.workers.dev`).

5. **Verify it works** — trigger it manually once:
   ```bash
   curl https://oil-agent-cron-trigger.<your-subdomain>.workers.dev/dispatch
   ```
   Should return `ok: dispatched`, and a new run should appear at
   `github.com/killeve1/agent_test_dem/actions` within a few seconds.

From here, the Cron Trigger in `wrangler.toml` (`*/10 * * * *` by
default) fires automatically — no further action needed.

## Changing the interval

Edit the `crons` line in `wrangler.toml`, then `npx wrangler deploy`
again. Cloudflare Cron Triggers support down to 1-minute granularity;
the real constraint at that point is Groq/Gemini free-tier per-minute
rate limits, not Cloudflare's.

## Rotating the GitHub token

Re-run `npx wrangler secret put GITHUB_TOKEN` with a new PAT — no
redeploy needed, secrets update independently of the Worker code.
