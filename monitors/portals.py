import logging
from typing import List, Optional, Dict
from datetime import datetime, timezone, timedelta
from database import Gift
import config
from aportalsmp.gifts import search, marketActivity, filterFloors
import asyncio

logger = logging.getLogger(__name__)


class PortalsMonitor:

    def __init__(self):
        self.auth_data = config.PORTALS_AUTH_TOKEN
        self.processed_ids = set()
        self.floor_cache = {}
        self.search_cache = {}
        self.cache_ttl = 1800

    def is_monochrome(self, model: str, backdrop: str) -> bool:
        """Проверка монохрома"""
        if not model or not backdrop:
            return False

        color_groups = {
            'red': ['red', 'crimson', 'scarlet', 'cherry', 'ruby', 'rose', 'burgundy'],
            'blue': ['blue', 'azure', 'navy', 'sapphire', 'cobalt', 'cyan', 'indigo'],
            'green': ['green', 'emerald', 'forest', 'jade', 'olive', 'lime'],
            'yellow': ['yellow', 'gold', 'golden', 'amber', 'lemon'],
            'purple': ['purple', 'violet', 'lavender', 'plum', 'amethyst'],
            'pink': ['pink', 'rose', 'magenta', 'fuchsia'],
            'brown': ['brown', 'chocolate', 'coffee', 'tan', 'beige'],
            'gray': ['gray', 'grey', 'silver', 'steel', 'charcoal'],
            'black': ['black', 'onyx', 'ebony', 'midnight'],
            'white': ['white', 'ivory', 'pearl', 'snow']
        }

        model_lower = model.lower()
        backdrop_lower = backdrop.lower()

        for color_name, color_variations in color_groups.items():
            model_has_color = any(color in model_lower for color in color_variations)
            backdrop_has_color = any(color in backdrop_lower for color in color_variations)
            if model_has_color and backdrop_has_color:
                return True

        return False

    def is_premium_backdrop(self, backdrop: str) -> bool:
        """Проверка премиум фона"""
        if not backdrop:
            return False
        premium = ['midnight blue', 'onyx black', 'black']
        return backdrop.lower() in premium

    async def scan_new_gifts(self) -> List[Gift]:
        """Сканирование новых NFT через search с retry"""
        max_retries = 3

        for attempt in range(max_retries):
            try:
                logger.info(f"Scanning latest gifts using search() (attempt {attempt + 1}/{max_retries})...")

                if attempt > 0:
                    wait_time = 5 * attempt
                    logger.info(f"Waiting {wait_time}s before retry...")
                    await asyncio.sleep(wait_time)

                nfts = await search(
                    sort="latest",
                    limit=50,
                    authData=self.auth_data
                )

                logger.info(f"Received {len(nfts)} NFTs from API")

                gifts = []
                for nft in nfts:
                    logger.info(f"NFT ID: {nft.id}, TG_ID: {nft.tg_id}")

                    if nft.price > config.MAX_PRICE_TON:
                        continue

                    if nft.id in self.processed_ids:
                        continue

                    self.processed_ids.add(nft.id)

                    attributes = []
                    if nft.model:
                        attributes.append({'type': 'model', 'value': nft.model})
                    if nft.backdrop:
                        attributes.append({'type': 'backdrop', 'value': nft.backdrop})
                    if nft.symbol:
                        attributes.append({'type': 'symbol', 'value': nft.symbol})

                    # ✅ ИСПРАВЛЕНО: используем параметры из СТАРОГО database.py
                    gift = Gift(
                        id=nft.id,
                        name=nft.name,
                        number=nft.tg_id,  # ← ОБЯЗАТЕЛЬНЫЙ параметр!
                        price=float(nft.price),
                        collection_id=nft.collection_id,
                        photo_url=nft.photo_url,
                        attributes=attributes
                        # timestamp создаётся автоматически в __post_init__
                    )

                    gifts.append(gift)

                logger.info(f"Found {len(gifts)} new NFTs")
                return gifts

            except Exception as e:
                logger.error(f"Error scanning gifts (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    logger.error("All retry attempts failed! Returning empty list.")
                    return []

        return []

    async def get_model_floor(self, collection_name: str, model: str) -> Optional[float]:
        """Получить floor цену модели"""
        try:
            nfts = await search(
                gift_name=collection_name,
                model=model,
                sort="price_asc",
                limit=1,
                authData=self.auth_data
            )

            if nfts and len(nfts) > 0:
                floor = float(nfts[0].price)
                logger.info(f"Model floor for {model}: {floor} TON")
                return floor

            return None

        except Exception as e:
            logger.error(f"Error getting model floor: {e}")
            return None

    async def search_similar_nfts(self, model: str = None, backdrop: str = None) -> List[Dict]:
        """Поиск похожих NFT с retry"""
        max_retries = 3

        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    await asyncio.sleep(3)

                if model and backdrop:
                    logger.info(f"Searching: {model} + {backdrop}")
                    nfts = await search(
                        model=model,
                        backdrop=backdrop,
                        sort="price_asc",
                        limit=50,
                        authData=self.auth_data
                    )
                elif model:
                    logger.info(f"Searching: {model} (MODEL ONLY)")
                    nfts = await search(
                        model=model,
                        sort="price_asc",
                        limit=50,
                        authData=self.auth_data
                    )
                else:
                    logger.warning("No model specified")
                    return []

                logger.info(f"Found {len(nfts)} NFTs")

                if len(nfts) > 0:
                    for i, nft in enumerate(nfts[:3]):
                        logger.info(
                            f"  NFT #{i + 1}: {nft.name}, Model={nft.model}, Backdrop={nft.backdrop}, Price={nft.price}")

                return [self._nft_to_dict(nft) for nft in nfts]

            except Exception as e:
                logger.error(f"Error searching NFTs (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    return []

        return []

    async def get_sales_history(
            self,
            collection_name: str,
            model: str = None,
            backdrop: str = None,
            days: int = 30
    ) -> List[Dict]:
        """Получить историю продаж"""
        try:
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

            for activity in activities:
                try:
                    timestamp = activity.created_at.replace('Z', '+00:00')

                    if '.' in timestamp and '+' in timestamp:
                        parts = timestamp.split('.')
                        microseconds = parts[1].split('+')[0]
                        if len(microseconds) > 6:
                            microseconds = microseconds[:6]
                        timestamp = f"{parts[0]}.{microseconds}+00:00"

                    sale_date = datetime.fromisoformat(timestamp)

                    if sale_date >= cutoff_date:
                        sales.append({
                            'price': float(activity.amount),
                            'date': sale_date,
                            'nft_name': activity.nft.name,
                            'model': activity.nft.model,
                            'backdrop': activity.nft.backdrop
                        })

                except Exception as e:
                    logger.error(f"Error parsing sale: {e}")
                    continue

            logger.info(f"Found {len(sales)} sales in last {days} days")
            return sales

        except Exception as e:
            logger.error(f"Error getting sales history: {e}", exc_info=True)
            return []

    def _nft_to_dict(self, nft) -> Dict:
        """Конвертация NFT в словарь"""
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
