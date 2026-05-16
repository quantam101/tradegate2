# Domain Deployment Plan

## Environment Variable Configuration

This project uses the `SITE_DOMAIN` environment variable for all domain references.
Set it in your `.env` file before deploying:

```bash
# .env
SITE_DOMAIN=yourdomain.com
ACME_EMAIL=admin@yourdomain.com
```

The Caddyfile uses `{$SITE_DOMAIN}` and docker-compose.yml uses `${SITE_DOMAIN}`
to resolve the domain at runtime. No code changes are needed per deployment.

## Production Domain

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
CNAME  www      <your-domain>
CNAME  app      <your-domain>
CNAME  api      <your-domain>
CNAME  status   <your-domain>
CNAME  docs     <your-domain>
```

Do not expose `n8n.<your-domain>` until authentication and access controls are confirmed.

## Subdomain Map

```txt
<domain>              Public website / landing page
www.<domain>          Public alias
app.<domain>          GMAOS command center
api.<domain>          EAOS runtime API
status.<domain>       Uptime/status page
n8n.<domain>          Automation server, protected only
docs.<domain>         Documentation / SOP portal, optional
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
caddy/Caddyfile          Uses {$SITE_DOMAIN} env var
docs/DOMAIN_SETUP.md     This file
.env.example             Domain variables template
docker-compose.yml       Uses ${SITE_DOMAIN} env var
```

## Domain Launch Checklist

```txt
[ ] Confirm domain registrar access
[ ] Decide registrar DNS or Cloudflare Free DNS
[ ] Create OCI Always Free A1 instance
[ ] Record OCI public IP
[ ] Add DNS records (A + CNAMEs)
[ ] Copy .env.example to .env on server
[ ] Set SITE_DOMAIN=yourdomain.com in .env
[ ] Set ACME_EMAIL=admin@yourdomain.com in .env
[ ] Replace server-side passwords in .env
[ ] Run docker compose up -d --build
[ ] Verify https://<your-domain>
[ ] Verify https://app.<your-domain>
[ ] Verify https://api.<your-domain> health endpoint
[ ] Verify https://status.<your-domain>
[ ] Keep n8n private until auth/access controls are confirmed
[ ] Add uptime checks
[ ] Confirm no paid adapters enabled
```
