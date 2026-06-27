# Temporary hackathon hosting

## Recommended option: Cloudflare Quick Tunnel

For a few-hour frontend integration session, run the backend on the operator's
Windows laptop and expose only `127.0.0.1:8000` through a Cloudflare Quick
Tunnel. Quick Tunnels create a random `trycloudflare.com` HTTPS URL without a
Cloudflare account, public IP, or inbound router rule. Cloudflare documents them
as development/testing tunnels with a 200 in-flight request limit and no
service-level agreement, so they are appropriate for this hackathon session,
not production.

Official references:

- [Cloudflare Quick Tunnels](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/)
- [How Cloudflare Tunnel works](https://developers.cloudflare.com/tunnel/)

Run:

```powershell
winget install --id Cloudflare.cloudflared --exact
.\scripts\start-public-demo.ps1 -Mode demo -FrontendOrigin https://your-frontend.example
```

Use `-Mode live` only after the Knowledge Base contains the intended lab
documents. Live mode runs the AWS preflight before opening the tunnel.

## Security boundary

The public profile provides pragmatic demo controls:

- Uvicorn listens on loopback only; `cloudflared` makes an outbound connection.
- A newly generated 256-bit token is required in `X-Demo-Token` for every route
  except `/health`.
- CORS allows only the frontend origins passed to the launcher; `*` is rejected.
- `/ask` and `/onboarding` have a per-client sliding-window rate limit.
- `/docs`, `/redoc`, and `/openapi.json` return 404.
- Prompts, retrieved content, history, credentials, and the token are not written
  to request logs.
- Stopping the launcher terminates both processes and invalidates the URL.

The token is visible to anyone who can inspect the frontend application. It is
a short-lived abuse barrier, not user authentication. Share the URL and token
only with the hackathon team, use reviewed non-sensitive documents, monitor the
terminal, and stop the tunnel immediately after the demo.

## Why not deploy the backend to a free host?

| Option | Fit for this prototype | Main limitation |
|---|---|---|
| Cloudflare Quick Tunnel | Best for a few hours; no deployment conversion and local AWS credentials keep working | Development-only, random URL, no SLA |
| Render free web service | Useful if the laptop cannot remain online | Spins down after 15 idle minutes; local SQLite filesystem is ephemeral |
| GitHub Codespaces port forwarding | Convenient for repository collaborators | Public forwarded ports are unauthenticated unless the app adds its own controls |
| ngrok free | Viable tunnel alternative | Free limits apply and browser HTML traffic can show an interstitial |

Official details: [Render free services](https://render.com/docs/free),
[Codespaces port security](https://docs.github.com/en/codespaces/reference/security-in-github-codespaces),
and [ngrok free-plan limits](https://ngrok.com/docs/pricing-limits/free-plan-limits).

Bedrock is the managed AI service, not a general-purpose FastAPI host. GitHub
Pages also cannot run Python server code. A Quick Tunnel avoids moving SQLite,
AWS credentials, and process state to a third-party host during the hackathon.

## Frontend request

```javascript
const response = await fetch(`${API_BASE_URL}/ask`, {
  method: "POST",
  headers: {
    "Content-Type": "application/json; charset=utf-8",
    "X-Demo-Token": DEMO_API_TOKEN,
  },
  body: JSON.stringify({
    message: "輝度つまみはどこですか？",
    session_id: "frontend-demo",
  }),
});
```

Keep `API_BASE_URL` and `DEMO_API_TOKEN` in the frontend host's temporary
environment configuration. Do not commit either value. A new Quick Tunnel gets
a new URL and token each time the launcher starts.
