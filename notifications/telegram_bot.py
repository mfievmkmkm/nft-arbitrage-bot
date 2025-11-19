"""
Telegram Bot Manager - NFT Profit Opportunity Notifications

Provides real-time Telegram notifications for profitable NFT opportunities
with rich formatting, interactive buttons, and comprehensive error handling.

Features:
---------
- Formatted profit alerts with NFT details and price analysis
- Interactive inline keyboards (Open on Portals, Copy Mint #)
- Sales history summaries and confidence scores
- Admin error notifications for monitoring
- Status updates for bot operations
- Callback handlers for user interactions
- Graceful resource cleanup

Message Format:
---------------
Each opportunity alert includes:
- NFT name and attributes (model, backdrop, symbol)
- Buy price and target price (TON and USD)
- Net profit and ROI percentage
- Strategy used and confidence score
- Sales history summary (if available)
- Interactive action buttons

Example Notification:
---------------------
🎯 PROFIT OPPORTUNITY

📦 Delicious Cake
✨ Premium Chocolate Mousse + Midnight Blue

💰 Price: 5.00 TON ($27.50)
🎯 Target: 7.50 TON ($41.25)
💎 Net Profit: 2.13 TON ($11.69)
📈 ROI: 42.5%
🔥 Strategy: Premium backdrop
⭐ Confidence: 85%
📊 Sales: 5 total, 3 recent (avg: 6.80 TON)

ID: abc123...

[🔗 Open on Portals] [📋 Copy Mint #]

Dependencies:
-------------
- aiogram: Telegram Bot API wrapper
- config: Bot token and chat ID configuration
- database: Gift and ProfitAnalysis models

Author: [Your Name]
Version: 2.2 (2025-11-19)
Repository: https://github.com/yourusername/nft-gift-bot
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Tuple

from aiogram import Bot, Dispatcher, Router
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.exceptions import TelegramAPIError

import config
from database import Gift, ProfitAnalysis

logger = logging.getLogger(__name__)


# ============================================================================
# TELEGRAM NOTIFIER
# ============================================================================

class TelegramNotifier:
    """
    Telegram notification manager for NFT arbitrage opportunities.

    Handles all Telegram bot operations including:
    - Sending formatted opportunity alerts
    - Processing user callback interactions
    - Delivering admin notifications (errors, status)
    - Managing bot lifecycle (polling, cleanup)

    Attributes:
        bot: Aiogram Bot instance for API calls
        user_id: Telegram chat ID for notifications
        dp: Aiogram Dispatcher for routing updates
        router: Aiogram Router for callback handling

    Example Usage:
        notifier = TelegramNotifier()
        await notifier.send_opportunity_alert(gift, analysis, ton_price)
        await notifier.start_polling()  # Start listening for callbacks
        await notifier.cleanup()  # On shutdown
    """

    def __init__(self):
        """
        Initialize Telegram bot with token and configure handlers.

        Raises:
            ValueError: If TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not configured
        """
        if not config.TELEGRAM_BOT_TOKEN:
            raise ValueError("TELEGRAM_BOT_TOKEN not configured in config.py")

        if not config.TELEGRAM_CHAT_ID:
            raise ValueError("TELEGRAM_CHAT_ID not configured in config.py")

        self.bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
        self.user_id = config.TELEGRAM_CHAT_ID
        self.dp = Dispatcher()
        self.router = Router()

        # Register callback query handlers
        self.router.callback_query.register(
            self.handle_copy_mint,
            lambda c: c.data and c.data.startswith("copy_mint")
        )
        self.dp.include_router(self.router)

        logger.info("=" * 60)
        logger.info("✅ TelegramNotifier initialized successfully")
        logger.info(f"  • Bot Token: {config.TELEGRAM_BOT_TOKEN[:10]}...")
        logger.info(f"  • Chat ID: {config.TELEGRAM_CHAT_ID}")
        logger.info("=" * 60)

    # ========================================================================
    # OPPORTUNITY ALERTS
    # ========================================================================

    async def send_opportunity_alert(
        self,
        gift: Gift,
        analysis: ProfitAnalysis,
        ton_usd: float,
        sales_history: Optional[List[Dict]] = None
    ) -> bool:
        """
        Send comprehensive profit opportunity notification to Telegram.

        Creates a richly formatted alert with:
        - NFT details (name, model, backdrop, symbol)
        - Price analysis (buy, target, profit in TON and USD)
        - ROI percentage and confidence score
        - Strategy used and risk assessment
        - Sales history summary (total, recent, average)
        - Interactive action buttons

        Args:
            gift: Gift object containing NFT metadata
            analysis: ProfitAnalysis with opportunity metrics
            ton_usd: Current TON/USD exchange rate
            sales_history: Optional list of historical sales with 'price' and 'date'

        Returns:
            True if notification sent successfully, False on error

        Example:
            success = await notifier.send_opportunity_alert(
                gift=my_nft,
                analysis=profit_analysis,
                ton_usd=5.50,
                sales_history=[{'price': 10.5, 'date': datetime.now()}, ...]
            )
        """
        try:
            # Extract NFT attributes
            model, backdrop, symbol = self._extract_attributes(gift.attributes)

            # Calculate USD equivalents
            buy_usd = gift.price * ton_usd
            target_usd = analysis.target_price * ton_usd
            profit_usd = analysis.profit_ton * ton_usd

            # Build sales history summary
            sales_info = ""
            if sales_history:
                sales_info = self._build_sales_info(sales_history)

            # Determine special type indicator (premium, monochrome, etc.)
            special_type = self._get_special_type_indicator(analysis.strategy)

            # Format comprehensive message
            message = self._format_opportunity_message(
                gift=gift,
                analysis=analysis,
                model=model,
                backdrop=backdrop,
                special_type=special_type,
                buy_usd=buy_usd,
                target_usd=target_usd,
                profit_usd=profit_usd,
                sales_info=sales_info
            )

            # Create interactive keyboard
            keyboard = self._create_opportunity_keyboard(gift)

            # Send to Telegram
            await self.bot.send_message(
                chat_id=self.user_id,
                text=message,
                parse_mode="HTML",
                reply_markup=keyboard,
                disable_web_page_preview=True  # Don't show preview for Portals link
            )

            logger.info(f"✅ Sent opportunity alert: {gift.name} #{gift.number}")
            return True

        except TelegramAPIError as e:
            logger.error(f"❌ Telegram API error sending notification: {e}")
            return False

        except Exception as e:
            logger.error(f"❌ Unexpected error sending notification: {e}", exc_info=True)
            return False

    def _extract_attributes(
        self,
        attributes: List[Dict]
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Extract model, backdrop, and symbol from attributes list.

        Args:
            attributes: List of dictionaries with 'type' and 'value' keys

        Returns:
            Tuple of (model, backdrop, symbol) - any can be None if missing

        Example:
            attributes = [
                {'type': 'model', 'value': 'Chocolate Mousse'},
                {'type': 'backdrop', 'value': 'Midnight Blue'},
                {'type': 'symbol', 'value': 'Heart'}
            ]
            model, backdrop, symbol = self._extract_attributes(attributes)
            # Returns: ('Chocolate Mousse', 'Midnight Blue', 'Heart')
        """
        model, backdrop, symbol = None, None, None

        for attr in attributes:
            attr_type = attr.get('type')
            value = attr.get('value')

            if attr_type == 'model':
                model = value
            elif attr_type == 'backdrop':
                backdrop = value
            elif attr_type == 'symbol':
                symbol = value

        return model, backdrop, symbol

    def _build_sales_info(self, sales_history: List[Dict]) -> str:
        """
        Build formatted sales history summary string.

        Calculates:
        - Total number of sales
        - Recent sales (last 14 days)
        - Average sale price

        Args:
            sales_history: List of sale dicts with 'price' (float) and 'date' (datetime)

        Returns:
            Formatted string with sales statistics, or empty string if no valid sales

        Example:
            sales = [
                {'price': 10.5, 'date': datetime(2025, 11, 18)},
                {'price': 12.0, 'date': datetime(2025, 11, 10)},
                {'price': 9.8, 'date': datetime(2025, 10, 25)}
            ]
            info = self._build_sales_info(sales)
            # Returns: "\n📊 Sales: 3 total, 2 recent (avg: 10.77 TON)"
        """
        if not sales_history:
            return ""

        try:
            # Calculate average price
            prices = [s['price'] for s in sales_history if 'price' in s]
            if not prices:
                return ""

            avg_price = sum(prices) / len(prices)

            # Count recent sales (last 14 days)
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=14)
            recent_count = 0

            for sale in sales_history:
                if 'date' not in sale:
                    continue

                sale_date = sale['date']
                if sale_date.tzinfo is None:
                    sale_date = sale_date.replace(tzinfo=timezone.utc)

                if sale_date >= cutoff_date:
                    recent_count += 1

            return (
                f"\n📊 <b>Sales:</b> {len(sales_history)} total, "
                f"{recent_count} recent (avg: {avg_price:.2f} TON)"
            )

        except Exception as e:
            logger.warning(f"⚠️ Error building sales info: {e}")
            return ""

    def _get_special_type_indicator(self, strategy: str) -> str:
        """
        Get special type indicator emoji based on strategy name.

        Maps strategy keywords to visual indicators:
        - "Premium" → ✨ Premium
        - "Monochrome" → 🎨 Monochrome
        - "SPECIAL NUMBER" → 🔢 Special #
        - Default → empty string

        Args:
            strategy: Strategy name from ProfitAnalysis

        Returns:
            Emoji indicator string, or empty if no special type

        Example:
            indicator = self._get_special_type_indicator("Premium backdrop")
            # Returns: "✨ Premium"
        """
        if "Premium" in strategy or "PREMIUM" in strategy:
            return "✨ Premium"
        elif "Monochrome" in strategy:
            return "🎨 Monochrome"
        elif "SPECIAL NUMBER" in strategy or "Special #" in strategy:
            return "🔢 Special #"
        return ""

    def _format_opportunity_message(
        self,
        gift: Gift,
        analysis: ProfitAnalysis,
        model: Optional[str],
        backdrop: Optional[str],
        special_type: str,
        buy_usd: float,
        target_usd: float,
        profit_usd: float,
        sales_info: str
    ) -> str:
        """
        Format comprehensive opportunity message with HTML markup.

        Creates a structured message with:
        - Header with emoji indicator
        - NFT details section
        - Price analysis section
        - Performance metrics section
        - NFT ID for reference

        Args:
            gift: Gift object with NFT data
            analysis: ProfitAnalysis with metrics
            model: NFT model name (or None)
            backdrop: NFT backdrop name (or None)
            special_type: Special type indicator string
            buy_usd: Buy price in USD
            target_usd: Target price in USD
            profit_usd: Profit in USD
            sales_info: Formatted sales history string

        Returns:
            HTML-formatted message string ready for Telegram

        Note:
            Uses HTML formatting supported by Telegram Bot API:
            - <b>text</b> for bold
            - <code>text</code> for monospace
            - <i>text</i> for italic
        """
        # Build attribute line
        model_str = model or "Unknown"
        backdrop_str = backdrop or "Unknown"

        if special_type:
            attributes = f"{special_type} {model_str} + {backdrop_str}"
        else:
            attributes = f"{model_str} + {backdrop_str}"

        # Format message with clear sections
        return f"""<b>🎯 PROFIT OPPORTUNITY</b>

<b>📦 {gift.name}</b>
{attributes}

💰 <b>Price:</b> {gift.price:.2f} TON (${buy_usd:.2f})
🎯 <b>Target:</b> {analysis.target_price:.2f} TON (${target_usd:.2f})
💎 <b>Net Profit:</b> {analysis.profit_ton:.2f} TON (${profit_usd:.2f})
📈 <b>ROI:</b> {analysis.profit_percent:.1f}%
🔥 <b>Strategy:</b> {analysis.strategy}
⭐ <b>Confidence:</b> {analysis.confidence:.0%}{sales_info}

<b>ID:</b> <code>{gift.id}</code>"""

    def _create_opportunity_keyboard(self, gift: Gift) -> InlineKeyboardMarkup:
        """
        Create inline keyboard with NFT action buttons.

        Buttons:
        1. Open on Portals - Deep link to NFT in Portals app
        2. Copy Mint # - Callback to show mint number

        Args:
            gift: Gift object with ID and mint number

        Returns:
            InlineKeyboardMarkup with action buttons

        Example:
            keyboard = self._create_opportunity_keyboard(gift)
            # Creates:
            # [🔗 Open on Portals]
            # [📋 Copy Mint #]
        """
        # Portals deep link format
        nft_url = f"https://t.me/portals/market?startapp=gift_{gift.id}_gkal9v"

        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="🔗 Open on Portals",
                url=nft_url
            )],
            [InlineKeyboardButton(
                text="📋 Copy Mint #",
                callback_data=f"copy_mint:{gift.number}"
            )]
        ])

    # ========================================================================
    # CALLBACK HANDLERS
    # ========================================================================

    async def handle_copy_mint(self, callback: CallbackQuery):
        """
        Handle "Copy Mint #" button callback.

        Shows an alert popup with the mint number when user presses
        the Copy Mint # button. The number can be copied from the alert.

        Args:
            callback: CallbackQuery from button press with data "copy_mint:<number>"

        Example Flow:
            User clicks [📋 Copy Mint #]
            → Bot shows alert: "Mint #12345"
            → User can copy number from alert
        """
        try:
            # Extract mint number from callback data
            mint_number = callback.data.split(":")[1]

            # Show alert with mint number
            await callback.answer(
                f"Mint #{mint_number}",
                show_alert=True  # Shows popup instead of toast
            )

            logger.debug(f"User copied mint #{mint_number}")

        except IndexError:
            logger.error(f"Invalid callback data format: {callback.data}")
            await callback.answer(
                "❌ Error: Invalid mint number",
                show_alert=True
            )

        except Exception as e:
            logger.error(f"❌ Error handling copy mint callback: {e}", exc_info=True)
            await callback.answer(
                "❌ Error copying mint number",
                show_alert=True
            )

    # ========================================================================
    # ADMIN NOTIFICATIONS
    # ========================================================================

    async def send_error_notification(self, error_message: str) -> bool:
        """
        Send error notification to admin for critical issues.

        Used for alerting admin about:
        - API failures
        - Database errors
        - Unexpected exceptions
        - System issues

        Args:
            error_message: Error description (will be shown in monospace)

        Returns:
            True if notification sent successfully, False otherwise

        Example:
            await notifier.send_error_notification(
                "Database connection failed: Timeout after 30s"
            )
        """
        try:
            message = (
                f"🚨 <b>Bot Error</b>\n\n"
                f"<code>{error_message}</code>\n\n"
                f"<i>Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>"
            )

            await self.bot.send_message(
                chat_id=self.user_id,
                text=message,
                parse_mode="HTML"
            )

            logger.info(f"✅ Sent error notification to admin")
            return True

        except TelegramAPIError as e:
            logger.error(f"❌ Failed to send error notification (Telegram API): {e}")
            return False

        except Exception as e:
            logger.error(f"❌ Failed to send error notification: {e}", exc_info=True)
            return False

    async def send_status_update(
        self,
        status: str,
        details: str = ""
    ) -> bool:
        """
        Send informational status update to admin.

        Used for non-critical updates about:
        - Bot startup/shutdown
        - Configuration changes
        - Performance metrics
        - Operational milestones

        Args:
            status: Main status message
            details: Optional additional details (shown in italic)

        Returns:
            True if notification sent successfully, False otherwise

        Example:
            await notifier.send_status_update(
                status="🚀 Bot started successfully",
                details="Uptime: 0h | Scanned: 0 NFTs"
            )
        """
        try:
            message = f"ℹ️ <b>Status Update</b>\n\n{status}"

            if details:
                message += f"\n\n<i>{details}</i>"

            message += f"\n\n<i>Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>"

            await self.bot.send_message(
                chat_id=self.user_id,
                text=message,
                parse_mode="HTML"
            )

            logger.info(f"✅ Sent status update: {status}")
            return True

        except TelegramAPIError as e:
            logger.error(f"❌ Failed to send status update (Telegram API): {e}")
            return False

        except Exception as e:
            logger.error(f"❌ Failed to send status update: {e}", exc_info=True)
            return False

    # ========================================================================
    # BOT LIFECYCLE MANAGEMENT
    # ========================================================================

    async def start_polling(self):
        """
        Start Telegram bot polling loop to listen for updates.

        Begins processing incoming updates including:
        - Callback queries (button presses)
        - Messages (if handlers registered)
        - Other update types

        This is a long-running task that should be run with asyncio.create_task().

        Raises:
            TelegramAPIError: If bot token is invalid or network error
            Exception: On unexpected polling errors

        Example:
            polling_task = asyncio.create_task(notifier.start_polling())
            # Bot now listening for callbacks...
            # On shutdown:
            polling_task.cancel()
        """
        try:
            logger.info("=" * 60)
            logger.info("🚀 Starting Telegram bot polling...")
            logger.info("=" * 60)

            await self.dp.start_polling(
                self.bot,
                allowed_updates=["callback_query", "message"]
            )

        except TelegramAPIError as e:
            logger.error(f"❌ Telegram API error during polling: {e}")
            raise

        except Exception as e:
            logger.error(f"❌ Unexpected polling error: {e}", exc_info=True)
            raise

    async def cleanup(self):
        """
        Cleanup bot resources and close network connections.

        Should be called on bot shutdown to properly release:
        - HTTP session
        - Network connections
        - Other bot resources

        Safe to call multiple times (idempotent).

        Example:
            try:
                await bot.run()
            finally:
                await notifier.cleanup()
        """
        try:
            logger.info("🔄 Cleaning up Telegram bot resources...")

            # Close bot session
            await self.bot.session.close()

            logger.info("✅ Telegram bot cleanup completed")

        except Exception as e:
            logger.error(f"❌ Error during bot cleanup: {e}", exc_info=True)


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def format_ton_amount(amount: float) -> str:
    """
    Format TON amount with consistent decimal places.

    Args:
        amount: TON amount to format

    Returns:
        Formatted string with 2 decimal places

    Example:
        >>> format_ton_amount(5.123456)
        '5.12 TON'
    """
    return f"{amount:.2f} TON"


def format_usd_amount(amount: float) -> str:
    """
    Format USD amount with currency symbol.

    Args:
        amount: USD amount to format

    Returns:
        Formatted string with $ symbol and 2 decimal places

    Example:
        >>> format_usd_amount(27.456)
        '$27.46'
    """
    return f"${amount:.2f}"


def format_percentage(value: float) -> str:
    """
    Format percentage with consistent decimal places.

    Args:
        value: Percentage value (e.g., 42.5 for 42.5%)

    Returns:
        Formatted string with % symbol

    Example:
        >>> format_percentage(42.567)
        '42.6%'
    """
    return f"{value:.1f}%"
