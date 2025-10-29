"""
NFT profit opportunity analyzer.

Analyzes NFT pricing, floor prices, monochrome combinations,
and calculates potential profit after marketplace fees.
"""

import logging
import aiohttp
import asyncio
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta

from database import Gift, ProfitAnalysis
import config

logger = logging.getLogger(__name__)


class ProfitAnalyzer:
    """Analyzer for NFT profit opportunities."""

    PREMIUM_BACKDROPS = ['midnight blue', 'onyx black', 'black']

    def __init__(self):
        """Initialize analyzer with caching."""
        self.market_cache = {}
        self.ton_usd_price = 0.0
        self.last_ton_update = None

    async def get_ton_usd_price(self) -> float:
        """
        Fetch current TON/USD exchange rate from CoinGecko API.
        Caches result for 5 minutes to reduce API calls.

        Returns:
            float: Current TON price in USD
        """
        try:
            if self.last_ton_update and \
                    (datetime.now() - self.last_ton_update).seconds < 300:
                return self.ton_usd_price

            url = "https://api.coingecko.com/api/v3/simple/price"
            params = {'ids': 'the-open-network', 'vs_currencies': 'usd'}

            async with aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=10)
            ) as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        price = data.get('the-open-network', {}).get('usd', 5.0)
                        self.ton_usd_price = price
                        self.last_ton_update = datetime.now()
                        return price

            return 5.0

        except Exception as e:
            logger.error(f"Error fetching TON price: {e}")
            return 5.0

    def is_monochrome(self, model: str, backdrop: str) -> bool:
        """
        Check if NFT has monochrome color combination.

        Args:
            model: NFT model name
            backdrop: NFT backdrop color

        Returns:
            bool: True if monochrome combination detected
        """
        if not model or not backdrop:
            return False

        color_groups = {
            'red': ['red', 'crimson', 'scarlet', 'cherry', 'ruby', 'rose', 'burgundy'],
            'blue': ['blue', 'azure', 'navy', 'sapphire', 'cobalt', 'cyan', 'indigo'],
            'green': ['green', 'emerald', 'forest', 'jade', 'olive', 'lime'],
            'yellow': ['yellow', 'gold', 'golden', 'amber', 'lemon'],
            'purple': ['purple', 'violet', 'lavender', 'plum', 'amethyst'],
            'pink': ['pink', 'rose', 'magenta', 'fuchsia'],
            'orange': ['orange', 'coral', 'peach', 'tangerine'],
            'brown': ['brown', 'chocolate', 'coffee', 'sepia', 'tan'],
            'gray': ['gray', 'grey', 'silver', 'charcoal'],
            'white': ['white', 'ivory', 'cream', 'pearl']
        }

        model_lower = model.lower()
        backdrop_lower = backdrop.lower()

        for color_group in color_groups.values():
            model_match = any(color in model_lower for color in color_group)
            backdrop_match = any(color in backdrop_lower for color in color_group)

            if model_match and backdrop_match:
                logger.info(f"Monochrome detected: {model} + {backdrop}")
                return True

        return False

    def is_premium_backdrop(self, backdrop: str) -> bool:
        """
        Check if backdrop is premium rarity.

        Args:
            backdrop: Backdrop color name

        Returns:
            bool: True if premium backdrop
        """
        if not backdrop:
            return False
        return backdrop.lower() in self.PREMIUM_BACKDROPS

    async def analyze_profit_opportunity(
            self,
            gift: Gift,
            portals_monitor
    ) -> Optional[ProfitAnalysis]:
        """
        Analyze NFT for profit opportunity.

        Args:
            gift: NFT Gift instance
            portals_monitor: PortalsMonitor instance for market data

        Returns:
            ProfitAnalysis if profitable, None otherwise
        """
        try:
            logger.info(f"\n{'=' * 60}")
            logger.info(f"Analyzing: {gift.name}")

            model, backdrop, symbol = None, None, None
            for attr in gift.attributes:
                if attr.get('type') == 'model':
                    model = attr.get('value')
                elif attr.get('type') == 'backdrop':
                    backdrop = attr.get('value')
                elif attr.get('type') == 'symbol':
                    symbol = attr.get('value')

            logger.info(f"Model: {model}, Backdrop: {backdrop}, Symbol: {symbol}")
            logger.info(f"Current price: {gift.price} TON")

            if gift.price > config.MAX_PRICE_TON:
                logger.warning(f"Price {gift.price} TON exceeds max {config.MAX_PRICE_TON}")
                return None

            is_mono = self.is_monochrome(model, backdrop)
            is_premium = self.is_premium_backdrop(backdrop)
            use_combo = is_mono or is_premium

            if is_premium:
                logger.info(f"Premium backdrop: {backdrop}")

            if is_mono:
                logger.info(f"Monochrome combination detected")
            else:
                logger.info(f"Regular backdrop: {backdrop}")

            model_floor = await portals_monitor.get_model_floor(model)
            if not model_floor:
                logger.warning("Could not get model floor")
                return None

            logger.info(f"Model floor: {model_floor} TON")

            price_diff_pct = ((gift.price - model_floor) / model_floor) * 100
            if price_diff_pct > 0:
                logger.warning(f"Price {gift.price} TON > floor {model_floor} TON")
                return None

            logger.info(f"Good price! {price_diff_pct:.1f}% below floor")

            search_backdrop = backdrop if use_combo else None
            similar_nfts = await portals_monitor.search_similar_nfts(
                model=model,
                backdrop=search_backdrop
            )

            if not similar_nfts:
                logger.warning("No similar NFTs found")
                return None

            logger.info(f"Found {len(similar_nfts)} similar NFTs")

            prices = [
                float(nft.get('price', 0))
                for nft in similar_nfts
                if nft.get('price', 0) > 0
            ]

            if not prices:
                logger.warning("No valid prices found")
                return None

            prices_sorted = sorted(prices)
            min_price = prices_sorted[0]
            max_price = prices_sorted[-1]
            avg_price = sum(prices) / len(prices)

            logger.info(f"Prices: Min={min_price}, Max={max_price}, Avg={avg_price:.2f}")

            if gift.price > min_price * 1.02:
                logger.warning(f"Not cheapest! Min is {min_price} TON")
                return None

            logger.info("This is the cheapest!")

            if len(prices_sorted) >= 2:
                target_price = prices_sorted[1]
            else:
                target_price = min_price * 1.05

            logger.info(f"Target: {target_price} TON")

            gross_profit = target_price - gift.price
            gross_profit_pct = (gross_profit / gift.price) * 100

            commission = target_price * 0.05
            net_profit = gross_profit - commission
            net_profit_pct = (net_profit / gift.price) * 100

            logger.info(f"Gross profit: {gross_profit:.2f} TON ({gross_profit_pct:.1f}%)")
            logger.info(f"Commission (5%): {commission:.2f} TON")
            logger.info(f"Net profit: {net_profit:.2f} TON ({net_profit_pct:.1f}%)")

            need_sales_check = (
                    use_combo or
                    len(prices) < 5 or
                    target_price > gift.price * 1.5
            )

            sales_history = []

            logger.info(
                f"Need sales check: {need_sales_check} "
                f"(use_combo={use_combo}, prices={len(prices)}, "
                f"jump={target_price > gift.price * 1.5})"
            )

            if need_sales_check:
                sales_history = await portals_monitor.get_sales_history(
                    gift.name,
                    model=model,
                    backdrop=search_backdrop,
                    days=30
                )

                if not sales_history or len(sales_history) < 2:
                    logger.warning(
                        f"Insufficient sales history: {len(sales_history)} sales"
                    )
                    return None

                logger.info(f"Sales history: {len(sales_history)} sales")

                recent_sales = [s for s in sales_history if s['price'] >= gift.price]
                if not recent_sales:
                    logger.warning("No sales above current price")
                    return None

                logger.info(f"Recent sales above price: {len(recent_sales)}")

            if net_profit_pct < config.MIN_PROFIT_PERCENT:
                logger.warning(
                    f"Net profit {net_profit_pct:.1f}% < minimum {config.MIN_PROFIT_PERCENT}%"
                )
                return None

            history_confidence = 0.8 if (sales_history and len(sales_history) > 0) else 0.6

            strategy = "Monochrome" if is_mono else \
                "Premium backdrop" if is_premium else \
                    "Model arbitrage"

            logger.info(f"PROFIT OPPORTUNITY FOUND!")
            logger.info(f"Strategy: {strategy}")
            logger.info(f"Confidence: {history_confidence:.1%}")

            return ProfitAnalysis(
                gift_id=gift.id,
                gift_name=gift.name,
                buy_price=gift.price,
                target_price=target_price,
                profit_ton=net_profit,
                profit_percent=net_profit_pct,
                strategy=strategy,
                confidence=history_confidence
            )

        except Exception as e:
            logger.error(f"Analysis error for {gift.name}: {e}", exc_info=True)
            return None
