"""
Portals.gift Marketplace Monitor

Integration with Portals NFT marketplace API for:
- Real-time NFT listing scanning
- Sales history retrieval with strict filtering
- Model floor price tracking with caching
- Monochrome and premium backdrop detection

Author: Your Name
Repository: https://github.com/yourusername/nft-gift-bot
"""

import asyncio
import logging
import numpy as np
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Tuple

import config
from aportalsmp.gifts import search, marketActivity
from database import Gift

logger = logging.getLogger(__name__)


# ============================================================================
# MARKETPLACE MONITOR
# ============================================================================

class PortalsMonitor:
    """
    Monitors Portals.gift marketplace for NFT opportunities.

    Features:
    - Automatic rate limiting and retry logic with exponential backoff
    - Floor price caching (30s TTL)
    - Strict attribute filtering to prevent data pollution
    - Aggressive outlier removal (5x median threshold)
    - Comprehensive logging for debugging
    """

    def __init__(self):
        """Initialize Portals marketplace monitor."""
        self.auth_data = config.PORTALS_AUTH_TOKEN
        self.floor_cache: Dict[str, Tuple[float, float]] = {}  # {key: (price, timestamp)}
        self.search_cache: Dict[str, Tuple[List, float]] = {}
        self.cache_ttl = 30  # Cache validity in seconds
        self.api_semaphore = asyncio.Semaphore(10)  # Max concurrent API calls

    # ========================================================================
    # ATTRIBUTE DETECTION
    # ========================================================================

    def is_monochrome(self, model: str, backdrop: str) -> bool:
        """
        Check if NFT has monochrome color scheme (same color family).

        Args:
            model: NFT model name
            backdrop: NFT backdrop name

        Returns:
            True if model and backdrop share the same color family

        Example:
            >>> monitor.is_monochrome("Ruby Dragon", "Crimson Red")
            True  # Both are red family
        """
        if not model or not backdrop:
            return False

        # Color family definitions with comprehensive variants
        color_groups = {
            'red': ['red', 'crimson', 'scarlet', 'cherry', 'ruby', 'rose', 'burgundy', 'papaya'],
            'blue': ['blue', 'azure', 'navy', 'sapphire', 'cobalt', 'cyan', 'indigo', 'midnight'],
            'green': ['green', 'emerald', 'forest', 'jade', 'olive', 'lime', 'hunter'],
            'yellow': ['yellow', 'gold', 'golden', 'amber', 'lemon', 'pure gold'],
            'purple': ['purple', 'violet', 'lavender', 'plum', 'amethyst'],
            'pink': ['pink', 'rose', 'magenta', 'fuchsia'],
            'brown': ['brown', 'chocolate', 'coffee', 'tan', 'beige'],
            'gray': ['gray', 'grey', 'silver', 'steel', 'charcoal'],
            'black': ['black', 'onyx', 'ebony', 'midnight'],
            'white': ['white', 'ivory', 'pearl', 'snow']
        }

        model_lower = model.lower()
        backdrop_lower = backdrop.lower()

        # Check if both model and backdrop contain same color family
        for color_name, color_variations in color_groups.items():
            model_has_color = any(color in model_lower for color in color_variations)
            backdrop_has_color = any(color in backdrop_lower for color in color_variations)

            if model_has_color and backdrop_has_color:
                logger.debug(f"Monochrome detected: {model} + {backdrop} ({color_name} family)")
                return True

        return False

    def is_premium_backdrop(self, backdrop: str) -> bool:
        """
        Check if backdrop is premium/rare variant.

        Premium backdrops typically have 1.5x-3x floor price multipliers.

        Args:
            backdrop: Backdrop name

        Returns:
            True if backdrop is premium quality
        """
        if not backdrop:
            return False

        premium_backdrops = ['midnight blue', 'onyx black', 'black', 'golden', 'gunmetal']
        return backdrop.lower().strip() in premium_backdrops

    # ========================================================================
    # MARKETPLACE SCANNING
    # ========================================================================

    async def scan_new_gifts(self) -> List[Gift]:
        """
        Scan marketplace for new NFT listings.

        Features:
        - Automatic retry on failures (3 attempts)
        - Exponential backoff between retries (5s, 10s, 15s)
        - Price filtering based on config.MAX_PRICE_TON
        - Excludes bundled items and includes premarket

        Returns:
            List of Gift objects from recent listings
        """
        max_retries = 3

        for attempt in range(max_retries):
            try:
                logger.info(
                    f"Scanning latest gifts using search() "
                    f"(attempt {attempt + 1}/{max_retries})..."
                )

                # Exponential backoff on retry
                if attempt > 0:
                    wait_time = 5 * attempt
                    logger.info(f"Waiting {wait_time}s before retry...")
                    await asyncio.sleep(wait_time)

                # Apply rate limiting
                if hasattr(config, 'API_REQUEST_DELAY') and config.API_REQUEST_DELAY > 0:
                    await asyncio.sleep(config.API_REQUEST_DELAY)

                # Fetch recent listings
                nfts = await search(
                    sort="latest",
                    limit=50,
                    exclude_bundled=True,
                    premarket_status="all",
                    authData=self.auth_data
                )

                logger.info(f"Received {len(nfts)} NFTs from API")

                # Convert to Gift objects and filter by price
                gifts = []
                for nft in nfts:
                    # Price filter
                    if nft.price > config.MAX_PRICE_TON:
                        continue

                    # Extract attributes
                    attributes = []
                    if nft.model:
                        attributes.append({'type': 'model', 'value': nft.model})
                    if nft.backdrop:
                        attributes.append({'type': 'backdrop', 'value': nft.backdrop})
                    if nft.symbol:
                        attributes.append({'type': 'symbol', 'value': nft.symbol})

                    # Create Gift object
                    gift = Gift(
                        id=nft.id,
                        name=nft.name,
                        number=nft.tg_id,
                        price=float(nft.price),
                        collection_id=nft.collection_id,
                        photo_url=nft.photo_url,
                        attributes=attributes
                    )
                    gifts.append(gift)

                logger.info(f"Found {len(gifts)} new NFTs after filtering")
                return gifts

            except Exception as e:
                logger.error(
                    f"Error scanning gifts (attempt {attempt + 1}/{max_retries}): {e}"
                )
                if attempt == max_retries - 1:
                    logger.error("All retry attempts failed! Returning empty list.")
                    return []

        return []

    # ========================================================================
    # FLOOR PRICE TRACKING
    # ========================================================================

    async def get_model_floor(
            self,
            collection_name: str,
            model: str
    ) -> Optional[float]:
        """
        Get floor price for specific NFT model with 30s caching.

        Args:
            collection_name: NFT collection name
            model: Model name to check

        Returns:
            Floor price in TON, or None if not found
        """
        cache_key = f"{collection_name}:{model}"
        now = asyncio.get_event_loop().time()

        # Check cache first
        if cache_key in self.floor_cache:
            cached_floor, cached_time = self.floor_cache[cache_key]
            if now - cached_time < self.cache_ttl:
                logger.debug(f"Using cached floor for {model}: {cached_floor} TON")
                return cached_floor

        try:
            # Apply rate limiting
            if hasattr(config, 'API_REQUEST_DELAY') and config.API_REQUEST_DELAY > 0:
                await asyncio.sleep(config.API_REQUEST_DELAY)

            # Fetch cheapest listing for this model
            nfts = await search(
                gift_name=collection_name,
                model=model,
                sort="price_asc",
                limit=1,
                exclude_bundled=True,
                premarket_status="all",
                authData=self.auth_data
            )

            if nfts and len(nfts) > 0:
                floor = float(nfts[0].price)
                logger.info(f"Model floor for {model}: {floor} TON")

                # Update cache
                self.floor_cache[cache_key] = (floor, now)
                return floor

            logger.debug(f"No listings found for {model}")
            return None

        except Exception as e:
            logger.error(f"Error getting model floor for {model}: {e}")
            return None

    # ========================================================================
    # SIMILAR NFT SEARCH
    # ========================================================================

    async def search_similar_nfts(
            self,
            model: str = None,
            backdrop: str = None
    ) -> List[Dict]:
        """
        Search for NFTs with similar attributes.

        Args:
            model: Model name filter (optional)
            backdrop: Backdrop name filter (optional)

        Returns:
            List of NFT dictionaries matching criteria

        Note:
            Returns empty list if no model specified.
            Combines model+backdrop if both provided.
        """
        max_retries = 3

        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    await asyncio.sleep(3)

                # Apply rate limiting
                if hasattr(config, 'API_REQUEST_DELAY') and config.API_REQUEST_DELAY > 0:
                    await asyncio.sleep(config.API_REQUEST_DELAY)

                # Search with filters
                if model and backdrop:
                    logger.info(f"Searching: {model} + {backdrop}")
                    nfts = await search(
                        model=model,
                        backdrop=backdrop,
                        sort="price_asc",
                        limit=50,
                        exclude_bundled=True,
                        premarket_status="all",
                        authData=self.auth_data
                    )
                elif model:
                    logger.info(f"Searching: {model} (MODEL ONLY)")
                    nfts = await search(
                        model=model,
                        sort="price_asc",
                        limit=50,
                        exclude_bundled=True,
                        premarket_status="all",
                        authData=self.auth_data
                    )
                else:
                    logger.warning("No model specified for search")
                    return []

                logger.info(f"Found {len(nfts)} similar NFTs")

                # Log sample results
                if nfts:
                    sample_count = min(3, len(nfts))
                    for i, nft in enumerate(nfts[:sample_count]):
                        logger.debug(
                            f"  NFT #{i + 1}: {nft.name}, Model={nft.model}, "
                            f"Backdrop={nft.backdrop}, Price={nft.price}"
                        )

                return [self._nft_to_dict(nft) for nft in nfts]

            except Exception as e:
                logger.error(
                    f"Error searching NFTs (attempt {attempt + 1}/{max_retries}): {e}"
                )
                if attempt == max_retries - 1:
                    return []

        return []

    # ========================================================================
    # SALES HISTORY (CRITICAL - FIXED VERSION)
    # ========================================================================

    async def get_sales_history(
            self,
            collection_name: str,
            model: str = None,
            backdrop: str = None,
            days: int = 60
    ) -> List[Dict]:
        """
        Get sales history with STRICT filtering and aggressive outlier removal.

        **CRITICAL FIXES:**
        - EXACT string matching for model/backdrop (prevents cross-contamination)
        - Deduplication by (price, date, model, backdrop)
        - Aggressive outlier removal (5x median threshold)
        - Comprehensive logging for debugging

        Args:
            collection_name: NFT collection name
            model: Model name for EXACT matching (optional)
            backdrop: Backdrop name for EXACT matching (optional)
            days: Number of days of history to retrieve (default: 60)

        Returns:
            List of sale dictionaries with price, date, and attributes

        Example:
            >>> sales = await monitor.get_sales_history(
            ...     "Mousse Cake",
            ...     model="Checkmate",
            ...     backdrop="Midnight Blue"
            ... )
            >>> # Returns ONLY sales matching EXACTLY "Checkmate" + "Midnight Blue"
        """
        max_retries = 3

        for attempt in range(max_retries):
            try:
                logger.info(
                    f"Getting sales history for {collection_name} "
                    f"(attempt {attempt + 1}/{max_retries})"
                )

                # Exponential backoff
                if attempt > 0:
                    wait_time = (2 ** attempt)
                    logger.info(f"Waiting {wait_time}s before retry...")
                    await asyncio.sleep(wait_time)

                # Apply rate limiting
                if hasattr(config, 'API_REQUEST_DELAY') and config.API_REQUEST_DELAY > 0:
                    await asyncio.sleep(config.API_REQUEST_DELAY)

                # Fetch market activity
                activities = await marketActivity(
                    gift_name=collection_name,
                    model=model if model else None,
                    backdrop=backdrop if backdrop else None,
                    activityType="buy",
                    sort="latest",
                    limit=100,
                    authData=self.auth_data
                )

                cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
                sales = []
                filtered_count = 0

                # Process and filter sales
                for activity in activities:
                    try:
                        # Extract attributes
                        activity_model = (
                            activity.nft.model
                            if hasattr(activity.nft, 'model')
                            else None
                        )
                        activity_backdrop = (
                            activity.nft.backdrop
                            if hasattr(activity.nft, 'backdrop')
                            else None
                        )

                        # STRICT MODEL MATCHING (exact match only, case-insensitive)
                        if model:
                            if not activity_model:
                                filtered_count += 1
                                continue

                            if activity_model.lower().strip() != model.lower().strip():
                                filtered_count += 1
                                continue

                        # STRICT BACKDROP MATCHING (exact match only, case-insensitive)
                        if backdrop:
                            if not activity_backdrop:
                                filtered_count += 1
                                continue

                            if activity_backdrop.lower().strip() != backdrop.lower().strip():
                                filtered_count += 1
                                continue

                        # Parse timestamp with microseconds normalization
                        timestamp = activity.created_at.replace('Z', '+00:00')
                        if '.' in timestamp and '+' in timestamp:
                            parts = timestamp.split('.')
                            microseconds = parts[1].split('+')[0]

                            # Normalize microseconds to 6 digits
                            if len(microseconds) > 6:
                                microseconds = microseconds[:6]
                            elif len(microseconds) < 6:
                                microseconds = microseconds.ljust(6, '0')

                            timestamp = f"{parts[0]}.{microseconds}+00:00"

                        sale_date = datetime.fromisoformat(timestamp)

                        # Date filtering
                        if sale_date >= cutoff_date:
                            sales.append({
                                'price': float(activity.amount),
                                'date': sale_date,
                                'nft_name': activity.nft.name,
                                'model': activity_model,
                                'backdrop': activity_backdrop
                            })

                    except Exception as e:
                        logger.error(f"Error parsing sale activity: {e}")
                        continue

                total_received = len(activities)

                # Initial stats
                logger.info(
                    f"Found {len(sales)} MATCHING sales in last {days} days "
                    f"(filtered {filtered_count} non-matching from {total_received} total)"
                )

                if not sales:
                    logger.warning("No sales found matching criteria")
                    return []

                # Log raw prices BEFORE any filtering
                raw_prices = [s['price'] for s in sales]
                logger.info(f"📊 RAW PRICES (before dedup/outlier removal): {sorted(raw_prices)}")

                # ============================================================
                # STEP 1: DEDUPLICATION
                # ============================================================
                unique_sales = []
                seen = set()
                for s in sales:
                    # Key: (rounded_price, date, model, backdrop)
                    key = (
                        round(s['price'], 2),
                        s['date'].date(),
                        s.get('model'),
                        s.get('backdrop')
                    )
                    if key not in seen:
                        seen.add(key)
                        unique_sales.append(s)

                if len(unique_sales) < len(sales):
                    logger.info(
                        f"📊 Deduplication: {len(sales)} → {len(unique_sales)} "
                        f"(removed {len(sales) - len(unique_sales)} duplicates)"
                    )

                sales = unique_sales

                # ============================================================
                # STEP 2: AGGRESSIVE OUTLIER REMOVAL (2x median threshold)
                # ============================================================
                if len(sales) >= 3:
                    # Сортируем по дате (новые первые) для правильного median
                    sorted_by_date = sorted(sales, key=lambda x: x['date'], reverse=True)

                    # Берём последние 50% продаж для расчета "реального" median
                    recent_half = sorted_by_date[:max(len(sorted_by_date) // 2, 2)]
                    recent_prices = [s['price'] for s in recent_half]
                    median_price = np.median(recent_prices)

                    # АГРЕССИВНЫЙ outlier removal: 2x median от RECENT sales
                    absolute_cap = median_price * 2

                    before_count = len(sales)
                    sales = [s for s in sales if s['price'] <= absolute_cap]

                    if len(sales) < before_count:
                        logger.info(
                            f"🔪 Outlier removal: {before_count} → {len(sales)} "
                            f"(removed {before_count - len(sales)} sales >2x recent median={median_price:.2f})"
                        )

                    # Fallback: если слишком мало осталось, вернуть хотя бы 2 последние
                    if len(sales) < 2 and len(sorted_by_date) >= 2:
                        sales = sorted_by_date[:2]
                        logger.warning(f"⚠️ Too few sales after outlier removal, using 2 most recent")

                # ============================================================
                # STEP 3: FINAL VALIDATION & LOGGING
                # ============================================================
                if not sales:
                    logger.warning("No sales remaining after filtering!")
                    return []

                # Log final statistics
                final_prices = [s['price'] for s in sales]
                logger.info(f"📊 FINAL PRICES: {sorted([f'{p:.2f}' for p in final_prices])}")
                logger.info(
                    f"📊 Statistics: "
                    f"Count={len(sales)}, "
                    f"Min={min(final_prices):.2f}, "
                    f"Max={max(final_prices):.2f}, "
                    f"Avg={sum(final_prices) / len(final_prices):.2f}, "
                    f"Median={np.median(final_prices):.2f}"
                )

                # Log sample sales
                if len(sales) <= 5:
                    logger.info(f"📋 All {len(sales)} final sales:")
                    for i, s in enumerate(sales):
                        logger.info(
                            f"  Sale #{i + 1}: {s['price']:.2f} TON, "
                            f"Model={s['model']}, Backdrop={s['backdrop']}, "
                            f"Date={s['date'].strftime('%Y-%m-%d')}"
                        )
                else:
                    logger.info(f"📋 Sample (first 3 of {len(sales)} sales):")
                    for i, s in enumerate(sales[:3]):
                        logger.info(
                            f"  Sale #{i + 1}: {s['price']:.2f} TON, "
                            f"Model={s['model']}, Backdrop={s['backdrop']}, "
                            f"Date={s['date'].strftime('%Y-%m-%d')}"
                        )

                return sales

            except Exception as e:
                error_msg = str(e)

                # Categorize error types for better debugging
                if "SSL" in error_msg or "TLS" in error_msg:
                    logger.error(f"SSL/TLS error (attempt {attempt + 1}): {error_msg}")
                elif "Connection" in error_msg or "timeout" in error_msg.lower():
                    logger.error(f"Connection error (attempt {attempt + 1}): {error_msg}")
                elif "401" in error_msg or "auth" in error_msg.lower():
                    logger.error(f"Authentication error (attempt {attempt + 1}): {error_msg}")
                elif "429" in error_msg:
                    logger.error(f"Rate limit error (attempt {attempt + 1}): {error_msg}")
                else:
                    logger.error(f"API error (attempt {attempt + 1}): {error_msg}")

                if attempt == max_retries - 1:
                    logger.error(
                        f"All {max_retries} retry attempts failed for {collection_name}!"
                    )
                    return []

        return []

    # ========================================================================
    # UTILITIES
    # ========================================================================

    def _nft_to_dict(self, nft) -> Dict:
        """
        Convert NFT object to dictionary.

        Args:
            nft: NFT object from aportalsmp

        Returns:
            Dictionary with NFT data
        """
        return {
            'id': nft.id,
            'tg_id': nft.tg_id,
            'name': nft.name,
            'price': float(nft.price),
            'model': nft.model,
            'backdrop': nft.backdrop,
            'symbol': nft.symbol,
            'photo_url': nft.photo_url,
            'collection_id': nft.collection_id,
            'floor_price': float(nft.floor_price) if nft.floor_price else None
        }
