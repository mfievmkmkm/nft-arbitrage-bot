import sqlite3
import json
import logging
from datetime import datetime
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class Gift:
    id: str
    name: str
    number: int
    price: float
    collection_id: str
    photo_url: str
    attributes: List[Dict]
    platform: str = "portals"
    url: str = ""
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
        if not self.url:
            self.url = f"https://portal-market.com/nft/{self.id}"

    @property
    def tg_id(self):
        """Compatibility property for Telegram ID"""
        return self.number


@dataclass
class ProfitAnalysis:
    gift_id: str
    profit_percent: float
    profit_ton: float  # ДОБАВИТЬ ЭТО ПОЛЕ!
    risk_score: float
    confidence: float
    strategy: str
    reasoning: str
    target_price: float


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.init_database()

    def init_database(self):
        """Инициализация базы данных"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Таблица подарков
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS gifts (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    number INTEGER NOT NULL,
                    price REAL NOT NULL,
                    collection_id TEXT,
                    photo_url TEXT,
                    attributes TEXT,
                    platform TEXT DEFAULT 'portals',
                    url TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Таблица анализа прибыли
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS profit_analysis (
                    gift_id TEXT PRIMARY KEY,
                    profit_percent REAL NOT NULL,
                    risk_score REAL NOT NULL,
                    confidence REAL NOT NULL,
                    strategy TEXT NOT NULL,
                    reasoning TEXT NOT NULL,
                    target_price REAL NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (gift_id) REFERENCES gifts (id)
                )
            ''')

            # Таблица обработанных ID для дедупликации
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS processed_gifts (
                    id TEXT PRIMARY KEY,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            conn.commit()
            logger.info("Database initialized successfully")

    def save_gift(self, gift: Gift) -> bool:
        """Сохранить подарок в БД"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO gifts 
                    (id, name, number, price, collection_id, photo_url, attributes, platform, url, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    gift.id,
                    gift.name,
                    gift.number,
                    gift.price,
                    gift.collection_id,
                    gift.photo_url,
                    json.dumps(gift.attributes),
                    gift.platform,
                    gift.url,
                    gift.timestamp
                ))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error saving gift: {e}")
            return False

    def save_analysis(self, analysis: ProfitAnalysis) -> bool:
        """Сохранить анализ прибыли"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO profit_analysis
                    (gift_id, profit_percent, risk_score, confidence, strategy, reasoning, target_price)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    analysis.gift_id,
                    analysis.profit_percent,
                    analysis.risk_score,
                    analysis.confidence,
                    analysis.strategy,
                    analysis.reasoning,
                    analysis.target_price
                ))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error saving analysis: {e}")
            return False

    def is_processed(self, gift_id: str) -> bool:
        """Проверить был ли подарок уже обработан"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM processed_gifts WHERE id = ?', (gift_id,))
            return cursor.fetchone() is not None

    def mark_processed(self, gift_id: str):
        """Отметить подарок как обработанный"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT OR IGNORE INTO processed_gifts (id) VALUES (?)', (gift_id,))
            conn.commit()

    def get_recent_gifts(self, limit: int = 10) -> List[Gift]:
        """Получить последние подарки"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, name, number, price, collection_id, photo_url, attributes, platform, url, timestamp
                FROM gifts
                ORDER BY timestamp DESC
                LIMIT ?
            ''', (limit,))

            gifts = []
            for row in cursor.fetchall():
                gifts.append(Gift(
                    id=row[0],
                    name=row[1],
                    number=row[2],
                    price=row[3],
                    collection_id=row[4],
                    photo_url=row[5],
                    attributes=json.loads(row[6]) if row[6] else [],
                    platform=row[7],
                    url=row[8],
                    timestamp=datetime.fromisoformat(row[9]) if row[9] else None
                ))
            return gifts
