[README.md](https://github.com/user-attachments/files/34598222/README.md)
# Tech-Price-Error# Tech-Price-Error

A free, RSS-based discovery scanner for possible technology pricing mistakes and unusually large discounts.

## What it scans

- **PC components:** GPUs, CPUs, RAM, SSDs, motherboards, power supplies and peripherals
- **Computers:** gaming desktops, laptops, mini PCs and workstations
- **Displays:** monitors, OLED/QLED TVs and projectors
- **Consumer electronics:** phones, tablets, wearables, audio and cameras

The first version reads public RSS feeds from Slickdeals, selected Reddit deal communities and Google News searches. It flags strong pricing-error wording and very large explicit discount claims.

**Important:** These are leads, not confirmed pricing errors. The scanner does not have comprehensive retailer price-history access and cannot guarantee that a retailer will honor a price. Verify the exact model, seller, condition, shipping, stock and checkout price on the retailer's own page.

## Setup

1. Open **Settings → Secrets and variables → Actions**.
2. Add a repository secret named `DISCORD_WEBHOOK_URL`.
3. Paste the newly regenerated Discord webhook URL as its value. Never put the URL in source code or commit it to the repository.
4. Open **Actions → Tech Price Error Scanner** and select **Run workflow** for the first test.
5. Check the workflow log and your Discord channel.

## Schedule

GitHub Actions uses UTC. The configured cron schedule (`0 0,4,14,19 * * *`) corresponds to 8 AM, 1 PM, 6 PM and 10 PM Central during **Central Standard Time (CST)**. During **Central Daylight Time (CDT)**, each run occurs one hour later. Update the UTC hours seasonally if you need the exact same local clock times year-round.

## Free-tier notes

The scanner uses free public feeds and GitHub Actions. Feed availability, access rules and rate limits can change. Some retailer pages block automated access, so this starter version focuses on discovering leads rather than claiming comprehensive live price verification.
