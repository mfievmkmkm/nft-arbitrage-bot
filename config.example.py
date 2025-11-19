"""
NFT Gift Bot Configuration - Example Template

Complete configuration template with detailed instructions for setting up
the NFT arbitrage trading bot.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
QUICK START GUIDE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Copy this file:
   cp config.example.py config.py

2. Get your credentials:
   • Telegram Bot Token: Talk to @BotFather on Telegram
   • Telegram Chat ID: Talk to @userinfobot on Telegram
   • Portals Auth Token: Follow instructions below

3. Edit config.py and fill in your credentials

4. Test your configuration:
   python -c "import config; print('✓ Config loaded')"

5. Run the bot:
   python main.py

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

For detailed setup guide, see: README.md
For troubleshooting, see: docs/TROUBLESHOOTING.md

Repository: https://github.com/Elchin-bit/nft-arbitrage-bot
"""

# ============================================================================
# 🤖 TELEGRAM BOT CONFIGURATION (REQUIRED)
# ============================================================================

# ─────────────────────────────────────────────────────────────────────────
# Telegram Bot Token
# ─────────────────────────────────────────────────────────────────────────
# This token identifies your bot on Telegram's servers.
#
# How to get:
#   1. Open Telegram and search for @BotFather
#   2. Send /newbot command
#   3. Follow instructions to create your bot
#   4. Copy the token provided by BotFather
#
# Format example:
#   "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz"
#
TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"

# ─────────────────────────────────────────────────────────────────────────
# Your Telegram User ID (Chat ID)
# ─────────────────────────────────────────────────────────────────────────
# This is YOUR personal Telegram user ID where notifications will be sent.
#
# How to get:
#   1. Open Telegram and search for @userinfobot
#   2. Start the bot
#   3. Copy your ID number (e.g., 123456789)
#
# Note: This is a NUMBER, not your @username!
#
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID_HERE"


# ============================================================================
# 🎁 PORTALS.GIFT API CONFIGURATION (REQUIRED)
# ============================================================================

# ─────────────────────────────────────────────────────────────────────────
# Portals Market Authentication Token
# ─────────────────────────────────────────────────────────────────────────
# This token authenticates your bot with Portals.gift marketplace API.
#
# How to get (Browser Method):
#   1. Open https://portals.gift in your browser
#   2. Log in with your Telegram account
#   3. Open Browser DevTools:
#      • Chrome/Edge: Press F12 or Ctrl+Shift+I
#      • Firefox: Press F12 or Ctrl+Shift+I
#      • Safari: Enable Developer Menu, then Cmd+Opt+I
#   4. Go to "Network" tab
#   5. Refresh the page
#   6. Look for any request to portals.gift API
#      (e.g., "search", "my-portal-gifts", "giftsFloors")
#   7. Click on the request
#   8. Find "Request Headers" section
#   9. Copy the entire "Authorization" header value
#      (starts with "tma query_id=...")
#
# Format example:
#   "tma query_id=AAH...&user=%7B%22id%22%3A123...&hash=abc123..."
#
# Token expires: Usually valid for several hours to days
# If bot stops working: Generate new token using steps above
#
PORTALS_AUTH_TOKEN = "YOUR_PORTALS_AUTH_TOKEN_HERE"


# ============================================================================
# 💰 TRADING STRATEGY PARAMETERS
# ============================================================================

# ─────────────────────────────────────────────────────────────────────────
# Profit Threshold
# ─────────────────────────────────────────────────────────────────────────
# Minimum net profit percentage (after fees) to trigger alerts.
#
# Lower values:
#   ✓ More opportunities found
#   ✗ Lower profit margins
#   ✗ More notifications
#
# Higher values:
#   ✓ Higher profit margins
#   ✓ Fewer notifications
#   ✗ Fewer opportunities
#
# Recommended: 15-25%
# Conservative: 30-50%
# Aggressive: 10-20%
#
MIN_PROFIT_PERCENT = 20

# ─────────────────────────────────────────────────────────────────────────
# Price Filter
# ─────────────────────────────────────────────────────────────────────────
# Maximum NFT price to consider (in TON).
# NFTs more expensive than this will be ignored.
#
# Lower values:
#   ✓ Less capital required
#   ✓ Lower risk per trade
#   ✗ Fewer opportunities
#
# Higher values:
#   ✓ More opportunities
#   ✗ More capital required
#   ✗ Higher risk per trade
#
# Recommended: 20-50 TON (based on your budget)
# Budget trading: 10-20 TON
# High volume: 50-100 TON
#
MAX_PRICE_TON = 40

# ─────────────────────────────────────────────────────────────────────────
# Risk Management
# ─────────────────────────────────────────────────────────────────────────
# Maximum risk score (0-100) to allow.
# Higher risk = less reliable opportunities.
#
# Lower values:
#   ✓ Safer trades
#   ✓ More reliable data
#   ✗ Fewer opportunities
#
# Higher values:
#   ✓ More opportunities
#   ✗ Less reliable
#   ✗ Higher risk
#
# Recommended: 30-50
# Conservative: 20-30
# Aggressive: 50-70
#
MAX_RISK_SCORE = 50


# ============================================================================
# 📊 MARKET ANALYSIS PARAMETERS
# ============================================================================

# ─────────────────────────────────────────────────────────────────────────
# Sales History Window
# ─────────────────────────────────────────────────────────────────────────
# Number of days of historical sales data to analyze.
#
# More days:
#   ✓ More data points
#   ✗ May include outdated prices
#   ✗ Slower market trend detection
#
# Fewer days:
#   ✓ More current data
#   ✓ Faster trend detection
#   ✗ Less data points
#
# Recommended: 30-90 days
# Fast markets: 14-30 days
# Stable markets: 60-90 days
#
SALES_HISTORY_DAYS = 60

# ─────────────────────────────────────────────────────────────────────────
# Minimum Sales Required
# ─────────────────────────────────────────────────────────────────────────
# Minimum number of historical sales needed for analysis.
# Ensures reliable price data.
#
# Lower values:
#   ✓ More opportunities (including rare NFTs)
#   ✗ Less reliable data
#
# Higher values:
#   ✓ More reliable data
#   ✗ Fewer opportunities
#   ✗ Misses rare NFTs
#
# Recommended: 3-5 sales
# Conservative: 5-10 sales
# Aggressive: 2-3 sales
#
MIN_SALES_REQUIRED = 3

# ─────────────────────────────────────────────────────────────────────────
# Competition Filter
# ─────────────────────────────────────────────────────────────────────────
# Maximum number of cheaper similar NFTs allowed.
# If more cheaper NFTs exist, opportunity is rejected.
#
# Lower values:
#   ✓ Only bottom-priced opportunities
#   ✓ Best arbitrage potential
#   ✗ Fewer opportunities
#
# Higher values:
#   ✓ More opportunities
#   ✗ More competition
#   ✗ Harder to flip
#
# Recommended: 2-5 NFTs
# Strict: 0-2 NFTs
# Relaxed: 5-10 NFTs
#
MAX_CHEAPER_NFTS = 2


# ============================================================================
# ⚡ PERFORMANCE & RATE LIMITING
# ============================================================================

# ─────────────────────────────────────────────────────────────────────────
# Scan Interval
# ─────────────────────────────────────────────────────────────────────────
# Seconds between marketplace scans.
#
# Lower values:
#   ✓ Faster opportunity detection
#   ✗ Higher API load
#   ✗ More likely to hit rate limits
#
# Higher values:
#   ✓ Lower API load
#   ✗ May miss fast-moving opportunities
#
# Recommended: 3-10 seconds
# Aggressive: 1-3 seconds (watch for rate limits!)
# Conservative: 10-30 seconds
#
SCAN_INTERVAL_SECONDS = 5

# ─────────────────────────────────────────────────────────────────────────
# Scan Batch Size
# ─────────────────────────────────────────────────────────────────────────
# Maximum number of NFT listings to fetch per scan.
#
# Lower values:
#   ✓ Faster scans
#   ✗ May miss opportunities
#
# Higher values:
#   ✓ More comprehensive
#   ✗ Slower scans
#   ✗ More API load
#
# Recommended: 100-500 NFTs
# Fast: 50-100 NFTs
# Comprehensive: 500-1000 NFTs
#
SCAN_LIMIT = 500

# ─────────────────────────────────────────────────────────────────────────
# Parallel Analysis
# ─────────────────────────────────────────────────────────────────────────
# Number of NFTs to analyze concurrently.
#
# Lower values:
#   ✓ Lower API load
#   ✗ Slower analysis
#
# Higher values:
#   ✓ Faster analysis
#   ✗ May trigger rate limiting (HTTP 429)
#
# Recommended: 3-5 parallel
# Conservative: 1-2 parallel
# Aggressive: 5-10 parallel (monitor for errors!)
#
MAX_PARALLEL_ANALYSES = 3

# ─────────────────────────────────────────────────────────────────────────
# Analysis Stagger Delay
# ─────────────────────────────────────────────────────────────────────────
# Seconds to wait between starting each analysis task.
# Prevents burst API requests that trigger rate limits.
#
# Lower values:
#   ✓ Faster batch processing
#   ✗ More burst load
#
# Higher values:
#   ✓ Smoother API load
#   ✗ Slower batch processing
#
# Recommended: 0.3-0.5 seconds
#
ANALYSIS_START_DELAY = 0.5

# ─────────────────────────────────────────────────────────────────────────
# Similar NFT Search Limit
# ─────────────────────────────────────────────────────────────────────────
# Stop searching after finding this many similar NFTs.
# Used for floor price and competition analysis.
#
# Lower values:
#   ✓ Faster analysis
#   ✗ Less accurate floor price
#
# Higher values:
#   ✓ More accurate analysis
#   ✗ Slower, more API calls
#
# Recommended: 30-100 NFTs
# Fast: 20-50 NFTs
# Accurate: 100-200 NFTs
#
SIMILAR_NFT_TARGET = 50


# ============================================================================
# 💾 DATABASE CONFIGURATION
# ============================================================================

# ─────────────────────────────────────────────────────────────────────────
# Database File Path
# ─────────────────────────────────────────────────────────────────────────
# SQLite database file for storing processed NFTs and analyses.
#
# Default: "nft_gifts.db" (in current directory)
# Production: "data/nft_gifts.db" or absolute path
#
DATABASE_PATH = "nft_gifts.db"


# ============================================================================
# 🔧 ADVANCED SETTINGS
# ============================================================================
# ⚠️ Don't change these unless you know what you're doing!

# Maximum absolute scan limit (safety limit)
MAX_SCAN_LIMIT = 10000

# Collection data cache TTL (seconds)
COLLECTION_CACHE_TTL = 300

# API request rate limiting delay (seconds)
# Minimum time between API requests to same endpoint
API_REQUEST_DELAY = 0.5


# ============================================================================
# 📝 VALIDATION & SANITY CHECKS
# ============================================================================

def validate_config():
    """
    Validate configuration values and provide helpful error messages.

    Raises:
        ValueError: If configuration is invalid
    """
    errors = []

    # Required credentials
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        errors.append("❌ TELEGRAM_BOT_TOKEN not configured! Get token from @BotFather")

    if TELEGRAM_CHAT_ID == "YOUR_CHAT_ID_HERE":
        errors.append("❌ TELEGRAM_CHAT_ID not configured! Get ID from @userinfobot")

    if PORTALS_AUTH_TOKEN == "YOUR_PORTALS_AUTH_TOKEN_HERE":
        errors.append("❌ PORTALS_AUTH_TOKEN not configured! See instructions in config.py")

    # Sanity checks
    if MIN_PROFIT_PERCENT < 0:
        errors.append("❌ MIN_PROFIT_PERCENT must be positive")

    if MIN_PROFIT_PERCENT < 10:
        errors.append("⚠️  MIN_PROFIT_PERCENT < 10% may generate too many false positives")

    if MAX_PRICE_TON <= 0:
        errors.append("❌ MAX_PRICE_TON must be positive")

    if SCAN_INTERVAL_SECONDS < 1:
        errors.append("⚠️  SCAN_INTERVAL_SECONDS < 1 may trigger rate limiting")

    if MAX_PARALLEL_ANALYSES > 10:
        errors.append("⚠️  MAX_PARALLEL_ANALYSES > 10 may trigger rate limiting")

    if SCAN_LIMIT > MAX_SCAN_LIMIT:
        errors.append(f"❌ SCAN_LIMIT exceeds MAX_SCAN_LIMIT ({MAX_SCAN_LIMIT})")

    if errors:
        print("\n" + "="*60)
        print("🚨 CONFIGURATION ERRORS")
        print("="*60)
        for error in errors:
            print(f"  {error}")
        print("="*60)
        print("\nPlease fix these errors before running the bot.")
        print("See config.example.py for instructions.\n")
        raise ValueError("Invalid configuration")

    # Success message
    print("\n" + "="*60)
    print("✅ CONFIGURATION VALIDATED")
    print("="*60)
    print(f"  • Telegram Bot: {TELEGRAM_BOT_TOKEN[:10]}...")
    print(f"  • Chat ID: {TELEGRAM_CHAT_ID}")
    print(f"  • Min Profit: {MIN_PROFIT_PERCENT}%")
    print(f"  • Max Price: {MAX_PRICE_TON} TON")
    print(f"  • Scan Interval: {SCAN_INTERVAL_SECONDS}s")
    print("="*60 + "\n")


# Auto-validate when imported
if __name__ != "__main__":
    try:
        validate_config()
    except ValueError:
        pass  # Don't exit on import, let main.py handle it
