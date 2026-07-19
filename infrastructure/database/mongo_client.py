"""
infrastructure/database/mongo_client.py
Singleton MongoDB client connection.
"""

import logging
from pymongo import MongoClient
from pymongo.database import Database

from config.settings import settings

logger = logging.getLogger(__name__)

_client: MongoClient | None = None


def get_client() -> MongoClient:
    """
    Trả về singleton MongoClient.
    Ping để verify connection lần đầu tạo.
    """
    global _client
    if _client is None:
        logger.info(f"Connecting to MongoDB: {settings.MONGODB_URI}")
        _client = MongoClient(
            settings.MONGODB_URI,
            serverSelectionTimeoutMS=5000,
        )
        # Verify connection
        try:
            _client.admin.command("ping")
            logger.info("MongoDB connection OK")
        except Exception as e:
            logger.warning(f"MongoDB ping failed: {e}. Will retry on first use.")
    return _client


def get_db() -> Database:
    """Trả về database instance."""
    return get_client()[settings.MONGODB_DB]


def close_client() -> None:
    """Đóng MongoDB connection."""
    global _client
    if _client is not None:
        _client.close()
        _client = None
        logger.info("MongoDB connection closed")
