// Cloudflare Worker for publishing state.json to GitHub
// Deploy: wrangler deploy publish-worker.js
// Set secret: wrangler secret put GH_TOKEN

const REPO = "ZeAlenu/knesset-legislation-flow";
const FILE_PATH = "state.json";
const ALLOWED_ORIGIN = "*"; // Restrict in production

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: {
          "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
          "Access-Control-Allow-Methods": "POST",
          "Access-Control-Allow-Headers": "Content-Type, X-Publish-Key",
        },
      });
    }

    if (request.method !== "POST") {
      return new Response("Method not allowed", { status: 405 });
    }

    // Simple auth: check publish key
    const publishKey = request.headers.get("X-Publish-Key");
    if (publishKey !== env.PUBLISH_KEY) {
      return new Response("Unauthorized", { status: 401 });
    }

    try {
      const stateData = await request.text();
      
      // Validate JSON
      JSON.parse(stateData);

      // Get current file SHA
      let sha = "";
      const getResp = await fetch(`https://api.github.com/repos/${REPO}/contents/${FILE_PATH}`, {
        headers: {
          "Authorization": `token ${env.GH_TOKEN}`,
          "User-Agent": "knesset-publish-worker",
        },
      });
      if (getResp.ok) {
        const data = await getResp.json();
        sha = data.sha;
      }

      // Commit new state
      const content = btoa(unescape(encodeURIComponent(stateData)));
      const putResp = await fetch(`https://api.github.com/repos/${REPO}/contents/${FILE_PATH}`, {
        method: "PUT",
        headers: {
          "Authorization": `token ${env.GH_TOKEN}`,
          "User-Agent": "knesset-publish-worker",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          message: "publish: update shared state",
          content,
          sha: sha || undefined,
        }),
      });

      if (!putResp.ok) {
        const err = await putResp.text();
        return new Response(`GitHub error: ${err}`, { 
          status: 500,
          headers: { "Access-Control-Allow-Origin": ALLOWED_ORIGIN },
        });
      }

      return new Response(JSON.stringify({ ok: true }), {
        headers: {
          "Content-Type": "application/json",
          "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
        },
      });
    } catch (e) {
      return new Response(`Error: ${e.message}`, { 
        status: 500,
        headers: { "Access-Control-Allow-Origin": ALLOWED_ORIGIN },
      });
    }
  },
};
