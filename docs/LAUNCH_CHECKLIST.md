# Launch Checklist

The system is not live-ready until all pass:

- CI passes
- lint passes
- typecheck passes
- tests pass
- security scan passes
- no secrets in repo
- no paid adapters enabled
- no-spend policy active
- approval gate active
- audit log active
- backups tested
- restore tested
- uptime monitor active
- HTTPS active
- firewall active
- mobile smoke test passes
- SEO metadata present
- sitemap present
- rollback documented
- placeholder scan passes


## Domain / DNS

- [ ] `alreadyherellc.com` DNS points to OCI public IP.
- [ ] `www`, `app`, `api`, and `status` records exist.
- [ ] Caddy is running and HTTPS certificates are issued.
- [ ] `n8n` is not public unless authentication/access control is active.
- [ ] Only ports 22, 80, and 443 are publicly open.
