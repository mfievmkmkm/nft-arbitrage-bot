"""
NFT Gift Bot - Main entry point.
Automated NFT arbitrage trading bot for Telegram Gifts marketplace.

This bot monitors new NFT listings, analyzes profit opportunities,
and sends notifications via Telegram.
"""

import os

os.environ['PYTHONIOENCODING'] = 'utf-8'

import asyncio
import logging
import sys
from datetime import datetime
from typing import Dict, Any

import config
from database import Database, Gift, ProfitAnalysis
from monitors.portals import PortalsMonitor
from notifications.telegram_bot import TelegramNotifier
from analyzers.profit_analyzer import ProfitAnalyzer

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('nft_bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


class NFTGiftBot:
    """Main bot class orchestrating NFT monitoring and trading."""

    def __init__(self):
        """Initialize bot components."""
        self.db = Database(config.DATABASE_PATH)
        self.portals_monitor = PortalsMonitor()
        self.notifier = TelegramNotifier()
        self.analyzer = ProfitAnalyzer()
        self.stats: Dict[str, Any] = {
            'total_scanned': 0,
            'total_found': 0,
            'total_notifications': 0,
            'start_time': datetime.now()
        }

    async def scan_and_analyze(self) -> int:
        """
        Main scanning and analysis cycle.

        Returns:
            int: Number of profit opportunities found
        """
        found_opportunities = 0

        try:
            new_gifts = await self.portals_monitor.scan_new_gifts()

            if not new_gifts:
                return 0

            self.stats['total_scanned'] += len(new_gifts)

            for gift in new_gifts:
                try:
                    model, backdrop = None, None
                    for attr in gift.attributes:
                        if attr.get('type') == 'model':
                            model = attr.get('value')
                        elif attr.get('type') == 'backdrop':
                            backdrop = attr.get('value')

                    logger.info(f"Analyzing {gift.name}")

                    analysis = await self.analyzer.analyze_profit_opportunity(
                        gift,
                        portals_monitor=self.portals_monitor
                    )

                    if analysis:
                        logger.info("Final check: validating opportunity")

                        is_mono = self.analyzer.is_monochrome(model, backdrop)
                        is_premium = self.analyzer.is_premium_backdrop(backdrop)
                        search_backdrop = backdrop if (is_mono or is_premium) else None

                        fresh_nfts = await self.portals_monitor.search_similar_nfts(
                            model=model,
                            backdrop=search_backdrop
                        )

                        if fresh_nfts:
                            fresh_prices = [
                                float(nft.get('price', 0))
                                for nft in fresh_nfts
                                if nft.get('price', 0) > 0
                            ]
                            if fresh_prices:
                                fresh_min = min(fresh_prices)

                                if gift.price > fresh_min * 1.02:
                                    logger.warning(
                                        f"Outdated opportunity: {gift.price} vs {fresh_min}"
                                    )
                                    continue

                                logger.info(f"Confirmed cheapest: {gift.price} vs {fresh_min}")

                        logger.info(f"Sending notification for {gift.name}")

                        try:
                            await self.send_notification(gift, analysis)
                            logger.info("Notification sent successfully")
                            self.stats['total_notifications'] += 1
                        except Exception as e:
                            logger.error(f"Notification error: {e}", exc_info=True)

                        logger.info(
                            f"Profit opportunity: {gift.name} | "
                            f"Buy: {gift.price} TON | "
                            f"Sell: {analysis.target_price:.1f} TON | "
                            f"Profit: {analysis.profit_percent:.1f}%"
                        )

                        found_opportunities += 1
                        self.stats['total_found'] += 1

                    await asyncio.sleep(1)

                except Exception as e:
                    logger.error(f"Error analyzing {gift.name}: {e}", exc_info=True)
                    continue

        except Exception as e:
            logger.error(f"Scan and analyze error: {e}", exc_info=True)

        return found_opportunities

    async def send_notification(self, gift: Gift, analysis: ProfitAnalysis):
        """
        Send profit opportunity notification to Telegram.

        Args:
            gift: NFT Gift instance
            analysis: Profit analysis result
        """
        try:
            model, backdrop = None, None
            for attr in gift.attributes:
                if attr.get('type') == 'model':
                    model = attr.get('value')
                elif attr.get('type') == 'backdrop':
                    backdrop = attr.get('value')

            is_mono = self.portals_monitor.is_monochrome(model, backdrop)
            is_premium = self.portals_monitor.is_premium_backdrop(backdrop)
            search_backdrop = backdrop if (is_mono or is_premium) else None

            sales_history = await self.portals_monitor.get_sales_history(
                gift.name,
                model=model,
                backdrop=search_backdrop,
                days=30
            )

            ton_usd = await self.analyzer.get_ton_usd_price()

            success = await self.notifier.send_opportunity_alert(
                gift,
                analysis,
                ton_usd,
                sales_history
            )

            if success:
                logger.info(f"Notification sent: {gift.name}")
            else:
                logger.error(f"Failed to send notification: {gift.name}")

        except Exception as e:
            logger.error(f"Send notification error: {e}")

    async def run(self):
        """Main bot loop."""
        logger.info("NFT Gift Bot started")
        logger.info(
            f"Config: min_profit={config.MIN_PROFIT_PERCENT}%, "
            f"max_price={config.MAX_PRICE_TON} TON"
        )

        polling_task = asyncio.create_task(self.notifier.start_polling())

        cycle = 0

        try:
            while True:
                try:
                    cycle += 1
                    logger.info(
                        f"\nCycle #{cycle} | "
                        f"{datetime.now().strftime('%H:%M:%S')}"
                    )
                    logger.info("Starting scan...")

                    await self.scan_and_analyze()

                    logger.info(
                        f"Cycle #{cycle} complete: "
                        f"Found {self.stats['total_found']} opportunities"
                    )

                    await asyncio.sleep(config.SCAN_INTERVAL_SECONDS)

                except Exception as e:
                    logger.error(f"Main loop error: {e}", exc_info=True)
                    await asyncio.sleep(60)

        except KeyboardInterrupt:
            logger.info("Received shutdown signal (Ctrl+C)")

        finally:
            await self.shutdown(polling_task)

    async def shutdown(self, polling_task):
        """
        Graceful shutdown procedure.

        Args:
            polling_task: Asyncio task for Telegram polling
        """
        logger.info("Shutting down gracefully...")

        polling_task.cancel()
        try:
            await polling_task
        except asyncio.CancelledError:
            pass
        logger.info("Telegram polling stopped")

        try:
            await self.notifier.bot.session.close()
            logger.info("Telegram bot session closed")
        except Exception as e:
            logger.warning(f"Error closing bot session: {e}")

        logger.info("Bot stopped successfully")


async def main():
    """Application entry point."""
    bot = NFTGiftBot()
    await bot.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
