---
title: "Remote Access"
description: "Access your Nova instance from anywhere via Cloudflare Tunnel or Tailscale."
---

Nova includes built-in support for remote access through two methods: **Cloudflare Tunnel** for public internet access, and **Tailscale** for private mesh networking. Both are configured through a guided wizard in the Dashboard's Remote Access page.

## Cloudflare Tunnel

Cloudflare Tunnel creates a secure, outbound-only connection from your Nova instance to Cloudflare's network, making Nova accessible via a custom domain without opening any ports on your firewall.

### What it provisions

The Dashboard wizard handles the entire setup:

1. **Verifies your API token** -- validates the token has the required permissions
2. **Selects account and zone** -- choose which Cloudflare account and domain to use
3. **Creates a tunnel** -- provisions a named Cloudflare Tunnel (e.g., `nova-<subdomain>`)
4. **Configures routing** -- sets up the tunnel to route traffic to Nova's services
5. **Creates DNS record** -- adds a CNAME record pointing `<subdomain>.<domain>` to the tunnel
6. **Saves credentials** -- stores the tunnel token in Nova's `.env` file
7. **Starts the container** -- launches the `cloudflared` container via Docker Compose profiles

### Prerequisites

- A Cloudflare account with at least one domain (zone)
- A Cloudflare API token with these permissions:
  - `Account: Cloudflare Tunnel: Edit`
  - `Zone: DNS: Edit`

Create a token at [dash.cloudflare.com/profile/api-tokens](https://dash.cloudflare.com/profile/api-tokens).

### Setup

1. Navigate to **Remote Access** in the Dashboard sidebar
2. Select the **Cloudflare Tunnel** tab
3. Enter your Cloudflare API token and click **Verify & Continue**
4. Select your account and zone (domain)
5. Choose a subdomain (e.g., `nova` for `nova.yourdomain.com`)
6. Click **Create Tunnel**

The wizard provisions everything automatically. Once complete, Nova is accessible at `https://<subdomain>.<domain>`.

### Disconnecting

Click **Disconnect Tunnel** on the Remote Access page. This stops the `cloudflared` container and removes the tunnel token from `.env`.

## Tailscale

Tailscale connects Nova to your personal tailnet using WireGuard-based mesh networking. Your Nova instance becomes accessible from any device on your tailnet via MagicDNS.

### What it provisions

1. **Creates an auth key** -- uses the Tailscale API to generate a pre-authorized, reusable auth key
2. **Saves the key** -- stores `TAILSCALE_AUTHKEY` in Nova's `.env` file
3. **Starts the container** -- launches the Tailscale container via Docker Compose profiles

### Prerequisites

- A Tailscale account
- A Tailscale API key with permission to create auth keys (create at [login.tailscale.com/admin/settings/keys](https://login.tailscale.com/admin/settings/keys))

### Setup

1. Navigate to **Remote Access** in the Dashboard sidebar
2. Select the **Tailscale** tab
3. Enter your Tailscale API key
4. Click **Connect to Tailnet**

Once connected, Nova is available on your tailnet as `nova` via MagicDNS.

### Disconnecting

Click **Disconnect Tailscale** on the Remote Access page. This stops the Tailscale container and removes the auth key from `.env`.

## Privacy note

Both wizards run entirely in the browser. API tokens are used client-side to call the Cloudflare or Tailscale APIs directly -- they are never sent to Nova's backend. Only the resulting credentials (tunnel token or auth key) are stored in Nova's `.env` file.

## Technical details

Both remote access methods use Docker Compose profiles managed by the [Recovery Service](/services/recovery/). The profiles are:

| Profile | Container | Purpose |
|---------|-----------|---------|
| `cloudflare-tunnel` | `cloudflared` | Runs the Cloudflare Tunnel daemon |
| `tailscale` | `tailscale` | Runs the Tailscale client |

These containers are only started when explicitly enabled through the wizard or by manually adding the profile to `COMPOSE_PROFILES` in your `.env` file.
