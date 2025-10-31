"""
NFT profit opportunity analyzer.

Analyzes NFT pricing, floor prices, monochrome combinations,
and calculates potential profit after marketplace fees.

Features:
- Advanced monochrome detection using color similarity analysis
- Premium backdrop recognition (Midnight Blue, Onyx Black, Black, Amber, Gunmetal)
- Intelligent profit calculation with market analysis
- Risk assessment and confidence scoring
"""
import time
import logging
import aiohttp
import asyncio
import json
import math
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from curl_cffi import requests
from rlottie_python import LottieAnimation
from sklearn.cluster import KMeans
from colorspacious import cspace_convert, deltaE
from colormath.color_objects import sRGBColor, HSVColor
from colormath.color_conversions import convert_color

from database import Gift, ProfitAnalysis
import config

logger = logging.getLogger(__name__)

# Premium backdrops that require combo analysis
PREMIUM_BACKDROPS = [
    'midnight blue',
    'onyx black',
    'black',
    'amber',
    'gunmetal'
]


class ProfitAnalyzer:
    """Advanced NFT profit opportunity analyzer with color similarity detection."""

    def __init__(self):
        """Initialize analyzer with caching for performance."""
        self.market_cache = {}
        self.ton_usd_price = 0.0
        self.last_ton_update = None
        self.monochrome_cache = {}

    # === ADVANCED MONOCHROME DETECTION ===

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
        data["layers"] = [
            layer for layer in data.get("layers", [])
            if layer.get("nm") not in layers_to_remove
        ]
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

        return round(
            weights[0] * cam_sim +
            weights[1] * rgb_sim +
            weights[2] * hue_sim +
            weights[3] * chroma_sim,
            2)

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

            result = {
                "similarity": similarity,
                "deltaE": round(delta_e, 2),
                "rgbDistance": round(rgb_distance, 2),
                "hueDifference": round(abs(bg_hsv.hsv_h - fg_hsv.hsv_h), 2),
                "chromaDifference": round(abs(bg_hsv.hsv_s - fg_hsv.hsv_s), 2),
                "bgColor": bg_color,
                "giftColor": fg_color
            }

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
            name_mapping = {
                "birthday candle": "bdaycandle",
                "b-day candle": "bdaycandle",
                "jack in the box": "jackinthebox",
                "durov's cap": "durovscap",
                "lol pop": "lolpop",
                "candy cane": "candycane",
                "restless jar": "restlessjar",
                # Add more mappings as needed
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
            if (self.last_ton_update and
                    (datetime.now() - self.last_ton_update).seconds < 300):
                return self.ton_usd_price

            url = "https://api.coingecko.com/api/v3/simple/price"
            params = {
                'ids': 'the-open-network',
                'vs_currencies': 'usd'
            }

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

    async def analyze_profit_opportunity(
            self,
            gift: Gift,
            portals_monitor
    ) -> Optional[ProfitAnalysis]:
        """Comprehensive profit opportunity analysis with special handling for rare combos."""
        try:
            logger.info("=" * 60)
            logger.info(f"Analyzing: {gift.name}")

            analysis = ProfitAnalysis(
                gift_id=gift.id,  #
                profit_percent=0.0,
                profit_ton=0.0,
                risk_score=30.0,
                confidence=70.0,
                strategy="Premium backdrop",
                reasoning="Initial analysis",
                target_price=gift.price
            )
            need_sales_verification = True

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

            if not model or not backdrop:
                logger.warning("Missing required attributes (model/backdrop)")
                return None

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

            # Determine analysis strategy
            use_combo_strategy = is_premium or is_monochrome

            # Get market data based on strategy
            if use_combo_strategy:
                similar_nfts = await portals_monitor.search_similar_nfts(
                    model=model,
                    backdrop=backdrop
                )
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
                sales_history = await portals_monitor.get_sales_history(
                    collection_name=gift.name,
                    model=model,
                    backdrop=backdrop,
                    days=60  # Extended period for rare items
                )

                if not sales_history or len(sales_history) < 2:
                    logger.warning(
                        f"Insufficient sales history for rare combo: {len(sales_history) if sales_history else 0} sales")
                    return None

                logger.info(f"Found {len(sales_history)} historical sales")

                # Analyze historical sales
                sale_prices = [s['price'] for s in sales_history]
                avg_sale_price = sum(sale_prices) / len(sale_prices)
                max_sale_price = max(sale_prices)
                min_sale_price = min(sale_prices)

                # Recent sales (last 30 days) are more valuable
                recent_sales = [
                    s for s in sales_history
                    if (datetime.now(s['date'].tzinfo) - s['date']).days <= 30
                ]

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
                    # НЕ ТРОГАЕМ target_price для premium/редких комбо!
                    if not use_combo_strategy:  # Только для обычных NFT
                        target_price = prices[1] if len(prices) > 1 else prices[0] * 1.05
                elif gift.price == min_price:
                    logger.info("✅ Tied for cheapest")
                    if not use_combo_strategy:  # Только для обычных NFT
                        target_price = prices[1] if len(prices) > 1 else min_price * 1.05

                else:
                    logger.warning(f"Not competitive - Current: {gift.price}, Floor: {min_price}")
                    return None

            # ✅ УНИВЕРСАЛЬНОЕ РЕШЕНИЕ - ПРОВЕРЯЕМ СУЩЕСТВОВАНИЕ
            if 'target_price' not in locals():
                logger.warning("target_price not set, using fallback calculation")
                if use_combo_strategy:
                    if recent_sales:
                        recent_avg = sum(s['price'] for s in recent_sales) / len(recent_sales)
                        target_price = recent_avg * 1.25
                    else:
                        target_price = avg_sale_price * 1.30
                else:
                    target_price = gift.price * 1.05  # Minimum profit

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

            MIN_PROFIT_THRESHOLD = 15  # Повысили с 10% до 15%
            if net_profit_percent < MIN_PROFIT_THRESHOLD:
                logger.warning(f"Net profit {net_profit_percent:.1f}% below minimum {min_profit_threshold}%")
                return None

            # Enhanced confidence for rare items with good sales history
            confidence_score = 0.85 if use_combo_strategy and len(similar_nfts or []) <= 1 else 0.8

            logger.info("🎯 PROFITABLE OPPORTUNITY IDENTIFIED!")
            logger.info(f"Strategy: {strategy_type}")
            logger.info(f"Confidence: {confidence_score:.0%}")
            logger.info("=" * 60)

            if not use_combo_strategy and len(similar_nfts or []) >= 10:
                prices = sorted([float(nft['price']) for nft in similar_nfts if nft.get('price', 0) > 0])
                if len(prices) >= 2:
                    first_price = prices[0]
                    second_price = prices[1]
                    price_jump = (second_price - first_price) / first_price

                    if price_jump >= 0.3:  # Если прыжок 30%+ между 1 и 2 местом
                        logger.info(
                            f"🏃‍♂️ Big market spread detected: {price_jump:.1%} jump, skipping sales verification")
                        need_sales_verification = False
                    logger.info("Sales verification required: RARE COMBO")
                elif len(similar_nfts or []) <= 5:
                    need_sales_verification = True  # Check for small supply
                    logger.info("Sales verification required: LIMITED SUPPLY")
                elif target_price > gift.price * 1.3:
                    need_sales_verification = True  # Check for big price jumps
                    logger.info("Sales verification required: BIG PRICE JUMP")

            if need_sales_verification:
                logger.info("🔍 Performing sales history verification...")
                sales_history = await portals_monitor.get_sales_history(
                    collection_name=gift.name,
                    model=model,
                    backdrop=backdrop if use_combo_strategy else None,
                    days=30
                )

                if sales_history and len(sales_history) >= 5:
                    # Умная фильтрация истории - убираем аутлайеры (монохромы)
                    # SMART WEIGHTED ANALYSIS - приоритет свежим продажам
                    sale_prices = [s['price'] for s in sales_history]
                    sale_dates = [s['date'] for s in sales_history]

                    if len(sale_prices) > 3:
                        # Сортируем по дате (свежие сверху)
                        sales_with_dates = list(zip(sale_prices, sale_dates))
                        sales_with_dates.sort(key=lambda x: x[1], reverse=True)

                        # Убираем аутлайеры (top 15% и bottom 10%)
                        n = len(sales_with_dates)
                        start_idx = max(1, int(n * 0.1))
                        end_idx = min(n - 1, int(n * 0.85))
                        filtered_sales = sales_with_dates[start_idx:end_idx]

                        if len(filtered_sales) >= 2:
                            # WEIGHTED AVERAGE - больший вес свежим продажам
                            total_weighted_price = 0
                            total_weight = 0

                            for i, (price, date) in enumerate(filtered_sales):
                                # Вес: свежие продажи важнее (экспоненциальный спад)
                                days_ago = (datetime.now(date.tzinfo) - date).days
                                weight = max(0.1, 2.0 ** (-days_ago / 7))  # Half-life 7 дней

                                # Последние 3 продажи получают бонус веса
                                if i < 3:
                                    weight *= 2.0

                                total_weighted_price += price * weight
                                total_weight += weight

                            weighted_avg = total_weighted_price / total_weight
                            simple_avg = sum(p for p, d in filtered_sales) / len(filtered_sales)

                            # Используем более консервативную из двух оценок
                            avg_sale_price = min(weighted_avg, simple_avg)

                            logger.info(f"📊 Weighted avg: {weighted_avg:.2f} TON")
                            logger.info(f"📊 Simple avg: {simple_avg:.2f} TON")
                            logger.info(f"📊 Conservative avg: {avg_sale_price:.2f} TON")

                            # ПОСЛЕДНИЕ 3 ПРОДАЖИ - отдельная проверка
                            recent_3_prices = [p for p, d in filtered_sales[:3]]
                            if len(recent_3_prices) >= 2:
                                recent_avg = sum(recent_3_prices) / len(recent_3_prices)
                                logger.info(f"🔥 Last 3 sales avg: {recent_avg:.2f} TON")

                                # Если разница между recent и общим > 30% - используем recent
                                if abs(recent_avg - avg_sale_price) / avg_sale_price > 0.3:
                                    logger.warning(f"📈 Big trend change detected! Using recent avg: {recent_avg:.2f}")
                                    avg_sale_price = recent_avg

                        else:
                            avg_sale_price = sum(sale_prices) / len(sale_prices)
                            logger.info(f"📊 Simple avg: {avg_sale_price:.2f} TON (too few sales to filter)")
                    else:
                        avg_sale_price = sum(sale_prices) / len(sale_prices)
                        logger.info(f"📊 Simple avg: {avg_sale_price:.2f} TON (sample too small)")

                    recent_sales_count = len([s for s in sales_history
                                              if (datetime.now(s['date'].tzinfo) - s['date']).days <= 14])

                    logger.info(f"Sales verification: {len(sales_history)} total sales, {recent_sales_count} recent")
                    logger.info(f"Average sale price: {avg_sale_price:.2f} TON")

                    # CRITICAL: Check if BUY PRICE is reasonable vs sales history
                    max_reasonable_buy_price = avg_sale_price * 1.08  # 110% от истории (строже!)
                    if gift.price > max_reasonable_buy_price:
                        overpay_percent = (gift.price / avg_sale_price - 1) * 100
                        logger.warning(f"🚫 REJECTED: Overpaying by {overpay_percent:.1f}%")
                        logger.warning(f"💰 Buy: {gift.price:.2f} TON > Limit: {max_reasonable_buy_price:.2f} TON")
                        logger.warning(f"📊 History avg: {avg_sale_price:.2f} TON")
                        return None

                        # Для premium combo - ВСЕГДА отклоняем переплату
                        if use_combo_strategy:
                            logger.warning(f"❌ Rejecting premium combo - price too high vs sales")
                            return None

                        # Для обычных NFT тоже отклоняем если переплата >10%
                        logger.warning(f"❌ Rejecting NFT - price {gift.price / avg_sale_price:.1%} of average sales")
                        return None

                        # Для премиум combo - строже
                        if use_combo_strategy:
                            logger.warning(f"❌ Rejecting premium combo - price too high vs sales")
                            return None

                        # Для обычных NFT - дополнительный анализ
                        logger.info("🔍 Checking if price spike justified...")

                    # Adjust target if too optimistic
                    max_reasonable_target = avg_sale_price * 1.5
                    if target_price > max_reasonable_target:
                        logger.info(f"📊 Adjusting target from {target_price:.2f} to {max_reasonable_target:.2f} TON")
                        target_price = max_reasonable_target

                    logger.info(f"✅ Buy price validation passed: {gift.price:.2f} ≤ {max_reasonable_buy_price:.2f} TON")

                    # Boost confidence if recent sales exist
                    if recent_sales_count > 0:
                        confidence_score = min(0.95, confidence_score + 0.1)
                        logger.info(f"Confidence boosted due to recent sales: {confidence_score:.0%}")
                else:
                    logger.warning(f"No sales history found")
                    if use_combo_strategy and len(similar_nfts or []) <= 2:
                        logger.warning("Rejecting rare combo with no sales history")
                        return None
                    else:
                        confidence_score = max(0.6, confidence_score - 0.2)

            quality_score = 0

            # Прибыльность (0-40 баллов)
            if net_profit_percent >= 30:
                quality_score += 40
            elif net_profit_percent >= 20:
                quality_score += 30
            elif net_profit_percent >= 15:
                quality_score += 20
            else:
                quality_score += 10

            # История продаж (0-25 баллов)
            sales_history = None
            if sales_history and len(sales_history) > 7:
                quality_score += 25
            elif sales_history and len(sales_history) >= 5:
                quality_score += 20
            elif sales_history and len(sales_history) >= 3:
                quality_score += 15
            else:
                quality_score += 5

            # Цена относительно истории (0-20 баллов)
            if 'avg_sale_price' not in locals() or avg_sale_price is None:
                avg_sale_price = gift.price  # Используем текущую цену как базу
                logger.warning(f"No sales history available, using current price as reference: {avg_sale_price}")

            price_ratio = gift.price / avg_sale_price
            if price_ratio <= 1.02:  # До 2% от истории
                quality_score += 20
            elif price_ratio <= 1.05:  # До 5%
                quality_score += 15
            elif price_ratio <= 1.08:  # До 8%
                quality_score += 10
            else:
                quality_score += 0

            # Стратегия (0-15 баллов)
            if use_combo_strategy:  # Монохром/премиум
                quality_score += 15
            else:
                quality_score += 8

            logger.info(f"🎯 Quality Score: {quality_score}/100")

            # ФИЛЬТР ПО КАЧЕСТВУ
            if quality_score < 65:  # Только топ-35% сделок
                logger.warning(f"❌ Quality too low: {quality_score}/100 < 65")
                return None

            logger.info(f"🎯 Quality Score: {quality_score}/100")
            return analysis

            return ProfitAnalysis(
                gift_id=gift.id,
                profit_percent=net_profit_percent,
                profit_ton=net_profit,  # ДОБАВИТЬ ЭТО!
                risk_score=1.0 - confidence_score,
                confidence=confidence_score,
                strategy=strategy_type,
                reasoning=f"Buy: {gift.price:.2f} TON, Sell: {target_price:.2f} TON, Net profit: {net_profit:.2f} TON ({net_profit_percent:.1f}%)",
                target_price=target_price
            )




        except Exception as e:
            logger.error(f"Analysis failed for {gift.name}: {e}")
            import traceback
            traceback.print_exc()
            return None
