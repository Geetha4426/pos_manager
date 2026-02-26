# Geo-Block Bypass Setup

Polymarket blocks CLOB API (buy/sell/orders) from certain regions (US, India, etc.).  
Your **private key never leaves your bot** — only the already-signed requests get relayed.

## Option 1: Cloudflare Workers (RECOMMENDED — Free Forever)

**100,000 requests/day** on Cloudflare's free plan. No credit card. Deploys globally.

### Steps

1. **Create Cloudflare account** → https://dash.cloudflare.com/sign-up

2. **Install Wrangler CLI** (Cloudflare's deployment tool):
   ```bash
   npm install -g wrangler
   ```

3. **Login to Cloudflare**:
   ```bash
   wrangler login
   ```

4. **Deploy the relay**:
   ```bash
   cd relay/
   wrangler deploy
   ```
   Output: `Published poly-relay (https://poly-relay.<your-subdomain>.workers.dev)`

5. **(Optional) Add security token**:
   ```bash
   wrangler secret put AUTH_TOKEN
   # Enter a strong random string when prompted
   ```

6. **Configure your bot** — add to your `.env` file:
   ```env
   CLOB_RELAY_URL=https://poly-relay.<your-subdomain>.workers.dev
   CLOB_RELAY_AUTH_TOKEN=your_secret_token_here  # Only if you set AUTH_TOKEN above
   ```

7. **Redeploy your bot** on Railway. Done!

### How it works
```
Your Bot (Railway/US)
  ↓  (signed order)
Cloudflare Worker (global edge, non-US IP)
  ↓  (forwarded request)
clob.polymarket.com
  ↓  (response)
Cloudflare Worker
  ↓
Your Bot
```

---

## Option 2: Oracle Cloud Free VPS (Backup — Also Free Forever)

Oracle Cloud offers **Always Free** VMs in Singapore, Tokyo, Mumbai, etc.

### Steps

1. **Create Oracle Cloud account** → https://cloud.oracle.com  
   (Free tier, no charges ever for Always Free resources)

2. **Create a VM** — choose region: Singapore or Tokyo  
   Shape: VM.Standard.E2.1.Micro (Always Free)

3. **SSH into your VM** and set up:
   ```bash
   sudo apt update && sudo apt install python3-pip -y
   pip3 install flask requests gunicorn
   
   # Copy relay_server.py to your VM
   scp relay/relay_server.py user@your-vm-ip:~/
   
   # Run the relay
   cd ~ && gunicorn relay_server:app -b 0.0.0.0:8080 --daemon
   ```

4. **Open port 8080** in Oracle Cloud security rules (or use 443 with nginx + Let's Encrypt).

5. **Configure your bot** — add to `.env`:
   ```env
   CLOB_RELAY_URL=http://your-vm-ip:8080
   ```

---

## FAQ

**Q: Is my private key safe?**  
A: Yes. `py-clob-client` signs orders *locally* on your bot. The relay only sees the already-signed HTTP request (same as what would go to Polymarket directly). Your private key never touches the relay.

**Q: Will Polymarket detect this?**  
A: The relay is just an HTTP forwarder. Polymarket sees a request from Cloudflare's IP (which serves millions of websites). This is no different from using Cloudflare-proxied websites.

**Q: 100,000 requests/day — is that enough?**  
A: Each buy/sell is ~2-3 CLOB requests. Even trading 1000+ times a day, you'll use <5% of the free quota. Read-only calls (Gamma API) still go direct.

**Q: What about the Gamma API (search/prices)?**  
A: Gamma API is read-only and is NOT geo-blocked. Only CLOB API (order execution) is blocked. The relay is only for CLOB calls.

**Q: Which Cloudflare region will be used?**  
A: Cloudflare Workers run on 300+ edge locations globally. The request will egress from a non-US datacenter automatically.
