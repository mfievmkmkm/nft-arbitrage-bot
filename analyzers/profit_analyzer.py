"""
NFT profit opportunity analyzer - FIXED VERSION.

Analyzes NFT pricing, floor prices, monochrome combinations,
and calculates potential profit after marketplace fees.

Fixes:
- ✅ Fixed 'recent_sales referenced before assignment' error
- ✅ Improved variable initialization and scope handling
- ✅ Better error handling and logging
- ✅ Consistent variable naming (recent_sales vs recentsales)
- ✅ Fixed target_price fallback logic
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

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


# ===== SPECIAL NUMBER DETECTION FUNCTIONS =====
def detect_special_number(tg_id: str) -> tuple[bool, float, str]:
    """
    Детекция особенных номеров и их мультипликаторов
    Returns: (is_special, multiplier, description)
    """
    if not tg_id or not tg_id.isdigit():
        return False, 1.0, ""

    num = int(tg_id)

    # 🏆 СУПЕР РЕДКИЕ (5x-20x)
    if num == 0:
        return True, 20.0, "GENESIS #0"
    elif num <= 9:  # 1-9
        return True, 10.0, f"Single Digit #{num}"
    elif num == 69:
        return True, 8.0, "Meme Number #69"
    elif num == 420:
        return True, 8.0, "Meme Number #420"
    elif num == 1337:
        return True, 6.0, "Elite Number #1337"

    # 🔥 ОЧЕНЬ РЕДКИЕ (3x-5x)
    elif num <= 99:  # 10-99
        return True, 5.0, f"Double Digit #{num}"
    elif num == 100:
        return True, 4.0, "Century #100"

    # ⭐ РЕДКИЕ ПАТТЕРНЫ (2x-4x)
    elif is_all_same_digits(tg_id):
        length = len(tg_id)
        if length >= 5:  # 77777, 888888
            return True, 5.0, f"Repeating Pattern #{tg_id}"
        elif length == 4:  # 7777, 8888
            return True, 4.0, f"Quad Pattern #{tg_id}"
        elif length == 3:  # 777, 888
            return True, 3.0, f"Triple Pattern #{tg_id}"
        else:  # 77, 88
            return True, 2.5, f"Double Pattern #{tg_id}"

    # 💎 ОСОБЫЕ ПАТТЕРНЫ (1.5x-3x)
    elif is_palindrome(tg_id):
        return True, 2.0, f"Palindrome #{tg_id}"
    elif is_sequential(tg_id):
        return True, 2.0, f"Sequential #{tg_id}"

    return False, 1.0, ""


def is_all_same_digits(s: str) -> bool:
    """111, 2222"""
    return len(set(s)) == 1


def is_palindrome(s: str) -> bool:
    """12321, 1221"""
    return s == s[::-1] and len(s) >= 3


def is_sequential(s: str) -> bool:
    """1234, 5678"""
    if len(s) < 3:
        return False

    nums = [int(d) for d in s]
    # Возрастающая последовательность
    ascending = all(nums[i] + 1 == nums[i + 1] for i in range(len(nums) - 1))
    # Убывающая последовательность
    descending = all(nums[i] - 1 == nums[i + 1] for i in range(len(nums) - 1))

    return ascending or descending


def calculate_smart_target_price(sales_history, is_premium, is_monochrome, current_backdrop=None):
    """Умный расчёт target price с фильтрацией по backdrop"""
    if not sales_history:
        return None

    # Сортируем по дате (новые первые)
    sorted_sales = sorted(sales_history, key=lambda x: x['date'], reverse=True)

    from datetime import timezone
    recent_cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    # НОВАЯ ЛОГИКА: фильтруем только ПОХОЖИЕ backdrop-ы
    relevant_sales = []
    for s in sorted_sales[:10]:  # Берём топ-10 последних
        try:
            sale_date = s['date']
            if sale_date.tzinfo is None:
                sale_date = sale_date.replace(tzinfo=timezone.utc)

            if sale_date >= recent_cutoff:
                # Проверяем backdrop similarity
                sale_backdrop = s.get('backdrop', '').lower()
                current_backdrop_lower = (current_backdrop or '').lower()

                # Фильтруем только если backdrop сильно отличается от премиума
                premium_backdrops = ['onyx black', 'black', 'midnight blue', 'golden', 'gunmetal']

                sale_is_premium = any(pb in sale_backdrop for pb in premium_backdrops)
                current_is_premium = any(pb in current_backdrop_lower for pb in premium_backdrops)

                # Исключаем продажи с СИЛЬНО разным типом backdrop
                if sale_is_premium == current_is_premium or abs(s['price'] - sales_history[0]['price']) < 20:
                    relevant_sales.append(s)
                else:
                    logger.info(f"🚫 Filtered outlier sale: {s['price']} TON (backdrop: {sale_backdrop})")

        except Exception as e:
            logger.warning(f"Skipping sale with invalid date: {e}")
            continue

    if not relevant_sales:
        # Fallback к последним 3 продажам
        relevant_sales = sorted_sales[:3]

    prices = [s['price'] for s in relevant_sales]

    # Дополнительная фильтрация Q95
    if len(prices) >= 3:
        q95 = np.percentile(prices, 95)
        filtered_prices = [p for p in prices if p <= q95]
        if filtered_prices:
            prices = filtered_prices
            logger.info(f"📊 Outlier filtering: {len(relevant_sales)} → {len(prices)} prices")

    # Остальная логика без изменений...
    weights = [1.0] * len(prices)
    weighted_avg = sum(p * w for p, w in zip(prices, weights)) / sum(weights)

    if is_premium and is_monochrome:
        multiplier = 1.10  # Уменьшено с 1.15
    elif is_monochrome:
        multiplier = 1.05
    else:
        multiplier = 1.0  # Premium сам по себе НЕ дает преимущество

    smart_target = weighted_avg * multiplier

    logger.info(f"💡 Smart Target: {smart_target:.2f} TON (weighted_avg: {weighted_avg:.2f}, multiplier: {multiplier})")
    logger.info(f"📊 Relevant sales: {len(relevant_sales)}, filtered prices: {len(prices)}")

    return smart_target


logger = logging.getLogger(__name__)

# Premium backdrops that require combo analysis
PREMIUM_BACKDROPS = ['midnight blue', 'onyx black', 'black', 'golden', 'gold']


class ProfitAnalyzer:
    """Advanced NFT profit opportunity analyzer with color similarity detection."""

    def __init__(self):
        """Initialize analyzer with caching for performance."""
        self.market_cache = {}
        self.ton_usd_price = 0.0
        self.last_ton_update = None
        self.monochrome_cache = {}

    async def get_lottie_data(self, short: str, num: int) -> dict:
        """Fetch Lottie animation data from NFT Fragment API."""
        try:
            url = f"https://nft.fragment.com/gift/{short}-{num}.lottie.json"
            response = requests.get(url, timeout=10)
            return response.json()
        except Exception as e:
            logger.debug(f"Failed to get Lottie data for {short}-{num}: {e}")
            return {"error": str(e)}

    async def get_bg_color(self, data: dict) -> tuple[int, int, int]:
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
        data["layers"] = [layer for layer in data.get("layers", []) if layer.get("nm") not in layers_to_remove]
        return data

    async def get_dominant_color(self, data: dict) -> tuple[int, int, int]:
        """Extract dominant color from NFT model using K-means clustering."""
        try:
            animation = LottieAnimation.from_data(json.dumps(data))
            image = animation.render_pillow_frame(frame_num=3).convert("RGBA")
            array = np.array(image)

            if array.shape[2] == 4:
                # Consider only non-transparent pixels
                mask = array[:, :, 3] > 0
                rgb_pixels = array[:, :, :3][mask]

                if rgb_pixels.size == 0:
                    return (0, 0, 0)

                # Use K-means to find dominant color
                kmeans = KMeans(n_clusters=1, random_state=42).fit(rgb_pixels)
                return tuple(kmeans.cluster_centers_.astype(int)[0])

            return (0, 0, 0)
        except Exception as e:
            logger.debug(f"Failed to get dominant color: {e}")
            return (0, 0, 0)

    def calculate_similarity_percentage(self, delta: float, rgb_dist: float, bg_hsv, fg_hsv) -> float:
        """Calculate color similarity percentage using multiple color spaces."""
        # CAM02-UCS similarity (most perceptually accurate)
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
            # For unsaturated colors (gray, white, black)
            weights = [0.4, 0.3, 0.2, 0.1]
        else:
            # For saturated colors
            weights = [0.5, 0.2, 0.2, 0.1]

        return round(weights[0] * cam_sim + weights[1] * rgb_sim + weights[2] * hue_sim + weights[3] * chroma_sim, 2)

    async def analyze_color_similarity(self, short: str, num: int) -> dict:
        """Perform comprehensive color similarity analysis between background and model."""
        # Check cache first
        cache_key = f"{short}_{num}"
        if cache_key in self.monochrome_cache:
            return self.monochrome_cache[cache_key]

        try:
            # Get animation data
            data = await self.get_lottie_data(short, num)

            # Extract background color
            bg_color = await self.get_bg_color(data)

            # Remove background and get model color
            data = await self.remove_bg_pat_col(data)
            fg_color = await self.get_dominant_color(data)

            if bg_color == (0, 0, 0) or fg_color == (0, 0, 0):
                result = {"similarity": 0, "error": "Failed to extract colors"}
                self.monochrome_cache[cache_key] = result
                return result

            # Convert to CAM02-UCS color space for accurate comparison
            bg_cam = cspace_convert(bg_color, "sRGB255", "CAM02-UCS")
            fg_cam = cspace_convert(fg_color, "sRGB255", "CAM02-UCS")

            # Calculate deltaE (color difference)
            delta_e = float(deltaE(bg_cam, fg_cam))
            rgb_distance = np.linalg.norm(np.array(bg_color) - np.array(fg_color))

            # Convert to HSV for additional analysis
            bg_rgb = sRGBColor(*bg_color, is_upscaled=True)
            fg_rgb = sRGBColor(*fg_color, is_upscaled=True)
            bg_hsv = convert_color(bg_rgb, HSVColor)
            fg_hsv = convert_color(fg_rgb, HSVColor)

            # Calculate similarity
            similarity = self.calculate_similarity_percentage(delta_e, rgb_distance, bg_hsv, fg_hsv)

            result = {"similarity": similarity, "deltaE": round(delta_e, 2), "rgbDistance": round(rgb_distance, 2),
                      "hueDifference": round(abs(bg_hsv.hsv_h - fg_hsv.hsv_h), 2),
                      "chromaDifference": round(abs(bg_hsv.hsv_s - fg_hsv.hsv_s), 2), "bgColor": bg_color,
                      "giftColor": fg_color}

            # Cache result
            self.monochrome_cache[cache_key] = result
            return result

        except Exception as e:
            logger.debug(f"Color similarity analysis failed for {short}-{num}: {e}")
            result = {"similarity": 0, "error": str(e)}
            self.monochrome_cache[cache_key] = result
            return result

    async def is_monochrome_advanced(self, gift_name: str, nft_id: Optional[str] = None) -> bool:
        """
        Advanced monochrome detection using color similarity analysis.

        Args:
            gift_name: NFT collection name
            nft_id: NFT ID if available

        Returns:
            bool: True if monochrome (similarity > 65%)
        """
        try:
            # Map gift names to short names for Fragment API
            name_mapping = {"birthday candle": "bdaycandle", "b-day candle": "bdaycandle",
                            "jack in the box": "jackinthebox", "durov's cap": "durovscap", "lol pop": "lolpop",
                            "candy cane": "candycane", "restless jar": "restlessjar",  # Add more mappings as needed
                            }

            gift_lower = gift_name.lower()
            short_name = name_mapping.get(gift_lower)

            if not short_name:
                logger.debug(f"No short name mapping for gift: {gift_name}")
                return False

            # Use NFT ID or default to 1 for testing
            gift_num = int(nft_id) if nft_id and nft_id.isdigit() else 1

            # Analyze color similarity
            analysis = await self.analyze_color_similarity(short_name, gift_num)
            similarity = analysis.get("similarity", 0)

            # Threshold of 65% for monochrome detection
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

        color_groups = {'red': ['red', 'crimson', 'scarlet', 'cherry', 'ruby', 'rose', 'burgundy', 'papaya'],
                        'blue': ['blue', 'azure', 'navy', 'sapphire', 'cobalt', 'cyan', 'indigo', 'midnight'],
                        'green': ['green', 'emerald', 'forest', 'jade', 'olive', 'lime', 'malachite'],
                        'yellow': ['yellow', 'gold', 'golden', 'amber', 'lemon'],
                        'purple': ['purple', 'violet', 'lavender', 'plum', 'amethyst'],
                        'pink': ['pink', 'rose', 'magenta', 'fuchsia'],
                        'orange': ['orange', 'coral', 'peach', 'tangerine'],
                        'brown': ['brown', 'chocolate', 'coffee', 'sepia', 'tan'],
                        'gray': ['gray', 'grey', 'silver', 'charcoal', 'gunmetal'],
                        'white': ['white', 'ivory', 'cream', 'pearl'], 'black': ['black', 'onyx']}

        model_lower = model.lower()
        backdrop_lower = backdrop.lower()

        for color_group in color_groups.values():
            model_match = any(color in model_lower for color in color_group)
            backdrop_match = any(color in backdrop_lower for color in color_group)

            if model_match and backdrop_match:
                logger.info(f"🎨 Simple monochrome detected: {model} + {backdrop}")
                return True

        return False

    async def is_monochrome(self, model: str, backdrop: str, gift_name: str = None, nft_id: str = None) -> bool:
        """
        Main monochrome detection method.
        Tries advanced analysis first, falls back to simple method.
        """
        # Try advanced analysis first
        if gift_name:
            try:
                result = await self.is_monochrome_advanced(gift_name, nft_id)
                if result:
                    return True
            except Exception as e:
                logger.debug(f"Advanced monochrome failed, using simple method: {e}")

        # Fallback to simple detection
        return self.is_monochrome_simple(model, backdrop)

    def is_premium_backdrop(self, backdrop: str) -> bool:
        """Check if backdrop is premium rarity (requires combo analysis)."""
        if not backdrop:
            return False

        backdrop_lower = backdrop.lower()
        return backdrop_lower in PREMIUM_BACKDROPS

    async def get_ton_usd_price(self) -> float:
        """Fetch current TON/USD exchange rate with 5-minute cache."""
        try:
            if (self.last_ton_update and (datetime.now() - self.last_ton_update).seconds < 300):
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

    async def analyze_profit_opportunity(self, gift: Gift, portals_monitor) -> Optional[ProfitAnalysis]:
        """Comprehensive profit opportunity analysis"""
        try:
            logger.info("=" * 60)
            logger.info(f"Analyzing: {gift.name}")

            # ===== ДОБАВЬ ЗДЕСЬ =====
            # ===== SPECIAL NUMBER DETECTION =====
            is_special, number_multiplier, number_description = detect_special_number(str(gift.tg_id))

            if is_special:
                logger.info(f"🔢 Special Number detected: {number_description}")
                logger.info(f"🔢 Number multiplier: {number_multiplier}x")

                # If ultra rare number (multiplier >= 5.0) - create special alert
                if number_multiplier >= 5.0:
                    logger.info(f"🚨 ULTRA RARE NUMBER ALERT for {gift.name}!")

                    special_number_analysis = ProfitAnalysis(
                        gift_id=gift.id,
                        profit_percent=(number_multiplier - 1) * 100,
                        profit_ton=gift.price * (number_multiplier - 1),
                        risk_score=0.1,  # Low risk
                        confidence=0.95,  # High confidence
                        strategy="🔢 SPECIAL NUMBER ALERT",
                        reasoning=f"{number_description} - Ultra rare number with {number_multiplier}x expected premium",
                        target_price=gift.price * number_multiplier
                    )
                    return special_number_analysis

            # ✅ INITIALIZE ALL VARIABLES AT START
            target_price = None
            avg_sale_price = None
            recent_sales = []
            sales_history = None
            confidence_score = 0.8
            quality_score = 0

            # Extract NFT attributes
            model, backdrop, symbol = None, None, None
            for attr in gift.attributes:
                attr_type = attr.get('type')
                if attr_type == 'model':
                    model = attr.get('value')
                elif attr_type == 'backdrop':
                    backdrop = attr.get('value')
                elif attr_type == 'symbol':
                    symbol = attr.get('value')

            try:
                from datetime import timezone

                sales_history = await portals_monitor.get_sales_history(collection_name=gift.name, model=model,
                                                                        backdrop=backdrop)

                if sales_history and len(sales_history) > 0:
                    last_sale = sales_history[0]
                    logger.info(f"🔍 Last sale date: {last_sale.get('date')}")

                    # Проверяем по времени + Telegram ID
                    try:
                        sale_date = last_sale['date']
                        now = datetime.now(timezone.utc)

                        # Конвертируем в UTC если нужно
                        if sale_date.tzinfo is None:
                            sale_date = sale_date.replace(tzinfo=timezone.utc)

                        time_since = (now - sale_date).total_seconds()

                        # Если продажа менее 30 минут назад - возможный flip
                        if time_since < 1800:  # 30 минут
                            logger.warning(
                                f"🚫 FLIP SUSPECT: Sale {time_since / 60:.1f} min ago - possible flip!")  # Не блокируем, но предупреждаем

                    except Exception as te:
                        logger.warning(f"Timezone error in flip check: {te}")

            except Exception as e:
                logger.error(f"Error in flip check: {e}")

            logger.info(f"Model: {model}, Backdrop: {backdrop}, Symbol: {symbol}")
            logger.info(f"Current price: {gift.price} TON")

            # Check price limits
            if gift.price > config.MAX_PRICE_TON:
                logger.warning(f"Price {gift.price} TON exceeds limit {config.MAX_PRICE_TON}")
                return None

            # Analyze backdrop and monochrome properties
            is_premium = self.is_premium_backdrop(backdrop)
            is_monochrome = await self.is_monochrome(model, backdrop, gift.name, gift.id)

            if is_premium:
                logger.info(f"✨ Premium backdrop: {backdrop}")
            if is_monochrome:
                logger.info(f"🎨 Monochrome combination detected!")
            else:
                logger.info(f"Regular backdrop: {backdrop}")

            # ===== PREMIUM FLOOR ALERTS =====
            if is_premium:
                try:
                    # Get model floor for comparison
                    model_floor = await portals_monitor.get_model_floor(gift.name, model)

                    if model_floor and model_floor > 0:
                        price_to_floor_ratio = gift.price / model_floor

                        # Define premium backdrop multipliers
                        premium_multipliers = {'onyx black': 1.3, 'black': 2.5, 'midnight blue': 1.05, 'golden': 2.0,
                                               'gunmetal': 1.06}

                        backdrop_lower = backdrop.lower().strip()
                        expected_multiplier = premium_multipliers.get(backdrop_lower, 2.0)

                        # DEBUG LOGGING
                        logger.info(f"🔍 DEBUG: backdrop='{backdrop}', backdrop_lower='{backdrop_lower}'")
                        logger.info(f"🔍 DEBUG: price_to_floor_ratio={price_to_floor_ratio:.2f}x")
                        logger.info(f"🔍 DEBUG: expected_multiplier={expected_multiplier}x")
                        logger.info(f"🔍 DEBUG: premium_multipliers keys: {list(premium_multipliers.keys())}")

                        if price_to_floor_ratio <= expected_multiplier:
                            logger.info("🔥 PREMIUM FLOOR ALERT TRIGGERED!")
                            logger.info(f"💎 Premium backdrop: {backdrop}")
                            logger.info(f"💰 Price: {gift.price:.2f} TON")
                            logger.info(f"📊 Model floor: {model_floor:.2f} TON")
                            logger.info(f"📈 Ratio: {price_to_floor_ratio:.2f}x (threshold: {expected_multiplier}x)")

                            # Create special premium alert
                            premium_analysis = ProfitAnalysis(gift_id=gift.id, profit_percent=50.0,
                                                              # High profit potential
                                                              profit_ton=gift.price * 0.3,  # Estimate 30% profit
                                                              risk_score=0.3,  # Lower risk for premium items
                                                              confidence=0.9,  # High confidence
                                                              strategy=f"🔥 PREMIUM FLOOR ALERT",
                                                              reasoning=f"Premium {backdrop} at only {price_to_floor_ratio:.2f}x model floor (expected {expected_multiplier}x+)",
                                                              target_price=model_floor * (expected_multiplier + 0.5)
                                                              # Target higher multiple
                                                              )

                            if price_to_floor_ratio <= expected_multiplier:
                                logger.info("🔥 PREMIUM FLOOR ALERT TRIGGERED!")

                                # НОВАЯ ПРОВЕРКА: проверить среднюю цену продаж
                                if sales_history and len(sales_history) > 2:
                                    recent_prices = [sale['price'] for sale in sales_history[-5:]]  # Последние 5 продаж
                                    avg_recent = sum(recent_prices) / len(recent_prices)

                                    # Если текущая цена больше средних продаж + 10% - НЕ рекомендовать
                                    if gift.price > avg_recent * 1.1:
                                        logger.warning(
                                            f"❌ Price {gift.price:.2f} > recent avg {avg_recent:.2f} - not profitable despite premium backdrop")
                                        # НЕ возвращаем premium_analysis, продолжаем обычную логику
                                    else:
                                        logger.info(
                                            f"✅ Price {gift.price:.2f} ≤ recent avg {avg_recent:.2f} - premium alert valid")
                                        logger.info(f"🚨 SENDING PREMIUM FLOOR ALERT for {gift.name}!")
                                        return premium_analysis
                                else:
                                    # Если нет истории продаж - отправляем как обычно
                                    logger.info(f"🚨 SENDING PREMIUM FLOOR ALERT for {gift.name}!")
                                    return premium_analysis

                            logger.info(f"🚨 SENDING PREMIUM FLOOR ALERT for {gift.name}!")
                            return premium_analysis
                        else:
                            logger.info(
                                f"✅ Premium {backdrop} at {price_to_floor_ratio:.2f}x floor - above {expected_multiplier}x threshold")

                except Exception as e:
                    logger.warning(f"Failed to check premium floor ratio: {e}")

            # Продолжить с обычной логикой...
            use_combo_strategy = is_premium or is_monochrome

            # Get market data based on strategy
            if use_combo_strategy:
                similar_nfts = await portals_monitor.search_similar_nfts(model=model, backdrop=backdrop)
                strategy_type = "Premium backdrop" if is_premium else "Monochrome"
            else:
                similar_nfts = await portals_monitor.search_similar_nfts(model=model)
                strategy_type = "Model arbitrage"

                # Also check model floor for regular backdrops
                model_floor = await portals_monitor.get_model_floor(gift.name, model)
                if model_floor and gift.price > model_floor * 1.05:
                    logger.warning(f"Price {gift.price} TON > model floor {model_floor} TON")
                    return None

            # SPECIAL HANDLING FOR RARE COMBOS (1 NFT in market)
            if use_combo_strategy and (not similar_nfts or len(similar_nfts) <= 1):
                logger.info(f"🔥 RARE COMBO detected! Only {len(similar_nfts or [])} NFT(s) in market")

                # For rare combos, rely on sales history
                logger.info("Checking sales history for rare combo pricing...")
                sales_history = await portals_monitor.get_sales_history(collection_name=gift.name, model=model,
                                                                        backdrop=backdrop, days=60
                                                                        # Extended period for rare items
                                                                        )

                if not sales_history or len(sales_history) < 2:
                    logger.warning(
                        f"Insufficient sales history for rare combo: {len(sales_history) if sales_history else 0} sales")
                    return None

                logger.info(f"Found {len(sales_history)} historical sales")

                # ✅ INITIALIZE sales data properly
                sale_prices = [s['price'] for s in sales_history]
                avg_sale_price = sum(sale_prices) / len(sale_prices)
                max_sale_price = max(sale_prices)
                min_sale_price = min(sale_prices)

                # ✅ PROPERLY INITIALIZE recent_sales
                recent_sales = [s for s in sales_history if (datetime.now(s['date'].tzinfo) - s['date']).days <= 30]

                if recent_sales:
                    recent_avg = sum(s['price'] for s in recent_sales) / len(recent_sales)
                    logger.info(f"Recent sales avg: {recent_avg:.2f} TON ({len(recent_sales)} sales)")
                    target_price = recent_avg * 1.25
                else:
                    logger.info(f"Historical sales avg: {avg_sale_price:.2f} TON")
                    target_price = avg_sale_price * 1.30

                logger.info(f"Price analysis for rare combo:")
                logger.info(f"- Historical range: {min_sale_price:.2f} - {max_sale_price:.2f} TON")
                logger.info(f"- Average: {avg_sale_price:.2f} TON")
                logger.info(f"- Current: {gift.price:.2f} TON")
                logger.info(f"- Target: {target_price:.2f} TON")

                # Check if current price is reasonable vs historical
                if gift.price > avg_sale_price * 1.2:
                    logger.warning(f"Price {gift.price} TON too high vs historical avg {avg_sale_price:.2f} TON")
                    return None

                # Set target price with premium for rarity
                target_price = max(target_price, avg_sale_price * 1.1)  # At least 10% above historical avg

            else:
                # NORMAL LOGIC for non-rare items
                if not similar_nfts or len(similar_nfts) < 2:
                    logger.warning(f"Insufficient similar NFTs found: {len(similar_nfts) if similar_nfts else 0}")
                    return None

                logger.info(f"Found {len(similar_nfts)} similar NFTs")

                # Analyze pricing
                prices = sorted([float(nft['price']) for nft in similar_nfts if nft.get('price', 0) > 0])

                if len(prices) < 2:
                    logger.warning("Insufficient price data for analysis")
                    return None

                min_price, max_price = prices[0], prices[-1]
                avg_price = sum(prices) / len(prices)

                logger.info(f"Price analysis - Min: {min_price}, Max: {max_price}, Avg: {avg_price:.2f}")

                # Check if this is a good deal
                if gift.price < min_price:
                    logger.info("✅ This is the cheapest available!")
                    if not use_combo_strategy:  # Only for regular NFTs
                        target_price = prices[1] if len(prices) > 1 else prices[0] * 1.05
                elif gift.price == min_price:
                    logger.info("✅ Tied for cheapest")
                    if not use_combo_strategy:  # Only for regular NFTs
                        target_price = prices[1] if len(prices) > 1 else min_price * 1.05
                else:
                    logger.warning(f"Not competitive - Current: {gift.price}, Floor: {min_price}")
                    return None

            # SMART TARGET PRICE CALCULATION
            smart_target = calculate_smart_target_price(sales_history, is_premium, is_monochrome, backdrop)

            if smart_target:
                target_price = smart_target
                logger.info(f"🎯 Using smart target: {target_price:.2f} TON")
            else:
                # UNIVERSAL FALLBACK - Check if target_price is set
                if target_price is None:
                    logger.warning("target_price not set, using fallback calculation")
                    if use_combo_strategy and recent_sales:
                        recent_avg = sum([s['price'] for s in recent_sales]) / len(recent_sales)
                        target_price = recent_avg * 1.25
                    elif avg_sale_price is not None:
                        target_price = avg_sale_price * 1.30
                    else:
                        target_price = gift.price * 1.05  # Minimum profit fallback
                logger.info(f"📈 Using fallback target: {target_price:.2f} TON")

            logger.info(f"Target sell price: {target_price:.2f} TON")

            # Calculate profit margins
            gross_profit = target_price - gift.price
            gross_profit_percent = (gross_profit / gift.price) * 100

            # Account for 5% marketplace commission
            commission = target_price * 0.05
            net_profit = gross_profit - commission
            net_profit_percent = (net_profit / gift.price) * 100

            logger.info(f"Gross profit: {gross_profit:.2f} TON ({gross_profit_percent:.1f}%)")
            logger.info(f"Marketplace commission: {commission:.2f} TON")
            logger.info(f"Net profit: {net_profit:.2f} TON ({net_profit_percent:.1f}%)")

            # Adjust minimum profit for rare combos
            min_profit_threshold = config.MIN_PROFIT_PERCENT
            if use_combo_strategy and len(similar_nfts or []) <= 1:
                min_profit_threshold = max(5.0, config.MIN_PROFIT_PERCENT - 5)  # Lower threshold for rare items
                logger.info(f"Using reduced profit threshold for rare combo: {min_profit_threshold}%")

            MIN_PROFIT_THRESHOLD = 20  # Increased from 15% to 20%
            if net_profit_percent < MIN_PROFIT_THRESHOLD:
                logger.warning(f"Net profit {net_profit_percent:.1f}% below minimum {min_profit_threshold}%")
                return None

            # Enhanced confidence for rare items with good sales history
            confidence_score = 0.85 if use_combo_strategy and len(similar_nfts or []) <= 1 else 0.8

            logger.info("🎯 PROFITABLE OPPORTUNITY IDENTIFIED!")
            logger.info(f"Strategy: {strategy_type}")
            logger.info(f"Confidence: {confidence_score:.0%}")
            logger.info("=" * 60)

            return ProfitAnalysis(gift_id=gift.id, profit_percent=net_profit_percent, profit_ton=net_profit,
                                  risk_score=1.0 - confidence_score, confidence=confidence_score,
                                  strategy=strategy_type,
                                  reasoning=f"Buy {gift.price:.2f} TON, Sell {target_price:.2f} TON, Net profit {net_profit:.2f} TON ({net_profit_percent:.1f}%), Sales: {len(sales_history) if sales_history else 0} total, {len(recent_sales) if recent_sales else 0} recent (avg: {avg_sale_price:.2f} TON)" if sales_history and avg_sale_price is not None else f"Buy {gift.price:.2f} TON, Sell {target_price:.2f} TON, Net profit {net_profit:.2f} TON ({net_profit_percent:.1f}%)",
                                  target_price=target_price)

        except Exception as e:
            logger.error(f"Analysis failed for {gift.name}: {e}")
            import traceback
            traceback.print_exc()
            return None
