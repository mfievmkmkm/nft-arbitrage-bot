"""
Telegram bot notifier.

Sends formatted profit opportunity alerts with interactive buttons
to Telegram chat.
"""

import asyncio
import logging
from typing import List, Dict
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, Router
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from database import Gift, ProfitAnalysis
import config

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Telegram notification manager."""

    def __init__(self):
        """Initialize bot and dispatcher."""
        self.bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
        self.user_id = config.TELEGRAM_CHAT_ID
        self.dp = Dispatcher()
        self.router = Router()

        self.router.callback_query.register(
            self.handle_copy_id,
            lambda c: c.data and c.data.startswith("copy_id:")
        )

        self.router.callback_query.register(
            self.handle_info,
            lambda c: c.data and c.data.startswith("info:")
        )

        self.dp.include_router(self.router)

    async def send_opportunity_alert(
            self,
            gift: Gift,
            analysis: ProfitAnalysis,
            ton_usd: float,
            sales_history: List[Dict] = None
    ) -> bool:
        """
        Send profit opportunity notification to Telegram.

        Args:
            gift: NFT Gift instance
            analysis: Profit analysis result
            ton_usd: Current TON/USD exchange rate
            sales_history: Optional sales history data

        Returns:
            bool: True if sent successfully
        """
        try:
            model, backdrop, symbol = None, None, None
            for attr in gift.attributes:
                if attr.get('type') == 'model':
                    model = attr.get('value')
                elif attr.get('type') == 'backdrop':
                    backdrop = attr.get('value')
                elif attr.get('type') == 'symbol':
                    symbol = attr.get('value')

            profit_usd = analysis.profit_ton * ton_usd
            buy_price_usd = gift.price * ton_usd
            target_price_usd = analysis.target_price * ton_usd

            sales_text = ""
            if sales_history and len(sales_history) > 0:
                recent = sales_history[:5]
                sales_text = "\n\n📊 Recent sales (last 30 days):\n"
                for sale in recent:
                    sale_date = sale['date']
                    if isinstance(sale_date, str):
                        sale_date = datetime.fromisoformat(
                            sale_date.replace('Z', '+00:00')
                        )

                    days_ago = (datetime.now(timezone.utc) - sale_date).days
                    sales_text += f"• {sale['price']:.2f} TON ({days_ago}d ago)\n"

            message = f"""
🔥 <b>PROFIT OPPORTUNITY</b> 🔥

<b>{gift.name}</b>
📦 Collection: {gift.collection}

💎 <b>Attributes:</b>
• Model: {model}
• Backdrop: {backdrop}
• Symbol: {symbol}

💰 <b>Pricing:</b>
• Buy: {gift.price} TON (${buy_price_usd:.2f})
• Sell: {analysis.target_price:.1f} TON (${target_price_usd:.2f})
• Net Profit: {analysis.profit_ton:.2f} TON (${profit_usd:.2f})

📈 <b>ROI: {analysis.profit_percent:.1f}%</b>

🎯 Strategy: {analysis.strategy}
📊 Confidence: {analysis.confidence:.0%}
{sales_text}
🆔 Gift ID: <code>{gift.id}</code>
"""

            nft_url = f"https://getgems.io/collection/EQAtXZPpnoTbUV1vVW2vxqL9XmxPgz3ACSJPHobgCW1J7t2T/{gift.tg_id}"

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔗 Open on GetGems", url=nft_url)],
                [InlineKeyboardButton(
                    text="📋 Copy ID",
                    callback_data=f"copy_id:{gift.id}"
                )]
            ])

            await self.bot.send_message(
                chat_id=self.user_id,
                text=message,
                parse_mode="HTML",
                reply_markup=keyboard
            )

            return True

        except Exception as e:
            logger.error(f"Error sending notification: {e}")
            return False

    async def handle_copy_id(self, callback: CallbackQuery):
        """Handle copy ID button callback."""
        try:
            gift_id = callback.data.split(":")[1]
            await callback.answer(f"ID copied: {gift_id}", show_alert=True)
        except Exception as e:
            logger.error(f"Error handling copy callback: {e}")
            await callback.answer("Error copying ID", show_alert=True)

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
