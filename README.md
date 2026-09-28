# Disposable Odoo 19 JSON-2 QA

Generic synthetic QA harness. It contains no product source, customer data or stored credentials.

Manual dispatch only, standard `ubuntu-24.04` GitHub-hosted runner in this public repository. No larger runners, artifacts, caches, packages or paid services. Official `odoo:19.0`, PostgreSQL 16 and Cloudflare's free Quick Tunnel.

Supply an RSA-4096 public key (base64 PEM) and a unique `NWQA-YYYYMMDD-HHMM` prefix. Keep the matching private key on the initiating PC. Credentials are randomly generated at runtime, masked defensively, and transferred only as RSA-OAEP-SHA256 ciphertext. No plaintext credentials are emitted into logs or artifacts. The ciphertext cannot authenticate to Odoo.

Odoo has no demo data. All test records carry the run prefix. Database management is disabled, PostgreSQL is not published, and Odoo binds only to the runner loopback. JSON-2 requires a newly generated API key with a two-hour expiry. The tunnel is temporary, with no named tunnel, account token or custom domain.

The lease lasts at most 100 minutes after readiness. Cancel the workflow after QA. An always-running cleanup step removes this run's containers, anonymous volumes and RAM-backed credential directory; the hosted runner is then discarded. Cleanup and negative endpoint checks must be recorded by the caller. There is no persistent QA deployment.

Cost sources: [GitHub standard runners in public repositories](https://docs.github.com/en/billing/concepts/product-billing/github-actions), [Cloudflare Quick Tunnels](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/).
