import logging
from datetime import datetime, timezone
from typing import List, Dict

from aiogram import Bot, Dispatcher, Router
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

import config
from database import Gift, ProfitAnalysis

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Telegram notification manager."""

    def __init__(self):
        """Initialize bot and dispatcher."""
        self.bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
        self.user_id = config.TELEGRAM_CHAT_ID
        self.dp = Dispatcher()
        self.router = Router()

        # Register handlers
        self.router.callback_query.register(self.handle_copy_id, lambda c: c.data and c.data.startswith("copy_id"))
        self.router.callback_query.register(self.handle_copy_id, lambda c: c.data and c.data.startswith("copy_mint"))
        self.dp.include_router(self.router)

    async def send_opportunity_alert(self, gift: Gift, analysis: ProfitAnalysis, ton_usd: float,
            sales_history: List[Dict] = None) -> bool:
        """Send profit opportunity notification."""
        try:
            # Extract attributes
            model, backdrop, symbol = None, None, None
            for attr in gift.attributes:
                attr_type = attr.get('type')
                if attr_type == 'model':
                    model = attr.get('value')
                elif attr_type == 'backdrop':
                    backdrop = attr.get('value')
                elif attr_type == 'symbol':
                    symbol = attr.get('value')

            # Calculate USD values
            buy_usd = gift.price * ton_usd
            target_usd = analysis.target_price * ton_usd
            profit_usd = analysis.profit_ton * ton_usd

            # Sales history info
            sales_info = ""
            if sales_history:
                avg_price = sum(s['price'] for s in sales_history) / len(sales_history)
                recent_count = len([s for s in sales_history if (datetime.now(timezone.utc) - s['date']).days <= 14])
                sales_info = f"\n📊 Sales: {len(sales_history)} total, {recent_count} recent (avg: {avg_price:.2f} TON)"

            # Premium/monochrome indicator
            special_type = ""
            if "Premium" in analysis.strategy:
                special_type = "✨ Premium"
            elif "Monochrome" in analysis.strategy:
                special_type = "🎨 Monochrome"

            message = f"""
<b>🎯 PROFIT OPPORTUNITY</b>

<b>📦 {gift.name}</b>
{special_type} {model} + {backdrop}

💰 <b>Price:</b> {gift.price:.2f} TON (${buy_usd:.2f})
🎯 <b>Target:</b> {analysis.target_price:.2f} TON (${target_usd:.2f})
💎 <b>Net Profit:</b> {analysis.profit_ton:.2f} TON (${profit_usd:.2f})
📈 <b>ROI:</b> {analysis.profit_percent:.1f}%
🔥 <b>Strategy:</b> {analysis.strategy}
⭐ <b>Confidence:</b> {analysis.confidence:.0%}{sales_info}

<b>ID:</b> <code>{gift.id}</code>
"""

            nft_url = f"https://t.me/portals/market?startapp=gift_{gift.id}_gkal9v"

            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="🔗 Open on Portals", url=nft_url)],
                    [InlineKeyboardButton(text="📋 Copy Mint #", callback_data=f"copy_mint:{gift.tg_id}")]])

            await self.bot.send_message(chat_id=self.user_id, text=message, parse_mode="HTML", reply_markup=keyboard)

            return True

        except Exception as e:
            logger.error(f"Error sending notification: {e}")
            return False

    async def handle_copy_id(self, callback: CallbackQuery):
        try:
            mint_number = callback.data.split(":")[1]
            await callback.answer(f"Mint #{mint_number}", show_alert=True)
        except Exception as e:
            logger.error(f"Error: {e}")
            await callback.answer("Error copying mint number", show_alert=True)

    async def handle_info(self, callback: CallbackQuery):
        """Handle info button callback."""
        try:
            await callback.answer("More info coming soon!", show_alert=False)
        except Exception as e:
            logger.error(f"Error handling info callback: {e}")

    async def start_polling(self):
        """Start Telegram bot polling."""
        try:
            logger.info("Starting Telegram bot polling...")
            await self.dp.start_polling(self.bot)
        except Exception as e:
            logger.error(f"Polling error: {e}")
