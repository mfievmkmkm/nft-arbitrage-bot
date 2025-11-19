"""
NFT Gift Bot - Advanced Automated NFT Arbitrage Trading System

An intelligent trading bot for Telegram NFT marketplace with advanced
profit detection, parallel processing, and comprehensive market analysis.

Key Features:
-------------
- Multi-strategy profit detection (floor, combo, special numbers)
- Parallel NFT analysis with intelligent rate limiting
- Real-time market monitoring via Portals.gift API
- Smart sales history analysis with outlier removal
- Premium backdrop and monochrome detection
- Database-backed deduplication
- Comprehensive error handling and recovery
- Detailed performance metrics and logging

Strategies:
-----------
1. Model Arbitrage: Buy cheapest, sell at average
2. Premium Floor Alert: Premium backdrops below expected multiplier
3. Monochrome Combo: Color-matched model + backdrop
4. Special Numbers: Rare IDs (#0, #69, palindromes, etc.)

Author: Elchin Aliev
Repository: https://github.com/Elchin-bit/nft-arbitrage-bot
License: MIT
"""

import os
os.environ['PYTHONIOENCODING'] = 'utf-8'

import asyncio
import logging
import sys
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, List

import config
from database import Database, Gift, ProfitAnalysis
from monitors.portals import PortalsMonitor
from notifications.telegram_bot import TelegramNotifier
from analyzers.profit_analyzer import ProfitAnalyzer

# Windows event loop compatibility
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Enhanced logging configuration with UTF-8 support
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('nft_bot.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


# ============================================================================
# MAIN BOT CLASS
# ============================================================================

class NFTGiftBot:
    """
    Advanced NFT arbitrage bot with parallel processing and smart analysis.

    Architecture:
    -------------
    - Monitors Portals.gift marketplace for new listings
    - Analyzes NFTs in parallel with rate limiting
    - Detects profitable opportunities using multiple strategies
    - Sends Telegram notifications with detailed analysis
    - Tracks performance metrics and handles errors gracefully

    Components:
    -----------
    - Database: SQLite-based deduplication and persistence
    - PortalsMonitor: Portals.gift API integration
    - ProfitAnalyzer: Multi-strategy profit detection
    - TelegramNotifier: User notifications and bot commands

    Configuration:
    --------------
    See config.py for customizable parameters:
    - MIN_PROFIT_PERCENT: Minimum profit threshold (default: 20%)
    - MAX_PRICE_TON: Maximum NFT price filter
    - SCAN_INTERVAL_SECONDS: Delay between scan cycles
    - MAX_PARALLEL_ANALYSES: Concurrent analysis limit
    """

    def __init__(self):
        """Initialize bot components and performance tracking."""
        self.db = Database(config.DATABASE_PATH)
        self.portals_monitor = PortalsMonitor()
        self.notifier = TelegramNotifier()
        self.analyzer = ProfitAnalyzer()

        # Rate limiting: prevents API throttling
        self.analysis_semaphore = asyncio.Semaphore(config.MAX_PARALLEL_ANALYSES)

        # Performance statistics
        self.stats: Dict[str, Any] = {
            'total_scanned': 0,
            'total_duplicates': 0,
            'total_found': 0,
            'total_notifications': 0,
            'successful_notifications': 0,
            'failed_notifications': 0,
            'start_time': datetime.now(),
            'uptime_seconds': 0,
            'cycles_completed': 0,
            'total_errors': 0
        }

        logger.info("=" * 60)
        logger.info("✅ NFTGiftBot initialized successfully")
        logger.info("=" * 60)

    # ========================================================================
    # MAIN SCANNING & ANALYSIS
    # ========================================================================

    async def scan_and_analyze(self) -> int:
        """
        Execute main scanning and analysis cycle with parallel processing.

        Process Flow:
        -------------
        1. Fetch new NFT listings from Portals.gift API
        2. Filter duplicates using database tracking
        3. Launch parallel analysis tasks with staggered execution
        4. Aggregate results and process opportunities
        5. Return count of profitable opportunities found

        Returns:
            Number of profitable opportunities detected in this cycle

        Raises:
            Exception: Logged but not propagated to allow retry
        """
        found_opportunities = 0

        try:
            # Step 1: Fetch new listings
            logger.info("🔍 Scanning marketplace for new listings...")
            new_gifts = await self.portals_monitor.scan_new_gifts()

            if not new_gifts:
                logger.info("📭 No new listings found")
                return 0

            # Step 2: Deduplicate
            unique_gifts = self._filter_duplicates(new_gifts)

            if not unique_gifts:
                logger.info("♻️ All listings already processed (duplicates)")
                return 0

            self.stats['total_scanned'] += len(unique_gifts)
            duplicates_count = len(new_gifts) - len(unique_gifts)

            logger.info(
                f"📦 Processing {len(unique_gifts)} NEW listings "
                f"({duplicates_count} duplicates filtered)"
            )

            # Step 3: Parallel analysis with staggered start
            analysis_tasks = self._create_staggered_analysis_tasks(unique_gifts)

            # Step 4: Execute and aggregate
            logger.info(f"⚡ Launching {len(analysis_tasks)} parallel analyses...")
            results = await asyncio.gather(*analysis_tasks, return_exceptions=True)

            # Step 5: Process results
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"❌ Analysis task #{i+1} failed: {result}")
                    self.stats['total_errors'] += 1
                    continue

                if result:  # Profitable opportunity found
                    found_opportunities += 1
                    self.stats['total_found'] += 1

            if found_opportunities > 0:
                logger.info(f"🎯 Found {found_opportunities} profitable opportunities!")
            else:
                logger.info("📊 Analysis complete - no opportunities found")

        except Exception as e:
            logger.error(f"❌ Critical error in scan_and_analyze: {e}", exc_info=True)
            self.stats['total_errors'] += 1

        return found_opportunities

    def _filter_duplicates(self, gifts: List[Gift]) -> List[Gift]:
        """
        Filter out duplicate NFTs using database tracking.

        Uses gift.id as unique identifier to prevent re-analyzing
        the same NFT across multiple cycles.

        Args:
            gifts: List of Gift objects to filter

        Returns:
            List of unique, unprocessed Gift objects
        """
        unique_gifts = []

        for gift in gifts:
            if self.db.is_nft_processed(gift.id):
                self.stats['total_duplicates'] += 1
                continue

            unique_gifts.append(gift)
            self.db.mark_nft_as_processed(gift)

        return unique_gifts

    def _create_staggered_analysis_tasks(self, gifts: List[Gift]) -> List[asyncio.Task]:
        """
        Create analysis tasks with staggered execution to prevent API throttling.

        Staggering distributes API requests over time, reducing the chance
        of hitting rate limits (HTTP 429 errors).

        Args:
            gifts: List of Gift objects to analyze

        Returns:
            List of asyncio.Task objects ready for gathering

        Example:
            For 10 gifts with 0.5s delay:
            - Gift #1: starts at t=0.0s
            - Gift #2: starts at t=0.5s
            - Gift #3: starts at t=1.0s
            - etc.
        """
        tasks = []

        for i, gift in enumerate(gifts):
            delay = i * config.ANALYSIS_START_DELAY
            task = asyncio.create_task(
                self._analyze_single_gift_with_delay(gift, delay)
            )
            tasks.append(task)

        return tasks

    async def _analyze_single_gift_with_delay(
        self,
        gift: Gift,
        initial_delay: float
    ) -> bool:
        """
        Analyze single NFT with staggered start and rate limiting.

        Flow:
        -----
        1. Wait for staggered start delay (prevents burst requests)
        2. Acquire semaphore slot (limits concurrent analyses)
        3. Execute profit analysis
        4. Handle profitable opportunities
        5. Release semaphore slot
        6. Return result

        Args:
            gift: NFT Gift instance to analyze
            initial_delay: Seconds to wait before starting (staggering)

        Returns:
            True if profitable opportunity found, False otherwise
        """
        # Step 1: Staggered start
        if initial_delay > 0:
            await asyncio.sleep(initial_delay)

        # Steps 2-5: Rate-limited analysis
        async with self.analysis_semaphore:
            try:
                logger.info(f"🔍 Analyzing {gift.name} (#{gift.number})")

                # Execute multi-strategy analysis
                analysis = await self.analyzer.analyze_profit_opportunity(
                    gift,
                    portals_monitor=self.portals_monitor
                )

                # Handle result
                if analysis:
                    logger.info("💰 PROFITABLE OPPORTUNITY IDENTIFIED!")
                    await self._handle_profitable_opportunity(gift, analysis)
                    return True

                return False

            except Exception as e:
                logger.error(
                    f"❌ Error analyzing {gift.name}: {e}",
                    exc_info=True
                )
                self.stats['total_errors'] += 1
                return False

    # ========================================================================
    # OPPORTUNITY HANDLING
    # ========================================================================

    async def _handle_profitable_opportunity(
        self,
        gift: Gift,
        analysis: ProfitAnalysis
    ):
        """
        Process profitable opportunity by sending notification and logging details.

        Args:
            gift: Gift object with NFT details
            analysis: ProfitAnalysis with opportunity metrics
        """
        try:
            # Send notification
            success = await self.send_notification(gift, analysis)

            # Track result
            if success:
                logger.info("✅ Notification sent successfully")
                self.stats['successful_notifications'] += 1
            else:
                logger.error("❌ Failed to send notification")
                self.stats['failed_notifications'] += 1

            # Log detailed summary
            logger.info(
                f"\n{'='*60}\n"
                f"🎯 OPPORTUNITY SUMMARY\n"
                f"{'='*60}\n"
                f"  NFT:        {gift.name} #{gift.number}\n"
                f"  Buy Price:  {gift.price:.2f} TON (${gift.price * await self.analyzer.get_ton_usd_price():.2f})\n"
                f"  Target:     {analysis.target_price:.2f} TON\n"
                f"  Profit:     {analysis.profit_percent:.1f}% ({analysis.profit_ton:.2f} TON)\n"
                f"  Strategy:   {analysis.strategy}\n"
                f"  Confidence: {analysis.confidence:.0%}\n"
                f"  Risk:       {analysis.risk_score:.0%}\n"
                f"  Reasoning:  {analysis.reasoning}\n"
                f"{'='*60}"
            )

            self.stats['total_notifications'] += 1

        except Exception as e:
            logger.error(f"❌ Error handling opportunity: {e}", exc_info=True)
            self.stats['total_errors'] += 1

    async def send_notification(
        self,
        gift: Gift,
        analysis: ProfitAnalysis
    ) -> bool:
        """
        Send enriched profit opportunity notification to Telegram.

        Enrichment includes:
        - Premium/monochrome detection
        - Relevant sales history
        - Current TON/USD exchange rate
        - Strategy-specific context

        Args:
            gift: Gift object with NFT details
            analysis: ProfitAnalysis with opportunity details

        Returns:
            True if notification sent successfully, False otherwise
        """
        try:
            # Extract NFT attributes
            model, backdrop, symbol = self._extract_gift_attributes(gift.attributes)

            # Analyze NFT properties
            is_premium = self.analyzer.is_premium_backdrop(backdrop)
            is_monochrome = await self.analyzer.is_monochrome(
                model, backdrop, gift.name, gift.id
            )

            # Fetch relevant sales history
            sales_history = await self._get_relevant_sales_history(
                gift.name, model, backdrop, is_premium, is_monochrome
            )

            # Get current TON price
            ton_usd = await self.analyzer.get_ton_usd_price()

            # Send Telegram notification
            success = await self.notifier.send_opportunity_alert(
                gift, analysis, ton_usd, sales_history
            )

            return success

        except Exception as e:
            logger.error(f"❌ Send notification error: {e}", exc_info=True)
            self.stats['total_errors'] += 1
            return False

    def _extract_gift_attributes(
        self,
        attributes: List[Dict]
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Extract model, backdrop, and symbol from gift attributes list.

        Args:
            attributes: List of attribute dictionaries with 'type' and 'value'

        Returns:
            Tuple of (model, backdrop, symbol) - any can be None if missing
        """
        model, backdrop, symbol = None, None, None

        for attr in attributes:
            attr_type = attr.get('type')
            if attr_type == 'model':
                model = attr.get('value')
            elif attr_type == 'backdrop':
                backdrop = attr.get('value')
            elif attr_type == 'symbol':
                symbol = attr.get('value')

        return model, backdrop, symbol

    async def _get_relevant_sales_history(
        self,
        gift_name: str,
        model: str,
        backdrop: str,
        is_premium: bool,
        is_monochrome: bool
    ) -> Optional[List[Dict]]:
        """
        Fetch sales history with strategy-appropriate filtering.

        Strategy Logic:
        ---------------
        - Premium/Monochrome: Search by model + backdrop (exact combo)
        - Regular: Search by model only (ignore backdrop)

        This ensures accurate price comparison for similar NFTs.

        Args:
            gift_name: NFT collection name
            model: Model attribute value
            backdrop: Backdrop attribute value
            is_premium: Whether backdrop is premium (Midnight Blue, etc.)
            is_monochrome: Whether model and backdrop match colors

        Returns:
            List of sale dictionaries, or None on error
        """
        try:
            use_combo_strategy = is_premium or is_monochrome
            search_backdrop = backdrop if use_combo_strategy else None

            logger.info(
                f"📊 Fetching sales history: "
                f"{'combo (model+backdrop)' if use_combo_strategy else 'model only'}"
            )

            return await self.portals_monitor.get_sales_history(
                gift_name,
                model=model,
                backdrop=search_backdrop,
                days=config.SALES_HISTORY_DAYS
            )
        except Exception as e:
            logger.error(f"❌ Error getting sales history: {e}")
            self.stats['total_errors'] += 1
            return None

    # ========================================================================
    # LOGGING & STATISTICS
    # ========================================================================

    def _log_cycle_summary(
        self,
        cycle: int,
        opportunities_found: int,
        duration: float
    ):
        """
        Log comprehensive cycle summary with performance metrics.

        Args:
            cycle: Current cycle number
            opportunities_found: Opportunities detected this cycle
            duration: Cycle execution time in seconds
        """
        self.stats['uptime_seconds'] = (
            datetime.now() - self.stats['start_time']
        ).total_seconds()
        self.stats['cycles_completed'] += 1

        # Calculate performance metrics
        nfts_processed = self.stats['total_scanned'] - self.stats['total_duplicates']
        speed_per_nft = duration / max(1, nfts_processed) if nfts_processed > 0 else 0

        success_rate = (
            self.stats['successful_notifications'] /
            max(1, self.stats['total_notifications']) * 100
        )

        logger.info(
            f"\n{'='*60}\n"
            f"✅ CYCLE #{cycle} COMPLETE\n"
            f"{'='*60}\n"
            f"📊 This Cycle:\n"
            f"  • Duration: {duration:.1f}s\n"
            f"  • Opportunities: {opportunities_found}\n"
            f"  • Speed: {speed_per_nft:.2f}s per NFT\n"
            f"\n"
            f"📈 Cumulative Stats:\n"
            f"  • Total opportunities: {self.stats['total_found']}\n"
            f"  • NFTs scanned: {self.stats['total_scanned']}\n"
            f"  • Duplicates filtered: {self.stats['total_duplicates']}\n"
            f"  • Notifications: {self.stats['successful_notifications']}/"
            f"{self.stats['total_notifications']} ({success_rate:.1f}% success)\n"
            f"  • Errors: {self.stats['total_errors']}\n"
            f"  • Uptime: {self.stats['uptime_seconds']/3600:.1f}h\n"
            f"{'='*60}"
        )

    # ========================================================================
    # MAIN EXECUTION LOOP
    # ========================================================================

    async def run(self):
        """
        Main bot execution loop with comprehensive monitoring.

        Flow:
        -----
        1. Log startup configuration
        2. Start Telegram bot polling
        3. Execute scan/analyze cycles indefinitely
        4. Handle errors gracefully with retry
        5. Shutdown on keyboard interrupt (Ctrl+C)

        Error Handling:
        ---------------
        - Individual analysis errors: Logged, continue
        - Cycle errors: Logged, wait 60s, retry
        - Fatal errors: Shutdown gracefully
        """
        logger.info("=" * 60)
        logger.info("🚀 NFT GIFT BOT v2.2 STARTING")
        logger.info("=" * 60)
        logger.info(
            f"⚙️ Configuration:\n"
            f"  • Min Profit:         {config.MIN_PROFIT_PERCENT}%\n"
            f"  • Max Price:          {config.MAX_PRICE_TON} TON\n"
            f"  • Scan Interval:      {config.SCAN_INTERVAL_SECONDS}s\n"
            f"  • Sales History:      {config.SALES_HISTORY_DAYS} days\n"
            f"  • Max Parallel:       {config.MAX_PARALLEL_ANALYSES}\n"
            f"  • Analysis Delay:     {config.ANALYSIS_START_DELAY}s\n"
            f"  • Database:           {config.DATABASE_PATH}\n"
            f"  • Telegram Enabled:   {bool(config.TELEGRAM_BOT_TOKEN)}"
        )
        logger.info("=" * 60)

        # Start Telegram bot polling
        polling_task = asyncio.create_task(self.notifier.start_polling())
        cycle = 0

        try:
            while True:
                try:
                    cycle += 1
                    cycle_start = datetime.now()

                    logger.info(
                        f"\n{'=' * 60}\n"
                        f"🔄 CYCLE #{cycle} | {cycle_start.strftime('%Y-%m-%d %H:%M:%S')}\n"
                        f"{'=' * 60}"
                    )

                    # Execute main cycle
                    opportunities_found = await self.scan_and_analyze()

                    # Log results
                    cycle_duration = (datetime.now() - cycle_start).total_seconds()
                    self._log_cycle_summary(cycle, opportunities_found, cycle_duration)

                    # Wait before next cycle
                    logger.info(f"⏳ Waiting {config.SCAN_INTERVAL_SECONDS}s until next cycle...")
                    await asyncio.sleep(config.SCAN_INTERVAL_SECONDS)

                except asyncio.CancelledError:
                    raise  # Propagate cancellation

                except Exception as e:
                    logger.error(
                        f"\n{'='*60}\n"
                        f"❌ CYCLE #{cycle} ERROR\n"
                        f"{'='*60}\n"
                        f"{str(e)}\n"
                        f"{'='*60}",
                        exc_info=True
                    )

                    self.stats['total_errors'] += 1

                    # Attempt error notification
                    try:
                        await self.notifier.send_error_notification(
                            f"Cycle #{cycle} error: {str(e)}"
                        )
                    except:
                        pass

                    # Wait before retry
                    logger.info("⏳ Waiting 60s before retry...")
                    await asyncio.sleep(60)

        except KeyboardInterrupt:
            logger.info("\n⛔ Received shutdown signal (Ctrl+C)")
        finally:
            await self.shutdown(polling_task)

    # ========================================================================
    # SHUTDOWN HANDLING
    # ========================================================================

    async def shutdown(self, polling_task: asyncio.Task):
        """
        Execute graceful shutdown with cleanup and statistics reporting.

        Steps:
        ------
        1. Send shutdown notification to Telegram
        2. Cancel polling task
        3. Cleanup bot resources (DB connections, etc.)
        4. Log final performance statistics
        5. Exit cleanly

        Args:
            polling_task: Asyncio task for Telegram bot polling
        """
        logger.info("=" * 60)
        logger.info("🔄 INITIATING GRACEFUL SHUTDOWN")
        logger.info("=" * 60)

        # Calculate final stats
        uptime_seconds = (datetime.now() - self.stats['start_time']).total_seconds()
        uptime_hours = uptime_seconds / 3600
        success_rate = (
            self.stats['successful_notifications'] /
            max(1, self.stats['total_notifications']) * 100
        )

        # Send shutdown notification
        try:
            await self.notifier.send_status_update(
                "🔄 Bot Shutting Down",
                f"Uptime: {uptime_hours:.1f}h | "
                f"Cycles: {self.stats['cycles_completed']} | "
                f"Opportunities: {self.stats['total_found']} | "
                f"NFTs Scanned: {self.stats['total_scanned']} | "
                f"Errors: {self.stats['total_errors']}"
            )
        except Exception as e:
            logger.warning(f"⚠️ Failed to send shutdown notification: {e}")

        # Cancel Telegram polling
        polling_task.cancel()
        try:
            await polling_task
        except asyncio.CancelledError:
            logger.info("⛔ Telegram polling stopped")

        # Cleanup resources
        try:
            await self.notifier.cleanup()
            logger.info("✅ Resources cleaned up")
        except Exception as e:
            logger.warning(f"⚠️ Error during cleanup: {e}")

        # Final statistics report
        logger.info("=" * 60)
        logger.info("📊 FINAL PERFORMANCE STATISTICS")
        logger.info("=" * 60)
        logger.info(
            f"  • Total Uptime:       {uptime_hours:.2f} hours\n"
            f"  • Cycles Completed:   {self.stats['cycles_completed']}\n"
            f"  • NFTs Scanned:       {self.stats['total_scanned']}\n"
            f"  • Duplicates:         {self.stats['total_duplicates']}\n"
            f"  • Opportunities:      {self.stats['total_found']}\n"
            f"  • Notifications:      {self.stats['successful_notifications']}/"
            f"{self.stats['total_notifications']} ({success_rate:.1f}% success)\n"
            f"  • Total Errors:       {self.stats['total_errors']}\n"
            f"  • Avg Opportunities:  {self.stats['total_found']/max(1, uptime_hours):.2f}/hour"
        )
        logger.info("=" * 60)
        logger.info("✅ NFT GIFT BOT STOPPED SUCCESSFULLY")
        logger.info("=" * 60)


# ============================================================================
# APPLICATION ENTRY POINT
# ============================================================================

async def main():
    """
    Application entry point with comprehensive error handling.

    Creates and runs NFTGiftBot instance. Handles fatal errors
    by logging and exiting with error code.

    Raises:
        SystemExit: On fatal initialization or runtime error
    """
    try:
        bot = NFTGiftBot()
        await bot.run()
    except Exception as e:
        logger.error(
            f"\n{'='*60}\n"
            f"❌ FATAL ERROR\n"
            f"{'='*60}\n"
            f"{str(e)}\n"
            f"{'='*60}",
            exc_info=True
        )
        sys.exit(1)


if __name__ == "__main__":
    """
    Script entry point with keyboard interrupt handling.
    
    Handles:
    - Normal execution via asyncio.run()
    - Keyboard interrupt (Ctrl+C) - graceful shutdown
    - Unexpected exceptions - error logging and exit
    """
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n⛔ Bot stopped by user (Ctrl+C)")
        sys.exit(0)
    except Exception as e:
        logger.error(
            f"\n{'='*60}\n"
            f"❌ APPLICATION ERROR\n"
            f"{'='*60}\n"
            f"{str(e)}\n"
            f"{'='*60}",
            exc_info=True
        )
        sys.exit(1)
