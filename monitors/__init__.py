"""
NFT marketplace monitoring module.

Handles real-time monitoring of NFT listings, floor prices,
and market activity on Telegram Gifts marketplace.
"""

from .portals import PortalsMonitor

__all__ = ['PortalsMonitor']
