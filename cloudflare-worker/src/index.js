/**
 * Reliable external scheduler for the oil-news-agent's GitHub Actions
 * workflow. GitHub's own scheduled-workflow cron is unreliable on the
 * free tier (this repo's run_agent.yml is configured for every 10
 * minutes but was observed actually firing every 2-6 hours). This
 * Worker does no agent logic itself -- it just calls GitHub's
 * workflow_dispatch API on Cloudflare's much more reliable Cron
 * Trigger schedule, so the *existing* workflow runs on time.
 */
export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(dispatchWorkflow(env));
  },

  // Lets you trigger it manually to test: `curl https://<worker>.workers.dev/dispatch`
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (url.pathname === "/dispatch") {
      const result = await dispatchWorkflow(env);
      return new Response(result, { status: result.startsWith("ok") ? 200 : 500 });
    }
    return new Response("Not found. POST/GET /dispatch to trigger manually.", { status: 404 });
  },
};

async function dispatchWorkflow(env) {
  const url =
    `https://api.github.com/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}` +
    `/actions/workflows/${env.GITHUB_WORKFLOW_FILE}/dispatches`;

  const res = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "oil-agent-cron-trigger-worker",
      "X-GitHub-Api-Version": "2022-11-28",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ ref: env.GITHUB_REF }),
  });

  if (res.status === 204) {
    console.log("Dispatched run_agent.yml successfully");
    return "ok: dispatched";
  }

  const text = await res.text();
  console.error(`workflow_dispatch failed: ${res.status} ${text}`);
  return `error: ${res.status} ${text}`;
}
