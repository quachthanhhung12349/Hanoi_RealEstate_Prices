# Phase 1b Plan: Deploy + Background Scraping

## Context

Phase 1 (scraping, SQLite storage, Streamlit dashboard) is mostly done. Phase 1b means two things:
1. **Automated background scraping** — scrapers run on a schedule without manual intervention
2. **Deployed dashboard** — the Streamlit app is accessible outside localhost

The constraint is minimum financial cost. The key technical challenges are:
- Selenium + Chrome is heavy (~1GB RAM), which rules out most free serverless platforms
- SQLite is file-based, so the dashboard and scraper must share the same disk
- The scraper already handles resumability — scheduling is a thin wrapper, not a rewrite

---

## Two Tiers (Cost vs. Reliability)

### Tier 0 — $0/month: Local machine + Cloudflare Tunnel

Keep everything on the current machine. Add automation and expose the dashboard publicly.

**Pros:** Literally free. No migration. SQLite stays where it is.  
**Cons:** Dashboard goes down when your PC is off. Less reliable for long scraping runs.

### Tier 1 — ~$4–6/month: Cheap VPS (Hetzner CX22)

Move project to a Hetzner CX22 (2 vCPU x86, 4GB RAM, 40GB SSD — €4.51/mo). Always on.

**Pros:** Reliable, always-on, ARM-free (avoids undetected_chromedriver ARM issues), SSH access.  
**Cons:** Small monthly cost, requires initial setup.

**Recommendation: Start with Tier 0 (local + Cloudflare Tunnel) unless you need it always-on. If yes → Hetzner CX22 is the cheapest reliable VPS.**

---

## Implementation Plan (applies to both tiers, paths differ slightly)

### 1. Scheduled Scraping via Cron

Add two cron jobs (no new code needed — just wraps existing scripts):

```
# Run discovery daily at 2am, up to 50 pages
0 2 * * * cd /path/to/project && PYTHONPATH=src python3 -m hanoi_real_estate.scrapers.discover_listings --max-pages 50 >> logs/discover.log 2>&1

# Run detail scraping daily at 3am (after discovery), process all queued
0 3 * * * cd /path/to/project && PYTHONPATH=src python3 -m hanoi_real_estate.scrapers.scrape_listing_details --limit 0 --max-workers 1 --batch-limit 10 >> logs/scrape_details.log 2>&1
```

- Uses `--limit 0` (process all queued), single worker to avoid detection
- Sequential (discover first, then details) using separate cron times
- Logs go to `logs/` (directory already exists in repo)
- No new Python code — pure cron scheduling

### 2. Dashboard as a Persistent Service (systemd)

Create a systemd user service to keep Streamlit running:

**File:** `~/.config/systemd/user/bds-dashboard.service`

```ini
[Unit]
Description=BDS Streamlit Dashboard
After=network.target

[Service]
WorkingDirectory=/path/to/project
Environment=PYTHONPATH=src
ExecStart=/usr/bin/streamlit run src/hanoi_real_estate/dashboard/app.py --server.port 8501 --server.headless true
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

Enable with: `systemctl --user enable --now bds-dashboard`

### 3. Dashboard Exposure

**Tier 0 (local):** Use Cloudflare Tunnel (free, no credit card needed):
```bash
# Install cloudflared, then:
cloudflared tunnel --url http://localhost:8501
# Gives a free *.trycloudflare.com URL (ephemeral, no account needed)
# For a stable URL: create a free Cloudflare account + tunnel
```

**Tier 1 (VPS):** Open port 8501 in firewall, or add Caddy as reverse proxy (free Let's Encrypt HTTPS):
```
# /etc/caddy/Caddyfile
bds.yourdomain.com {
    reverse_proxy localhost:8501
}
```
Caddy auto-manages HTTPS certs. Free domain via Cloudflare (free DNS) or `.duckdns.org` (free subdomain).

### 4. SQLite Backup (Optional but Recommended)

Add a weekly backup cron — one liner, no new code:

```
0 4 * * 0 cp /path/to/data/bds_live.sqlite3 /path/to/data/bds_live.bak.$(date +%Y%m%d).sqlite3
```

Or use `litestream` (free, open-source) to stream SQLite WAL to local/S3 — but S3 has cost. Local backup is free.

### 5. Log Rotation (Optional)

Add `logrotate` config to prevent logs growing unbounded:

```
/path/to/logs/*.log {
    weekly
    rotate 4
    compress
    missingok
    notifempty
}
```

---

## Files to Create/Modify

| File | Action | Purpose |
|------|---------|---------|
| `logs/.gitkeep` | Create | Ensure logs dir exists in repo |
| `scripts/cron_setup.sh` | Create | Installs cron jobs (documents the schedule) |
| `~/.config/systemd/user/bds-dashboard.service` | Create | Systemd service for dashboard |
| `README.md` | Update | Add Phase 1b deployment instructions |

No changes to scraper logic, database schema, or dashboard code — Phase 1b is purely operational.

---

## Cost Summary

| Component | Tier 0 | Tier 1 |
|-----------|--------|--------|
| Server | $0 (local PC) | ~$4.51/mo (Hetzner CX22) |
| Dashboard URL | Free (trycloudflare.com ephemeral) or free Cloudflare account | Free (Caddy + DuckDNS) |
| Database | $0 (local SQLite) | $0 (SQLite on VPS disk) |
| Scheduling | $0 (cron) | $0 (cron) |
| Backups | $0 (local copy) | $0 (local copy) |
| **Total** | **$0** | **~$4.51/mo** |

---

## Verification

1. Trigger cron job manually: run the discover + scrape commands and confirm new rows appear in SQLite
2. Check systemd service status: `systemctl --user status bds-dashboard`
3. Access dashboard via tunnel/VPS URL in a browser
4. Wait 24h and verify logs show automated runs completed
5. Check `listing` table for new `done` rows from the overnight scrape
