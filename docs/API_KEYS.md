# Getting your API keys

Every key goes into GitHub: open the repo → **Settings → Secrets and variables → Actions →
Secrets → New repository secret**. Use the exact names in **bold**. Add only the sources you
have; the tool skips any source whose keys are missing.

When at least one data source is set up, delete the repository variable `VDF_DEMO` (Settings →
Secrets and variables → Actions → Variables) so the app switches from demo data to real data.

| Source | Cost | What it gives you | Priority |
|---|---|---|---|
| eBay | free | Live listings worldwide | ★★★ start here |
| Cardmarket | free | EU listings (main source) | ★★★ |
| PriceCharting | paid subscription | PSA 9/10 market values | ★★ makes valuations reliable |
| Telegram | free | Deal alerts on your phone | ★★★ |
| Discord | free | Alternative to Telegram | optional |

---

## 1. eBay: `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET`

1. Go to **https://developer.ebay.com** and click **Register**. Use your normal eBay account and
   pick an individual account.
2. Wait for the confirmation email. Approval is usually quick but can take up to a day.
3. Open **Application Keys** (in the account menu at the top right).
4. Enter an application title, for example `psa-deal-finder`, and create a **Production** keyset.
5. eBay first asks about **Marketplace Account Deletion notifications**. This tool doesn't store
   eBay user data, so choose the option to **apply for an exemption** (the reason is that you
   don't persist eBay user data). Your production keys only become active after this step.
6. Copy the values from the Production keyset:
   - **App ID (Client ID)** → secret **`EBAY_CLIENT_ID`**
   - **Cert ID (Client Secret)** → secret **`EBAY_CLIENT_SECRET`**

Don't use the Sandbox keys, because Sandbox only contains fake test listings.

eBay sold prices come from the *Marketplace Insights* API, which eBay only grants on request,
mostly to businesses. You don't need it; the tool uses PriceCharting and CSV imports for sold
prices instead.

## 2. Cardmarket: `MKM_APP_TOKEN`, `MKM_APP_SECRET`, `MKM_ACCESS_TOKEN`, `MKM_ACCESS_SECRET`

1. Log in at **https://www.cardmarket.com**.
2. Go to **My Account → Settings → API** (or open
   `https://www.cardmarket.com/en/Pokemon/Account/API`).
3. Create a **Dedicated App**. Any name works. You will get four values:
   - App Token → **`MKM_APP_TOKEN`**
   - App Secret → **`MKM_APP_SECRET`**
   - Access Token → **`MKM_ACCESS_TOKEN`**
   - Access Token Secret → **`MKM_ACCESS_SECRET`**

Cardmarket has limited API access in recent years. If you can't find the API page, or it says
API access isn't available for your account, email Cardmarket support and ask for a "Dedicated
App" for personal price tracking. Until then, eBay and PriceCharting still work, and you can
add Cardmarket listings by hand through `imports/` (see the README).

## 3. PriceCharting: `PRICECHARTING_TOKEN`

1. Create an account at **https://www.pricecharting.com**.
2. Subscribe to the plan that includes **API access** (the top tier, currently called
   "Legendary"; check the site for the current price).
3. Open **https://www.pricecharting.com/api-documentation** while logged in. Your personal
   40-character token is shown there.
4. Save it as **`PRICECHARTING_TOKEN`**.

This is the most reliable source for "what does a PSA 9 / PSA 10 sell for". Without it,
valuations depend on sold data you import yourself.

## 4. Telegram alerts: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`

1. In Telegram, open a chat with **@BotFather** (it has the blue verified tick).
2. Send `/newbot`, then choose a display name and a username ending in `bot`, for example
   `my_psa_deals_bot`.
3. BotFather replies with a token like `7123456789:AAH...`. Save it as **`TELEGRAM_BOT_TOKEN`**.
4. Open a chat with **your new bot** and send it any message, for example `hi`. The bot can only
   message you after you have messaged it first.
5. Find your chat ID. Either:
   - open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser and copy the number
     after `"chat":{"id":`, or
   - message **@userinfobot**, which replies with your ID.
6. Save it as **`TELEGRAM_CHAT_ID`**.

## 5. Discord alerts (optional): `DISCORD_WEBHOOK`

In your Discord server, open **Server Settings → Integrations → Webhooks → New Webhook**, pick
a channel and click **Copy Webhook URL**. Save the URL as **`DISCORD_WEBHOOK`**.

---

## Check that it works

1. On GitHub, open **Actions → Scan → Run workflow**. Leave "demo" unticked.
2. Open the run and look at the **Scan** step. Each source reports how many listings it found.
   - A line like `source ebay disabled or missing credentials` means that secret's name is
     wrong or the secret is empty.
   - `eBay token request failed: 401` means the client ID or secret is wrong, or the
     deletion-notification exemption from step 1.5 hasn't been approved yet.
   - `Cardmarket auth failed` means at least one of the four tokens is wrong.
3. Open your app: https://datatraingithub.github.io/vintage-pokemon-psa-deal-finder/

Keep these keys private. Don't paste them into issues, chats or files in the repo; GitHub
Secrets is the only place they belong.
