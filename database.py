"""
Database Layer - NFT Gift Bot Persistence

SQLite-based data persistence layer providing:
- NFT gift listing storage and retrieval
- Profit analysis result tracking
- Deduplication via processing state
- Query helpers and statistics

Database Schema:
----------------
1. gifts: NFT marketplace listings
   - id (PK): Unique NFT identifier
   - name: Display name
   - number: Collection number (mint #)
   - price: Current listing price (TON)
   - collection_id: Smart contract address
   - photo_url: Image URL
   - attributes: JSON array of traits
   - platform: Marketplace name
   - url: Direct listing link
   - timestamp: Discovery time

2. profit_analysis: Opportunity analyses
   - gift_id (PK, FK): NFT identifier
   - profit_percent: Expected ROI %
   - profit_ton: Expected profit (TON)
   - risk_score: Risk assessment (0-100)
   - confidence: Confidence level (0-100)
   - strategy: Strategy used
   - reasoning: Analysis details
   - target_price: Recommended sell price
   - timestamp: Analysis time

3. processed_gifts: Deduplication tracking
   - id (PK): NFT identifier
   - timestamp: Processing time

Usage Example:
--------------
    # Initialize database
    db = Database("nft_bot.db")

    # Save NFT listing
    gift = Gift(
        id="abc123",
        name="Delicious Cake",
        number=12345,
        price=5.5,
        collection_id="EQAbc...",
        photo_url="https://...",
        attributes=[
            {"type": "model", "value": "Chocolate"},
            {"type": "backdrop", "value": "Midnight Blue"}
        ]
    )
    db.save_gift(gift)

    # Check if already processed
    if not db.is_nft_processed(gift.id):
        # Analyze and save
        analysis = ProfitAnalysis(...)
        db.save_analysis(analysis)
        db.mark_nft_as_processed(gift)

    # Query recent gifts
    recent = db.get_recent_gifts(limit=10)

Threading:
----------
SQLite connections are thread-safe with proper usage. Each method
creates its own connection via context manager, making concurrent
access safe.

Performance:
------------
- Indexed queries on timestamp and price
- Connection pooling via context managers
- Batch operations for bulk inserts

Author: [Your Name]
Version: 2.2 (2025-11-19)
Repository: https://github.com/yourusername/nft-gift-bot
"""

import json
import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Generator

logger = logging.getLogger(__name__)


# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class Gift:
    """
    NFT gift marketplace listing with metadata.

    Represents a single NFT available for purchase on the marketplace,
    including all relevant attributes for profit analysis.

    Attributes:
        id: Unique identifier (typically blockchain transaction hash or marketplace ID)
        name: Human-readable NFT name (e.g., "Delicious Cake")
        number: Mint number in collection (e.g., #12345)
        price: Current listing price in TON
        collection_id: Smart contract address for the collection
        photo_url: Direct URL to NFT image/preview
        attributes: List of trait dictionaries with 'type' and 'value' keys
        platform: Marketplace platform identifier (default: "portals")
        url: Direct link to view/purchase NFT
        timestamp: When this listing was discovered by the bot

    Example:
        gift = Gift(
            id="2dd43a95-7682-4bab-b3cd-3e2b107a8436",
            name="Delicious Cake",
            number=12345,
            price=5.50,
            collection_id="EQAbc...",
            photo_url="https://cdn.portals.gift/abc.jpg",
            attributes=[
                {"type": "model", "value": "Chocolate Mousse"},
                {"type": "backdrop", "value": "Midnight Blue"},
                {"type": "symbol", "value": "Heart"}
            ]
        )
    """
    id: str
    name: str
    number: int
    price: float
    collection_id: str
    photo_url: str
    attributes: List[Dict] = field(default_factory=list)
    platform: str = "portals"
    url: str = ""
    timestamp: Optional[datetime] = None

    def __post_init__(self):
        """Initialize computed fields and defaults."""
        if self.timestamp is None:
            self.timestamp = datetime.now()

        if not self.url:
            self.url = f"https://portals.gift/gift/{self.id}"

    @property
    def tg_id(self) -> int:
        """
        Telegram-compatible ID property.

        Provides backward compatibility with code expecting tg_id.

        Returns:
            NFT number (mint number in collection)
        """
        return self.number

    def get_attribute(self, attr_type: str) -> Optional[str]:
        """
        Get attribute value by type.

        Args:
            attr_type: Attribute type to search for ('model', 'backdrop', 'symbol')

        Returns:
            Attribute value if found, None otherwise

        Example:
            model = gift.get_attribute('model')
            # Returns: "Chocolate Mousse"
        """
        for attr in self.attributes:
            if attr.get('type') == attr_type:
                return attr.get('value')
        return None


@dataclass
class ProfitAnalysis:
    """
    Profit opportunity analysis result for an NFT.

    Contains all metrics needed to evaluate whether an NFT presents
    a profitable arbitrage opportunity.

    Attributes:
        gift_id: ID of analyzed NFT (foreign key to Gift)
        profit_percent: Expected net profit as percentage of buy price
        profit_ton: Expected net profit amount in TON
        risk_score: Risk assessment (0-100, lower is safer)
        confidence: Analysis confidence (0-100, higher is better)
        strategy: Trading strategy identifier (e.g., "Model arbitrage", "Premium backdrop")
        reasoning: Human-readable explanation of analysis
        target_price: Recommended sell price in TON

    Example:
        analysis = ProfitAnalysis(
            gift_id="2dd43a95...",
            profit_percent=45.2,
            profit_ton=2.48,
            risk_score=25.0,
            confidence=85.0,
            strategy="Model arbitrage",
            reasoning="Buy 5.50 TON, Sell 8.50 TON, Model floor 5.50",
            target_price=8.50
        )
    """
    gift_id: str
    profit_percent: float
    profit_ton: float
    risk_score: float
    confidence: float
    strategy: str
    reasoning: str
    target_price: float


# ============================================================================
# DATABASE CLASS
# ============================================================================

class Database:
    """
    SQLite database interface for NFT gift bot persistence.

    Provides high-level methods for storing and querying:
    - NFT marketplace listings
    - Profit analysis results
    - Processing state for deduplication

    Features:
    ---------
    - Automatic schema initialization
    - Context manager support for connections
    - Indexed queries for performance
    - Thread-safe operations
    - Legacy compatibility methods

    Thread Safety:
    --------------
    Each method creates its own database connection, making
    concurrent access safe. No connection pooling is needed
    for SQLite.

    Example:
        db = Database("nft_bot.db")

        # Check and save new listing
        if not db.is_nft_processed(gift.id):
            db.save_gift(gift)
            db.mark_nft_as_processed(gift)

        # Query statistics
        stats = db.get_statistics()
        print(f"Total gifts: {stats['total_gifts']}")
    """

    def __init__(self, db_path: str):
        """
        Initialize database connection and create schema.

        Args:
            db_path: Path to SQLite database file (will be created if missing)

        Example:
            db = Database("data/nft_bot.db")
        """
        self.db_path = db_path
        self.init_database()
        logger.info(f"Database initialized at {db_path}")

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Context manager for database connections.

        Automatically commits on success, rolls back on error,
        and always closes connection.

        Yields:
            SQLite connection object

        Example:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM gifts")
                results = cursor.fetchall()
        """
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database transaction failed: {e}")
            raise
        finally:
            conn.close()

    def init_database(self) -> None:
        """
        Create database schema if it doesn't exist.

        Creates three main tables:
        1. gifts - NFT marketplace listings
        2. profit_analysis - Opportunity analyses
        3. processed_gifts - Deduplication tracking

        Also creates indexes for performance optimization.

        Raises:
            sqlite3.Error: If table creation fails
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Gifts table - NFT marketplace listings
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

                # Profit analysis table - opportunity analyses
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS profit_analysis (
                        gift_id TEXT PRIMARY KEY,
                        profit_percent REAL NOT NULL,
                        profit_ton REAL NOT NULL,
                        risk_score REAL NOT NULL,
                        confidence REAL NOT NULL,
                        strategy TEXT NOT NULL,
                        reasoning TEXT NOT NULL,
                        target_price REAL NOT NULL,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (gift_id) REFERENCES gifts (id)
                            ON DELETE CASCADE
                    )
                ''')

                # Processed gifts table - deduplication tracking
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS processed_gifts (
                        id TEXT PRIMARY KEY,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                # Performance indexes
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_gifts_timestamp 
                    ON gifts(timestamp DESC)
                ''')

                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_gifts_price 
                    ON gifts(price)
                ''')

                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_gifts_name 
                    ON gifts(name)
                ''')

                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_processed_timestamp 
                    ON processed_gifts(timestamp DESC)
                ''')

                logger.info("Database schema initialized successfully")

        except sqlite3.Error as e:
            logger.error(f"Failed to initialize database: {e}")
            raise

    # ========================================================================
    # GIFT OPERATIONS
    # ========================================================================

    def save_gift(self, gift: Gift) -> bool:
        """
        Save or update NFT gift in database.

        Uses INSERT OR REPLACE to handle both new entries and updates.

        Args:
            gift: Gift object to persist

        Returns:
            True if successful, False on error

        Example:
            success = db.save_gift(gift)
            if success:
                print("Gift saved successfully")
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO gifts 
                    (id, name, number, price, collection_id, photo_url, 
                     attributes, platform, url, timestamp)
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
                    gift.timestamp.isoformat() if gift.timestamp else datetime.now().isoformat()
                ))

                logger.debug(f"Saved gift {gift.id} ({gift.name})")
                return True

        except sqlite3.Error as e:
            logger.error(f"Failed to save gift {gift.id}: {e}")
            return False

        except Exception as e:
            logger.error(f"Unexpected error saving gift {gift.id}: {e}")
            return False

    def get_gift(self, gift_id: str) -> Optional[Gift]:
        """
        Retrieve gift by ID.

        Args:
            gift_id: Unique gift identifier

        Returns:
            Gift object if found, None otherwise

        Example:
            gift = db.get_gift("2dd43a95...")
            if gift:
                print(f"Found: {gift.name}")
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, name, number, price, collection_id, photo_url,
                           attributes, platform, url, timestamp
                    FROM gifts
                    WHERE id = ?
                ''', (gift_id,))

                row = cursor.fetchone()
                if row:
                    return Gift(
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
                    )
                return None

        except Exception as e:
            logger.error(f"Error retrieving gift {gift_id}: {e}")
            return None

    def get_recent_gifts(self, limit: int = 10) -> List[Gift]:
        """
        Retrieve most recent gifts from database.

        Args:
            limit: Maximum number of gifts to return (default: 10)

        Returns:
            List of Gift objects, ordered by timestamp descending (newest first)

        Example:
            recent = db.get_recent_gifts(limit=20)
            for gift in recent:
                print(f"{gift.name}: {gift.price} TON")
        """
        gifts = []

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, name, number, price, collection_id, photo_url,
                           attributes, platform, url, timestamp
                    FROM gifts
                    ORDER BY timestamp DESC
                    LIMIT ?
                ''', (limit,))

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

        except Exception as e:
            logger.error(f"Error retrieving recent gifts: {e}")

        return gifts

    # ========================================================================
    # PROFIT ANALYSIS OPERATIONS
    # ========================================================================

    def save_analysis(self, analysis: ProfitAnalysis) -> bool:
        """
        Save profit analysis result to database.

        Args:
            analysis: ProfitAnalysis object to persist

        Returns:
            True if successful, False on error

        Example:
            success = db.save_analysis(analysis)
            if success:
                print("Analysis saved")
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO profit_analysis
                    (gift_id, profit_percent, profit_ton, risk_score, 
                     confidence, strategy, reasoning, target_price)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    analysis.gift_id,
                    analysis.profit_percent,
                    analysis.profit_ton,
                    analysis.risk_score,
                    analysis.confidence,
                    analysis.strategy,
                    analysis.reasoning,
                    analysis.target_price
                ))

                logger.debug(f"Saved analysis for gift {analysis.gift_id}")
                return True

        except sqlite3.Error as e:
            logger.error(f"Failed to save analysis for {analysis.gift_id}: {e}")
            return False

        except Exception as e:
            logger.error(f"Unexpected error saving analysis for {analysis.gift_id}: {e}")
            return False

    def get_analysis(self, gift_id: str) -> Optional[ProfitAnalysis]:
        """
        Retrieve profit analysis by gift ID.

        Args:
            gift_id: Unique gift identifier

        Returns:
            ProfitAnalysis object if found, None otherwise

        Example:
            analysis = db.get_analysis("2dd43a95...")
            if analysis:
                print(f"ROI: {analysis.profit_percent}%")
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT gift_id, profit_percent, profit_ton, risk_score,
                           confidence, strategy, reasoning, target_price
                    FROM profit_analysis
                    WHERE gift_id = ?
                ''', (gift_id,))

                row = cursor.fetchone()
                if row:
                    return ProfitAnalysis(
                        gift_id=row[0],
                        profit_percent=row[1],
                        profit_ton=row[2],
                        risk_score=row[3],
                        confidence=row[4],
                        strategy=row[5],
                        reasoning=row[6],
                        target_price=row[7]
                    )
                return None

        except Exception as e:
            logger.error(f"Error retrieving analysis for {gift_id}: {e}")
            return None

    # ========================================================================
    # PROCESSING STATE OPERATIONS
    # ========================================================================

    def is_processed(self, gift_id: str) -> bool:
        """
        Check if gift was already processed (analyzed).

        Used for deduplication to avoid re-analyzing the same NFT.

        Args:
            gift_id: Unique gift identifier

        Returns:
            True if already processed, False if new

        Example:
            if not db.is_processed(gift.id):
                # Analyze this new NFT
                analysis = analyzer.analyze(gift)
                db.save_analysis(analysis)
                db.mark_processed(gift.id)
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT id FROM processed_gifts WHERE id = ?',
                    (gift_id,)
                )
                return cursor.fetchone() is not None

        except Exception as e:
            logger.error(f"Error checking processed status for {gift_id}: {e}")
            return False  # Fail-safe: treat as not processed

    def mark_processed(self, gift_id: str) -> bool:
        """
        Mark gift as processed to prevent duplicate analysis.

        Args:
            gift_id: Unique gift identifier

        Returns:
            True if successful, False on error

        Example:
            db.mark_processed(gift.id)
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'INSERT OR IGNORE INTO processed_gifts (id) VALUES (?)',
                    (gift_id,)
                )

                logger.debug(f"Marked gift {gift_id} as processed")
                return True

        except Exception as e:
            logger.error(f"Error marking {gift_id} as processed: {e}")
            return False

    # ========================================================================
    # STATISTICS & UTILITIES
    # ========================================================================

    def get_statistics(self) -> Dict[str, int]:
        """
        Get database statistics.

        Returns:
            Dictionary with counts:
            - total_gifts: Total NFTs in database
            - total_analyses: Total profit analyses
            - processed_gifts: Total processed NFTs
            - gifts_today: Gifts discovered today

        Example:
            stats = db.get_statistics()
            print(f"Total gifts: {stats['total_gifts']}")
            print(f"Today: {stats['gifts_today']}")
        """
        stats = {
            'total_gifts': 0,
            'total_analyses': 0,
            'processed_gifts': 0,
            'gifts_today': 0
        }

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Total gifts
                cursor.execute('SELECT COUNT(*) FROM gifts')
                stats['total_gifts'] = cursor.fetchone()[0]

                # Total analyses
                cursor.execute('SELECT COUNT(*) FROM profit_analysis')
                stats['total_analyses'] = cursor.fetchone()[0]

                # Processed gifts
                cursor.execute('SELECT COUNT(*) FROM processed_gifts')
                stats['processed_gifts'] = cursor.fetchone()[0]

                # Gifts today
                today = datetime.now().date().isoformat()
                cursor.execute(
                    'SELECT COUNT(*) FROM gifts WHERE DATE(timestamp) = ?',
                    (today,)
                )
                stats['gifts_today'] = cursor.fetchone()[0]

        except Exception as e:
            logger.error(f"Error getting statistics: {e}")

        return stats

    def cleanup_old_entries(self, days: int = 30) -> int:
        """
        Remove processed gifts older than specified days.

        Keeps database size manageable by removing old deduplication entries.
        Does NOT remove gifts or analyses, only processed_gifts tracking.

        Args:
            days: Number of days to keep (default: 30)

        Returns:
            Number of entries removed

        Example:
            removed = db.cleanup_old_entries(days=7)
            print(f"Removed {removed} old entries")
        """
        try:
            cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()

            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'DELETE FROM processed_gifts WHERE timestamp < ?',
                    (cutoff_date,)
                )
                removed = cursor.rowcount

                logger.info(f"Cleaned up {removed} processed gifts older than {days} days")
                return removed

        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
            return 0

    # ========================================================================
    # LEGACY COMPATIBILITY METHODS
    # ========================================================================

    def is_nft_processed(self, nft_id: str) -> bool:
        """
        Legacy alias for is_processed().

        Provided for backward compatibility with older code.

        Args:
            nft_id: Unique NFT identifier

        Returns:
            True if already processed, False otherwise
        """
        return self.is_processed(nft_id)

    def mark_nft_as_processed(self, gift: Gift) -> None:
        """
        Legacy method to mark NFT as processed.

        Saves gift data and marks as processed in one operation.
        Provided for backward compatibility.

        Args:
            gift: Gift object to save and mark

        Example:
            db.mark_nft_as_processed(gift)
        """
        try:
            self.save_gift(gift)
            self.mark_processed(gift.id)
            logger.debug(f"NFT {gift.id} marked as processed (legacy method)")

        except Exception as e:
            logger.error(f"Error in legacy mark_nft_as_processed for {gift.id}: {e}")


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def create_backup(db_path: str, backup_path: Optional[str] = None) -> bool:
    """
    Create a backup copy of the database.

    Args:
        db_path: Path to source database
        backup_path: Optional custom backup path (default: appends .backup)

    Returns:
        True if successful, False on error

    Example:
        success = create_backup("nft_bot.db", "backups/nft_bot_2025-11-19.db")
    """
    import shutil

    if not backup_path:
        backup_path = f"{db_path}.backup"

    try:
        shutil.copy2(db_path, backup_path)
        logger.info(f"Database backed up to {backup_path}")
        return True

    except Exception as e:
        logger.error(f"Failed to create backup: {e}")
        return False
