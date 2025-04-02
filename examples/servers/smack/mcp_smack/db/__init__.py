"""
Database module for Smack Messaging Service.

This module provides the database interface for the Smack messaging service.
"""

from .postgres import MessageDB

__all__ = ["MessageDB"]
