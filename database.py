"""
Database module for NFT Gift Bot.
Handles SQLite operations for gifts, profit analysis, and statistics.
"""

import sqlite3
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class Gift:
    """NFT Gift data model."""
    id: str
    tg_id: int
    name: str
    price: float
    collection: str
    attributes: List[Dict[str, Any]]
    created_at: str

    @classmethod
    def from_api(cls, data: Dict[str, Any]) -> 'Gift':
        """Create Gift instance from API response."""
        return cls(
            id=data['id'],
            tg_id=data['tg_id'],
            name=data['name'],
            price=float(data.get('price', 0)),
            collection=data.get('collection', {}).get('name', 'Unknown'),
            attributes=data.get('attributes', []),
            created_at=data.get('created_at', '')
        )


@dataclass
class ProfitAnalysis:
    """Profit analysis result data model."""
    gift_id: str
    gift_name: str
    buy_price: float
    target_price: float
    profit_ton: float
    profit_percent: float
    strategy: str
    confidence: float
    analyzed_at: str = None

    def __post_init__(self):
        if self.analyzed_at is None:
            self.analyzed_at = datetime.now().isoformat()


class Database:
    """SQLite database manager for NFT Gift Bot."""

    def __init__(self, db_path: str):
        """
        Initialize database connection.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self.conn = None
        self._initialize_db()

    def _initialize_db(self):
        """Create database tables if they don't exist."""
        try:
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            cursor = self.conn.cursor()

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS gifts (
                    id TEXT PRIMARY KEY,
                    tg_id INTEGER,
                    name TEXT,
                    price REAL,
                    collection TEXT,
                    attributes TEXT,
                    created_at TEXT,
                    added_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS profit_analyses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    gift_id TEXT,
                    gift_name TEXT,
                    buy_price REAL,
                    target_price REAL,
                    profit_ton REAL,
                    profit_percent REAL,
                    strategy TEXT,
                    confidence REAL,
                    analyzed_at TEXT,
                    FOREIGN KEY (gift_id) REFERENCES gifts (id)
                )
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_gifts_tg_id 
                ON gifts(tg_id)
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_profit_analyses_gift_id 
                ON profit_analyses(gift_id)
            ''')

            self.conn.commit()
            logger.info("Database initialized successfully")

        except sqlite3.Error as e:
            logger.error(f"Database initialization error: {e}")
            raise

    def save_gift(self, gift: Gift) -> bool:
        """
        Save gift to database.

        Args:
            gift: Gift instance to save

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO gifts 
                (id, tg_id, name, price, collection, attributes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                gift.id,
                gift.tg_id,
                gift.name,
                gift.price,
                gift.collection,
                str(gift.attributes),
                gift.created_at
            ))
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Error saving gift {gift.id}: {e}")
            return False

    def save_analysis(self, analysis: ProfitAnalysis) -> bool:
        """
        Save profit analysis to database.

        Args:
            analysis: ProfitAnalysis instance to save

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO profit_analyses 
                (gift_id, gift_name, buy_price, target_price, profit_ton, 
                 profit_percent, strategy, confidence, analyzed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                analysis.gift_id,
                analysis.gift_name,
                analysis.buy_price,
                analysis.target_price,
                analysis.profit_ton,
                analysis.profit_percent,
                analysis.strategy,
                analysis.confidence,
                analysis.analyzed_at
            ))
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Error saving analysis for {analysis.gift_id}: {e}")
            return False

    def get_recent_analyses(self, limit: int = 10) -> List[ProfitAnalysis]:
        """
        Get recent profit analyses.

        Args:
            limit: Maximum number of results

        Returns:
            List of ProfitAnalysis instances
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT * FROM profit_analyses 
                ORDER BY analyzed_at DESC 
                LIMIT ?
            ''', (limit,))

            rows = cursor.fetchall()
            return [
                ProfitAnalysis(
                    gift_id=row['gift_id'],
                    gift_name=row['gift_name'],
                    buy_price=row['buy_price'],
                    target_price=row['target_price'],
                    profit_ton=row['profit_ton'],
                    profit_percent=row['profit_percent'],
                    strategy=row['strategy'],
                    confidence=row['confidence'],
                    analyzed_at=row['analyzed_at']
                )
                for row in rows
            ]
        except sqlite3.Error as e:
            logger.error(f"Error fetching recent analyses: {e}")
            return []

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")
