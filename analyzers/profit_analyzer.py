"""
NFT Profit Opportunity Analyzer v2.0

Advanced profit analysis for Telegram NFT marketplace with:
- Special number detection (rare IDs: #0, #69, #420, palindromes, etc.)
- Premium backdrop alerts (Onyx Black, Midnight Blue, Golden)
- Monochrome combination detection
- Smart target price calculation with outlier filtering
- Comprehensive sales history analysis

Author: Elchin Aliev
Repository: https://github.com/Elchin-bit/nft-arbitrage-bot
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Tuple

import aiohttp
import numpy as np
from colormath.color_conversions import convert_color
from colormath.color_objects import sRGBColor, HSVColor
from colorspacious import cspace_convert, deltaE
from curl_cffi import requests
from rlottie_python import LottieAnimation
from sklearn.cluster import KMeans

import config
from database import Gift, ProfitAnalysis

logger = logging.getLogger(__name__)

# Premium backdrops requiring special analysis
PREMIUM_BACKDROPS = ['midnight blue', 'onyx black', 'black', 'golden', 'gold', 'gunmetal']

# Premium backdrop multipliers for floor price alerts
PREMIUM_MULTIPLIERS = {
    'onyx black': 1.3,
    'black': 2.5,
    'midnight blue': 1.05,
    'golden': 2.0,
    'gunmetal': 1.06
}


# ==================== SPECIAL NUMBER DETECTION ====================

def detect_special_number(tg_id: str) -> Tuple[bool, float, str]:
    """
    Detect rare/special NFT numbers and calculate premium multipliers.

    Returns:
        (is_special, multiplier, description)
    """
    if not tg_id or not tg_id.isdigit():
        return False, 1.0, ""

    num = int(tg_id)

    # 🏆 ULTRA RARE (5x-20x multiplier)
    if num == 0:
        return True, 20.0, "GENESIS #0"
    elif num <= 9:
        return True, 10.0, f"Single Digit #{num}"
    elif num == 69:
        return True, 8.0, "Meme Number #69"
    elif num == 420:
        return True, 8.0, "Meme Number #420"
    elif num == 1337:
        return True, 6.0, "Elite Number #1337"

    # 🔥 VERY RARE (3x-5x multiplier)
    elif num <= 99:
        return True, 5.0, f"Double Digit #{num}"
    elif num == 100:
        return True, 4.0, "Century #100"

    # ⭐ RARE PATTERNS (2x-4x multiplier)
    elif is_all_same_digits(tg_id):
        length = len(tg_id)
        if length >= 5:
            return True, 5.0, f"Repeating Pattern #{tg_id}"
        elif length == 4:
            return True, 4.0, f"Quad Pattern #{tg_id}"
        elif length == 3:
            return True, 3.0, f"Triple Pattern #{tg_id}"
        else:
            return True, 2.5, f"Double Pattern #{tg_id}"

    # 💎 SPECIAL PATTERNS (1.5x-3x multiplier)
    elif is_palindrome(tg_id):
        return True, 2.0, f"Palindrome #{tg_id}"
    elif is_sequential(tg_id):
        return True, 2.0, f"Sequential #{tg_id}"

    return False, 1.0, ""


def is_all_same_digits(s: str) -> bool:
    """Check if all digits are the same (111, 2222)."""
    return len(set(s)) == 1


def is_palindrome(s: str) -> bool:
    """Check if number is palindrome (12321, 1221)."""
    return s == s[::-1] and len(s) >= 3


def is_sequential(s: str) -> bool:
    """Check if number is sequential (1234, 5678)."""
    if len(s) < 3:
        return False

    nums = [int(d) for d in s]
    ascending = all(nums[i] + 1 == nums[i + 1] for i in range(len(nums) - 1))
    descending = all(nums[i] - 1 == nums[i + 1] for i in range(len(nums) - 1))

    return ascending or descending


# ==================== SMART TARGET PRICE CALCULATION ====================

def calculate_smart_target_price(
        sales_history: List[Dict],
        is_premium: bool,
        is_monochrome: bool,
        current_backdrop: Optional[str] = None
) -> Optional[float]:
    """
    Calculate smart target price based on recent sales history.

    Features:
    - Filters last 30 days of sales
    - Removes extreme outliers (>3x median)
    - Applies premium/monochrome multipliers
    - Returns None if insufficient data

    Args:
        sales_history: List of sale dictionaries with 'price', 'date', 'backdrop'
        is_premium: Whether backdrop is premium
        is_monochrome: Whether combo is monochrome
        current_backdrop: Current NFT backdrop for comparison

    Returns:
        Target price in TON or None
    """
    if not sales_history:
        return None

    # Sort by date (newest first)
    sorted_sales = sorted(sales_history, key=lambda x: x['date'], reverse=True)
    recent_cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    # Filter to last 30 days
    relevant_sales = []
    for s in sorted_sales[:10]:
        try:
            sale_date = s['date']
            if sale_date.tzinfo is None:
                sale_date = sale_date.replace(tzinfo=timezone.utc)

            if sale_date >= recent_cutoff:
                relevant_sales.append(s)
        except Exception as e:
            logger.warning(f"Skipping sale with invalid date: {e}")
            continue

    # Fallback to last 3 sales if no recent sales
    if not relevant_sales:
        relevant_sales = sorted_sales[:3]

    prices = [s['price'] for s in relevant_sales]

    # Remove extreme outliers (>3x median)
    if len(prices) >= 3:
        median = np.median(prices)
        filtered = [p for p in prices if p <= median * 3]

        if len(filtered) >= 2:
            prices = filtered
            logger.info(f"📊 Outlier filtering: {len(relevant_sales)} → {len(prices)} prices")

    if not prices:
        return None

    # Calculate simple average (no weighted average)
    avg = sum(prices) / len(prices)

    # Apply multipliers
    if is_premium and is_monochrome:
        multiplier = 1.10
    elif is_monochrome:
        multiplier = 1.05
    else:
        multiplier = 1.0

    smart_target = avg * multiplier

    logger.info(f"💡 Smart Target: {smart_target:.2f} TON (avg: {avg:.2f}, multiplier: {multiplier})")
    logger.info(f"📊 Used {len(prices)} sales from last 30 days")

    return smart_target


# ==================== MAIN ANALYZER CLASS ====================

class ProfitAnalyzer:
    """Advanced NFT profit opportunity analyzer with color similarity detection."""

    def __init__(self):
        """Initialize analyzer with caching for performance."""
        self.market_cache = {}
        self.ton_usd_price = 0.0
        self.last_ton_update = None
        self.monochrome_cache = {}

    # ==================== COLOR ANALYSIS METHODS ====================

    async def get_lottie_data(self, short: str, num: int) -> dict:
        """Fetch Lottie animation data from NFT Fragment API."""
        try:
            url = f"https://nft.fragment.com/gift/{short}-{num}.lottie.json"
            response = requests.get(url, timeout=10)
            return response.json()
        except Exception as e:
            logger.debug(f"Failed to get Lottie data for {short}-{num}: {e}")
            return {"error": str(e)}

    async def get_bg_color(self, data: dict) -> Tuple[int, int, int]:
        """Extract background color from Lottie animation data."""
        if "error" in data:
            return (0, 0, 0)

        for layer in data.get("layers", []):
            if layer.get("nm") == "Background":
                for shape in layer.get("shapes", []):
                    for it in shape.get("it", []):
                        if it.get("ty") == "gf":
                            k = it.get("g", {}).get("k", {}).get("k", [])
                            if len(k) >= 4:
                                return tuple(round(v * 255) for v in k[1:4])
        return (0, 0, 0)

    async def remove_bg_pat_col(self, data: dict) -> dict:
        """Remove background, pattern and color icon layers from animation data."""
        layers_to_remove = {"Background", "Pattern", "Color Icon"}
        data["layers"] = [layer for layer in data.get("layers", [])
                          if layer.get("nm") not in layers_to_remove]
        return data

    async def get_dominant_color(self, data: dict) -> Tuple[int, int, int]:
        """Extract dominant color from NFT model using K-means clustering."""
        try:
            animation = LottieAnimation.from_data(json.dumps(data))
            image = animation.render_pillow_frame(frame_num=3).convert("RGBA")
            array = np.array(image)

            if array.shape[2] == 4:
                mask = array[:, :, 3] > 0
                rgb_pixels = array[:, :, :3][mask]

                if rgb_pixels.size == 0:
                    return (0, 0, 0)

                kmeans = KMeans(n_clusters=1, random_state=42).fit(rgb_pixels)
                return tuple(kmeans.cluster_centers_.astype(int)[0])

            return (0, 0, 0)
        except Exception as e:
            logger.debug(f"Failed to get dominant color: {e}")
            return (0, 0, 0)

    def calculate_similarity_percentage(
            self,
            delta: float,
            rgb_dist: float,
            bg_hsv: HSVColor,
            fg_hsv: HSVColor
    ) -> float:
        """Calculate color similarity percentage using multiple color spaces."""
        # CAM02-UCS similarity (perceptually accurate)
        cam_sim = 100 * np.exp(-delta ** 2 / (2 * 18.04))

        # RGB distance similarity
        rgb_sim = min(100, 100 - (rgb_dist / 150 * 100))

        # Hue similarity
        raw_hue_diff = abs(bg_hsv.hsv_h - fg_hsv.hsv_h)
        hue_diff = min(raw_hue_diff, 360 - raw_hue_diff)
        hue_sim = 100 - min(100, (hue_diff / 45 * 100))

        # Chroma similarity
        chroma_diff = abs(bg_hsv.hsv_s - fg_hsv.hsv_s)
        chroma_sim = 100 - min(100, (chroma_diff / 0.3 * 100))

        # Weight based on color saturation
        if bg_hsv.hsv_s < 0.2 and fg_hsv.hsv_s < 0.2:
            weights = [0.4, 0.3, 0.2, 0.1]
        else:
            weights = [0.5, 0.2, 0.2, 0.1]

        return round(
            weights[0] * cam_sim + weights[1] * rgb_sim +
            weights[2] * hue_sim + weights[3] * chroma_sim, 2
        )

    async def analyze_color_similarity(self, short: str, num: int) -> Dict:
        """Perform comprehensive color similarity analysis."""
        cache_key = f"{short}_{num}"
        if cache_key in self.monochrome_cache:
            return self.monochrome_cache[cache_key]

        try:
            data = await self.get_lottie_data(short, num)
            bg_color = await self.get_bg_color(data)
            data = await self.remove_bg_pat_col(data)
            fg_color = await self.get_dominant_color(data)

            if bg_color == (0, 0, 0) or fg_color == (0, 0, 0):
                result = {"similarity": 0, "error": "Failed to extract colors"}
                self.monochrome_cache[cache_key] = result
                return result

            # Convert to CAM02-UCS
            bg_cam = cspace_convert(bg_color, "sRGB255", "CAM02-UCS")
            fg_cam = cspace_convert(fg_color, "sRGB255", "CAM02-UCS")
            delta_e = float(deltaE(bg_cam, fg_cam))
            rgb_distance = np.linalg.norm(np.array(bg_color) - np.array(fg_color))

            # Convert to HSV
            bg_rgb = sRGBColor(*bg_color, is_upscaled=True)
            fg_rgb = sRGBColor(*fg_color, is_upscaled=True)
            bg_hsv = convert_color(bg_rgb, HSVColor)
            fg_hsv = convert_color(fg_rgb, HSVColor)

            similarity = self.calculate_similarity_percentage(delta_e, rgb_distance, bg_hsv, fg_hsv)

            result = {
                "similarity": similarity,
                "deltaE": round(delta_e, 2),
                "rgbDistance": round(rgb_distance, 2),
                "hueDifference": round(abs(bg_hsv.hsv_h - fg_hsv.hsv_h), 2),
                "chromaDifference": round(abs(bg_hsv.hsv_s - fg_hsv.hsv_s), 2),
                "bgColor": bg_color,
                "giftColor": fg_color
            }

            self.monochrome_cache[cache_key] = result
            return result

        except Exception as e:
            logger.debug(f"Color similarity analysis failed for {short}-{num}: {e}")
            result = {"similarity": 0, "error": str(e)}
            self.monochrome_cache[cache_key] = result
            return result

    # ==================== MONOCHROME DETECTION ====================

    async def is_monochrome_advanced(self, gift_name: str, nft_id: Optional[str] = None) -> bool:
        """Advanced monochrome detection using color similarity analysis (65% threshold)."""
        try:
            name_mapping = {
                "birthday candle": "bdaycandle",
                "b-day candle": "bdaycandle",
                "jack in the box": "jackinthebox",
                "durov's cap": "durovscap",
                "lol pop": "lolpop",
                "candy cane": "candycane",
                "restless jar": "restlessjar",
            }

            gift_lower = gift_name.lower()
            short_name = name_mapping.get(gift_lower)

            if not short_name:
                logger.debug(f"No short name mapping for gift: {gift_name}")
                return False

            gift_num = int(nft_id) if nft_id and nft_id.isdigit() else 1

            analysis = await self.analyze_color_similarity(short_name, gift_num)
            similarity = analysis.get("similarity", 0)

            is_mono = similarity >= 65.0

            if is_mono:
                logger.info(f"🎨 Advanced monochrome detected: {gift_name} (similarity: {similarity}%)")

            return is_mono

        except Exception as e:
            logger.debug(f"Advanced monochrome check failed for {gift_name}: {e}")
            return False

    def is_monochrome_simple(self, model: str, backdrop: str) -> bool:
        """Simple monochrome detection using color name matching (fallback method)."""
        if not model or not backdrop:
            return False

        color_groups = {
            'red': ['red', 'crimson', 'scarlet', 'cherry', 'ruby', 'rose', 'burgundy', 'papaya'],
            'blue': ['blue', 'azure', 'navy', 'sapphire', 'cobalt', 'cyan', 'indigo', 'midnight'],
            'green': ['green', 'emerald', 'forest', 'jade', 'olive', 'lime', 'malachite'],
            'yellow': ['yellow', 'gold', 'golden', 'amber', 'lemon'],
            'purple': ['purple', 'violet', 'lavender', 'plum', 'amethyst'],
            'pink': ['pink', 'rose', 'magenta', 'fuchsia'],
            'orange': ['orange', 'coral', 'peach', 'tangerine'],
            'brown': ['brown', 'chocolate', 'coffee', 'sepia', 'tan'],
            'gray': ['gray', 'grey', 'silver', 'charcoal', 'gunmetal'],
            'white': ['white', 'ivory', 'cream', 'pearl'],
            'black': ['black', 'onyx']
        }

        model_lower = model.lower()
        backdrop_lower = backdrop.lower()

        for color_group in color_groups.values():
            model_match = any(color in model_lower for color in color_group)
            backdrop_match = any(color in backdrop_lower for color in color_group)

            if model_match and backdrop_match:
                logger.info(f"🎨 Simple monochrome detected: {model} + {backdrop}")
                return True

        return False

    async def is_monochrome(
            self,
            model: str,
            backdrop: str,
            gift_name: str = None,
            nft_id: str = None
    ) -> bool:
        """Main monochrome detection (tries advanced, falls back to simple)."""
        if gift_name:
            try:
                result = await self.is_monochrome_advanced(gift_name, nft_id)
                if result:
                    return True
            except Exception as e:
                logger.debug(f"Advanced monochrome failed, using simple method: {e}")

        return self.is_monochrome_simple(model, backdrop)

    def is_premium_backdrop(self, backdrop: str) -> bool:
        """Check if backdrop is premium rarity."""
        if not backdrop:
            return False
        return backdrop.lower() in PREMIUM_BACKDROPS

    # ==================== TON PRICE FETCHING ====================

    async def get_ton_usd_price(self) -> float:
        """Fetch current TON/USD exchange rate (5-minute cache)."""
        try:
            if (self.last_ton_update and
                    (datetime.now() - self.last_ton_update).seconds < 300):
                return self.ton_usd_price

            url = "https://api.coingecko.com/api/v3/simple/price"
            params = {'ids': 'the-open-network', 'vs_currencies': 'usd'}

            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        price = data.get('the-open-network', {}).get('usd', 0)
                        if price > 0:
                            self.ton_usd_price = float(price)
                            self.last_ton_update = datetime.now()
                            logger.info(f"TON/USD rate updated: ${self.ton_usd_price:.2f}")
                            return self.ton_usd_price

        except Exception as e:
            logger.warning(f"Failed to fetch TON/USD rate: {e}")

        return self.ton_usd_price if self.ton_usd_price > 0 else 5.5

    # ==================== MAIN ANALYSIS METHOD ====================

    async def analyze_profit_opportunity(
            self,
            gift: Gift,
            portals_monitor
    ) -> Optional[ProfitAnalysis]:
        """
        Comprehensive profit opportunity analysis.

        Returns ProfitAnalysis if profitable opportunity found, else None.
        """
        try:
            logger.info("=" * 60)
            logger.info(f"Analyzing: {gift.name}")

            # Check special number
            is_special, number_multiplier, number_description = detect_special_number(str(gift.tg_id))

            if is_special:
                logger.info(f"🔢 {number_description} (multiplier: {number_multiplier}x)")

                # Ultra rare numbers get special alert
                if number_multiplier >= 5.0:
                    logger.info(f"🚨 ULTRA RARE NUMBER ALERT!")
                    return ProfitAnalysis(
                        gift_id=gift.id,
                        profit_percent=(number_multiplier - 1) * 100,
                        profit_ton=gift.price * (number_multiplier - 1),
                        risk_score=0.1,
                        confidence=0.95,
                        strategy="🔢 SPECIAL NUMBER ALERT",
                        reasoning=f"{number_description} - Ultra rare with {number_multiplier}x premium",
                        target_price=gift.price * number_multiplier
                    )

            # Initialize variables
            target_price = None
            avg_sale_price = None
            recent_sales = []
            sales_history = None
            confidence_score = 0.8

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

            logger.info(f"Model: {model}, Backdrop: {backdrop}, Symbol: {symbol}")
            logger.info(f"Current price: {gift.price} TON")

            # Check price limits
            if gift.price > config.MAX_PRICE_TON:
                logger.warning(f"Price {gift.price} TON exceeds limit {config.MAX_PRICE_TON}")
                return None

            # Analyze backdrop and monochrome
            is_premium = self.is_premium_backdrop(backdrop)
            is_monochrome = await self.is_monochrome(model, backdrop, gift.name, gift.id)

            if is_premium:
                logger.info(f"✨ Premium backdrop: {backdrop}")
            if is_monochrome:
                logger.info(f"🎨 Monochrome combination detected!")

            # Get sales history
            use_combo_strategy = is_premium or is_monochrome

            try:
                if use_combo_strategy:
                    # Для premium/monochrome: модель + фон
                    sales_history = await portals_monitor.get_sales_history(
                        collection_name=gift.name,
                        model=model,
                        backdrop=backdrop
                    )
                else:
                    # Для обычных: ТОЛЬКО модель (БЕЗ backdrop!)
                    sales_history = await portals_monitor.get_sales_history(
                        collection_name=gift.name,
                        model=model,
                        backdrop=None  # ← НЕ фильтруем по backdrop!
                    )


            except Exception as e:
                logger.error(f"Error getting sales history: {e}")

            # Premium floor alert logic
            premium_floor_target = None

            if is_premium:
                try:
                    model_floor = await portals_monitor.get_model_floor(gift.name, model)

                    if model_floor and model_floor > 0:
                        price_to_floor_ratio = gift.price / model_floor
                        backdrop_lower = backdrop.lower().strip()
                        expected_multiplier = PREMIUM_MULTIPLIERS.get(backdrop_lower, 2.0)

                        logger.info(
                            f"🔍 Premium floor check: {price_to_floor_ratio:.2f}x (threshold: {expected_multiplier}x)"
                        )

                        if price_to_floor_ratio <= expected_multiplier:
                            # Рассчитываем premium floor target
                            premium_floor_target = model_floor * (expected_multiplier + 0.5)

                            # Проверяем reasonability vs sales history
                            if sales_history and len(sales_history) > 2:
                                recent_prices = [sale['price'] for sale in sales_history[-5:]]
                                avg_recent = sum(recent_prices) / len(recent_prices)

                                if gift.price > avg_recent * 1.1:
                                    logger.warning(
                                        f"❌ Premium floor alert: Price {gift.price:.2f} > recent avg {avg_recent:.2f}, "
                                        f"but calculated target {premium_floor_target:.2f} TON"
                                    )
                                    # НЕ обнуляем premium_floor_target - используем позже!
                                else:
                                    logger.info(
                                        f"💎 Premium floor target: {premium_floor_target:.2f} TON "
                                        f"(floor {model_floor:.2f} * {expected_multiplier + 0.5:.2f})"
                                    )
                            else:
                                logger.info(
                                    f"💎 Premium floor target: {premium_floor_target:.2f} TON "
                                    f"(no sales history for validation)"
                                )

                except Exception as e:
                    logger.warning(f"Failed to check premium floor: {e}")

            # Continue with regular analysis

            if use_combo_strategy:
                similar_nfts = await portals_monitor.search_similar_nfts(model=model, backdrop=backdrop)
                strategy_type = "Premium backdrop" if is_premium else "Monochrome"
            else:
                similar_nfts = await portals_monitor.search_similar_nfts(model=model)
                strategy_type = "Model arbitrage"

                model_floor = await portals_monitor.get_model_floor(gift.name, model)
                if model_floor and gift.price > model_floor * 1.05:
                    logger.warning(f"Price {gift.price} > model floor {model_floor}")
                    return None

            # Handle rare combos (1 NFT in market)
            if use_combo_strategy and (not similar_nfts or len(similar_nfts) <= 1):
                logger.info(f"🔥 RARE COMBO detected!")

                if not sales_history or len(sales_history) < 2:
                    logger.warning(f"Insufficient sales history for rare combo")
                    return None

                logger.info(f"Found {len(sales_history)} historical sales")

                sale_prices = [s['price'] for s in sales_history]
                avg_sale_price = sum(sale_prices) / len(sale_prices)
                recent_sales = [s for s in sales_history
                                if (datetime.now(s['date'].tzinfo) - s['date']).days <= 30]

                if recent_sales:
                    recent_avg = sum(s['price'] for s in recent_sales) / len(recent_sales)
                    target_price = recent_avg * 1.25
                else:
                    target_price = avg_sale_price * 1.30

                if gift.price > avg_sale_price * 1.2:
                    logger.warning(f"Price too high vs historical avg")
                    return None

            else:
                # Normal logic
                if not similar_nfts or len(similar_nfts) < 2:
                    logger.warning(f"Insufficient similar NFTs")
                    return None

                logger.info(f"Found {len(similar_nfts)} similar NFTs")

                prices = sorted([float(nft['price']) for nft in similar_nfts if nft.get('price', 0) > 0])

                if len(prices) < 2:
                    logger.warning("Insufficient price data")
                    return None

                min_price = prices[0]
                logger.info(f"Floor price: {min_price:.2f} TON")

                if gift.price < min_price:
                    logger.info("✅ This is the cheapest!")
                    target_price = prices[1] if len(prices) > 1 else prices[0] * 1.05
                elif gift.price == min_price:
                    logger.info("✅ Tied for cheapest")
                    # ВСЕГДА берём next NFT price как target
                    target_price = prices[1] if len(prices) > 1 else min_price * 1.05
                else:
                    logger.warning(f"Not competitive - Current: {gift.price}, Floor: {min_price}")
                    return None

            # Calculate smart target
            # Calculate smart target from sales history
            smart_target = calculate_smart_target_price(
                sales_history,
                is_premium,
                is_monochrome,
                backdrop
            )

            # Determine final target price
            final_target = None

            # Option 1: Next NFT price (from market listings)
            next_nft_price = None
            if len(prices) > 1:
                next_nft_price = prices[1]
                logger.info(f"💰 Next NFT price: {next_nft_price:.2f} TON")

            # Option 2: Smart target from sales history
            if smart_target:
                logger.info(f"📊 Smart target from sales: {smart_target:.2f} TON")

            # Option 3: Premium floor target (if available)
            if premium_floor_target:
                logger.info(f"💎 Premium floor target: {premium_floor_target:.2f} TON")

            # Choose LOWEST (most conservative) target
            candidates = []

            if next_nft_price:
                candidates.append(("Next NFT price", next_nft_price))

            if smart_target:
                candidates.append(("Smart target", smart_target))

            if premium_floor_target:
                candidates.append(("Premium floor", premium_floor_target))

            if candidates:
                # Sort by price (lowest first)
                candidates.sort(key=lambda x: x[1])
                chosen_strategy, final_target = candidates[0]

                logger.info(
                    f"✅ Using {chosen_strategy}: {final_target:.2f} TON "
                    f"(other options: {', '.join([f'{s}: {p:.2f}' for s, p in candidates[1:]])})"
                )

                target_price = final_target

            else:
                # Fallback
                if target_price is None:
                    logger.warning("No target price calculated, using fallback")
                    if use_combo_strategy and recent_sales:
                        recent_avg = sum([s['price'] for s in recent_sales]) / len(recent_sales)
                        target_price = recent_avg * 1.25
                    elif avg_sale_price is not None:
                        target_price = avg_sale_price * 1.30
                    else:
                        target_price = gift.price * 1.05
                    logger.info(f"📈 Using fallback target: {target_price:.2f} TON")

            # Calculate profits
            gross_profit = target_price - gift.price
            gross_profit_percent = (gross_profit / gift.price) * 100

            commission = target_price * 0.05
            net_profit = gross_profit - commission
            net_profit_percent = (net_profit / gift.price) * 100

            logger.info(f"Gross profit: {gross_profit:.2f} TON ({gross_profit_percent:.1f}%)")
            logger.info(f"Commission: {commission:.2f} TON")
            logger.info(f"Net profit: {net_profit:.2f} TON ({net_profit_percent:.1f}%)")

            MIN_PROFIT_THRESHOLD = 20
            if net_profit_percent < MIN_PROFIT_THRESHOLD:
                logger.warning(f"Net profit {net_profit_percent:.1f}% below {MIN_PROFIT_THRESHOLD}%")
                return None

            confidence_score = 0.85 if use_combo_strategy and len(similar_nfts or []) <= 1 else 0.8

            logger.info("🎯 PROFITABLE OPPORTUNITY IDENTIFIED!")
            logger.info(f"Strategy: {strategy_type}")
            logger.info(f"Confidence: {confidence_score:.0%}")
            logger.info("=" * 60)

            reasoning = (f"Buy {gift.price:.2f} TON, Sell {target_price:.2f} TON, "
                         f"Net profit {net_profit:.2f} TON ({net_profit_percent:.1f}%)")

            if sales_history:
                reasoning += f", Sales: {len(sales_history)} total, {len(recent_sales)} recent"

            return ProfitAnalysis(
                gift_id=gift.id,
                profit_percent=net_profit_percent,
                profit_ton=net_profit,
                risk_score=1.0 - confidence_score,
                confidence=confidence_score,
                strategy=strategy_type,
                reasoning=reasoning,
                target_price=target_price
            )

        except Exception as e:
            logger.error(f"Analysis failed for {gift.name}: {e}")
            import traceback
            traceback.print_exc()
            return None
