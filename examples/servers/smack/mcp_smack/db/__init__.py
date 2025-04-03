# Copyright (c) 2025 Featureform, Inc.
#
# Licensed under the MIT License. See LICENSE file in the project root for full license information.

"""
Database module for Smack Messaging Service.

This module provides the database interface for the Smack messaging service.
"""

from .postgres import MessageDB

__all__ = ["MessageDB"]
