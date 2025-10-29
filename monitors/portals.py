"""
Portals marketplace monitor.

Monitors new NFT listings, tracks floor prices, and retrieves
sales history from Telegram Gifts marketplace.
"""

import logging
from typing import List, Optional, Dict
from datetime import datetime, timezone, timedelta

from database import Gift
import config
from aportalsmp.gifts import search, marketActivity, filterFloors
import asyncio

logger = logging.getLogger(__name__)


class PortalsMonitor:
    """Monitor for Portals NFT marketplace."""

    PREMIUM_BACKDROPS = ['midnight blue', 'onyx black', 'black']

    def __init__(self):
        """Initialize monitor with caching."""
        self.auth_data = config.PORTALS_AUTH_TOKEN
        self.processed_ids = set()
        self.floor_cache = {}
        self.search_cache = {}
        self.cache_ttl = 1800

    def is_monochrome(self, model: str, backdrop: str) -> bool:
        """
        Check if NFT has monochrome color combination.

        Args:
            model: NFT model name
            backdrop: NFT backdrop color

        Returns:
            bool: True if monochrome
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
                return True

        return False

    def is_premium_backdrop(self, backdrop: str) -> bool:
        """
        Check if backdrop is premium rarity.

        Args:
            backdrop: Backdrop color name

        Returns:
            bool: True if premium
        """
        if not backdrop:
            return False
        return backdrop.lower() in self.PREMIUM_BACKDROPS

    async def scan_new_listings(self) -> List[Gift]:
        """
        Scan marketplace for new NFT listings.

        Returns:
            List of new Gift instances
        """
        max_retries = 3

        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"Scanning NEW LISTINGS (attempt {attempt}/{max_retries})...")

                activities = await marketActivity(
                    activityType="listing",
                    sort="latest",
                    limit=20,
                    authData=self.auth_data
                )

                if not activities:
                    logger.warning("No activities returned from API")
                    return []

                logger.info(f"Received {len(activities)} new listings")

                new_gifts = []
                for activity in activities:
                    try:
                        gift_data = activity.get('gift', {})
                        gift_id = gift_data.get('id')

                        if not gift_id or gift_id in self.processed_ids:
                            continue

                        gift = Gift.from_api(gift_data)

                        logger.info(
                            f"NFT ID: {gift.id}, TG_ID: {gift.tg_id}, "
                            f"Price: {gift.price}, Listed: {activity.get('created_at')}"
                        )

                        new_gifts.append(gift)
                        self.processed_ids.add(gift_id)

                    except Exception as e:
                        logger.error(f"Error parsing gift: {e}")
                        continue

                logger.info(f"Found {len(new_gifts)} NEW listings")
                return new_gifts

            except Exception as e:
                logger.error(f"Error scanning listings (attempt {attempt}): {e}")
                if attempt < max_retries:
                    await asyncio.sleep(2 ** attempt)
                else:
                    return []

        return []

    async def get_model_floor(self, model: str) -> Optional[float]:
        """
        Get floor price for specific model.

        Args:
            model: NFT model name

        Returns:
            float: Floor price in TON, or None if not found
        """
        if not model:
            return None

        cache_key = f"floor_{model}"
        if cache_key in self.floor_cache:
            cached_time, cached_price = self.floor_cache[cache_key]
            if (datetime.now() - cached_time).seconds < self.cache_ttl:
                return cached_price

        try:
            logger.info(f"Getting floor for model: {model}")

            floors = await filterFloors(
                filters={'model': [model]},
                authData=self.auth_data
            )

            if floors:
                floor_price = float(floors[0].get('price', 0))
                logger.info(f"Model floor for {model}: {floor_price} TON")

                self.floor_cache[cache_key] = (datetime.now(), floor_price)
                return floor_price

            return None

        except Exception as e:
            logger.error(f"Error getting model floor: {e}")
            return None

    async def search_similar_nfts(
            self,
            model: str = None,
            backdrop: str = None
    ) -> List[Dict]:
        """
        Search for similar NFTs on marketplace.

        Args:
            model: Model filter (required)
            backdrop: Backdrop filter (optional)

        Returns:
            List of NFT dictionaries
        """
        if not model:
            return []

        try:
            if backdrop:
                logger.info(f"Searching: {model} + {backdrop}")
            else:
                logger.info(f"Searching: {model} (MODEL ONLY)")

            filters = {'model': [model]}
            if backdrop:
                filters['backdrop'] = [backdrop]

            results = await search(
                filters=filters,
                sort='price',
                limit=50,
                authData=self.auth_data
            )

            if results:
                logger.info(f"Found {len(results)} NFTs")
                for i, nft in enumerate(results[:3], 1):
                    attrs = nft.get('attributes', [])
                    nft_model = next(
                        (a['value'] for a in attrs if a.get('type') == 'model'),
                        'Unknown'
                    )
                    nft_backdrop = next(
                        (a['value'] for a in attrs if a.get('type') == 'backdrop'),
                        'Unknown'
                    )
                    logger.info(
                        f"   NFT #{i}: {nft.get('name')}, "
                        f"Model={nft_model}, Backdrop={nft_backdrop}, "
                        f"Price={nft.get('price')}"
                    )

            return results

        except Exception as e:
            logger.error(f"Search error: {e}")
            return []

    async def get_sales_history(
            self,
            gift_name: str,
            model: str = None,
            backdrop: str = None,
            days: int = 30
    ) -> List[Dict]:
        """
        Get sales history for similar NFTs.

        Args:
            gift_name: NFT name
            model: Model filter
            backdrop: Backdrop filter
            days: Number of days to look back

        Returns:
            List of sale dictionaries
        """
        try:
            filters = {}
            if model:
                filters['model'] = [model]
            if backdrop:
                filters['backdrop'] = [backdrop]

            activities = await marketActivity(
                activityType="sale",
                filters=filters,
                sort="latest",
                limit=50,
                authData=self.auth_data
            )

            if not activities:
                return []

            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

            sales = []
            for activity in activities:
                try:
                    sale_date_str = activity.get('created_at')
                    if not sale_date_str:
                        continue

                    sale_date = datetime.fromisoformat(
                        sale_date_str.replace('Z', '+00:00')
                    )

                    if sale_date < cutoff_date:
                        continue

                    gift = activity.get('gift', {})
                    price = float(gift.get('price', 0))

                    if price > 0:
                        sales.append({
                            'price': price,
                            'date': sale_date,
                            'name': gift.get('name')
                        })

                except Exception as e:
                    logger.error(f"Error parsing sale: {e}")
                    continue

            logger.info(f"Found {len(sales)} sales in last {days} days")
            return sales

        except Exception as e:
            logger.error(f"Error getting sales history: {e}")
            return []
