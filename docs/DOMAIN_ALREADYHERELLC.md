# Domain Deployment Plan — alreadyherellc.com

## Production Domain

Primary domain: `alreadyherellc.com`
Registrar: GoDaddy
Target runtime: Oracle Cloud Infrastructure Always Free
Reverse proxy: Caddy

## Recommended DNS Model

Preferred model:

```txt
GoDaddy Registrar
  -> Cloudflare Free DNS / Proxy
    -> OCI Always Free Public IP
      -> Caddy HTTPS Reverse Proxy
        -> GMAOS / EAOS services
```

Keeping DNS at GoDaddy also works, but Cloudflare Free is preferred for easier proxying, TLS handling, security rules, and future access controls.

## Required DNS Records

After the OCI instance public IP is known, configure either direct A records:

```txt
A      @        <OCI_PUBLIC_IP>
A      www      <OCI_PUBLIC_IP>
A      app      <OCI_PUBLIC_IP>
A      api      <OCI_PUBLIC_IP>
A      status   <OCI_PUBLIC_IP>
```

Or one root A record plus CNAME aliases:

```txt
A      @        <OCI_PUBLIC_IP>
CNAME  www      alreadyherellc.com
CNAME  app      alreadyherellc.com
CNAME  api      alreadyherellc.com
CNAME  status   alreadyherellc.com
CNAME  docs     alreadyherellc.com
```

Do not expose `n8n.alreadyherellc.com` until authentication and access controls are confirmed.

## Subdomain Map

```txt
alreadyherellc.com          Public website / landing page
www.alreadyherellc.com      Public alias
app.alreadyherellc.com      GMAOS command center
api.alreadyherellc.com      EAOS runtime API
status.alreadyherellc.com   Uptime/status page
n8n.alreadyherellc.com      Automation server, protected only
docs.alreadyherellc.com     Documentation / SOP portal, optional
```

## OCI Firewall

Only these public ports should be open:

```txt
22/tcp   SSH, restricted by source IP where possible
80/tcp   HTTP for HTTPS issuance/redirect
443/tcp  HTTPS public web
```

Do not expose these publicly:

```txt
Postgres
Redis
Qdrant / Chroma
Ollama
n8n without auth
internal runtime ports
database admin panels
backup/download routes
approval mutation routes
```

## Deployment Files Added

```txt
caddy/Caddyfile
docs/DOMAIN_ALREADYHERELLC.md
.env.example domain variables
docker-compose.yml with Caddy service
```

## Domain Launch Checklist

```txt
[ ] Confirm GoDaddy account controls alreadyherellc.com
[ ] Decide GoDaddy DNS or Cloudflare Free DNS
[ ] Create OCI Always Free A1 instance
[ ] Record OCI public IP
[ ] Add DNS records
[ ] Copy .env.example to .env on server
[ ] Replace server-side passwords
[ ] Run docker compose up -d --build
[ ] Verify https://alreadyherellc.com
[ ] Verify https://app.alreadyherellc.com
[ ] Verify https://api.alreadyherellc.com health endpoint when runtime API is active
[ ] Verify https://status.alreadyherellc.com
[ ] Keep n8n private until auth/access controls are confirmed
[ ] Add uptime checks
[ ] Confirm no paid adapters enabled
```
