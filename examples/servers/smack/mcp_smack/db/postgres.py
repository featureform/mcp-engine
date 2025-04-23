# Copyright (c) 2025 Featureform, Inc.
#
# Licensed under the MIT License. See LICENSE file in the
# project root for full license information.

"""
PostgreSQL Database Interface for Smack Messaging Service.

This module provides a robust database interface for storing and retrieving messages
with proper connection management, error handling, and logging.
"""

import atexit
import logging
import os
import time
from contextlib import suppress

from psycopg2 import pool

# Configure logging
logger = logging.getLogger(__name__)


class MessageDB:
    """PostgreSQL database interface for message storage with connection pooling."""

    # Class-level connection pool
    _connection_pool = None
    _pool_min_conn = 1
    _pool_max_conn = 10

    def __init__(self):
        """Initialize the database connection pool if not already initialized."""
        if not hasattr(self, "_initialized"):
            self._initialize_connection_pool()
            # Register cleanup function
            atexit.register(self.close_connection)
            self._initialized = True

    def _initialize_connection_pool(self) -> None:
        """Initialize the database connection pool with retry logic."""
        # Get connection parameters from environment with secure defaults
        database_url = os.environ.get("DATABASE_URL")
        max_retries = int(os.environ.get("DB_MAX_RETRIES", "10"))
        retry_delay = int(os.environ.get("DB_RETRY_DELAY", "5"))

        # Set pool size from environment or use defaults
        self._pool_min_conn = int(os.environ.get("DB_MIN_CONNECTIONS", "1"))
        self._pool_max_conn = int(os.environ.get("DB_MAX_CONNECTIONS", "10"))

        retry_count = 0
        last_error = None

        while retry_count < max_retries:
            try:
                if database_url:
                    # Use the complete DATABASE_URL if available
                    self._connection_pool = pool.ThreadedConnectionPool(
                        self._pool_min_conn, self._pool_max_conn, database_url
                    )
                    logger.info(
                        "PostgreSQL connection pool established using DATABASE_URL"
                    )
                else:
                    # Fallback to individual parameters with secure defaults
                    self.db_host = os.environ.get("DB_HOST", "localhost")
                    self.db_name = os.environ.get("DB_NAME", "smack")
                    self.db_user = os.environ.get("DB_USER", "postgres")
                    self.db_password = os.environ.get("DB_PASSWORD", "")
                    self.db_port = os.environ.get("DB_PORT", "5432")

                    self._connection_pool = pool.ThreadedConnectionPool(
                        self._pool_min_conn,
                        self._pool_max_conn,
                        host=self.db_host,
                        database=self.db_name,
                        user=self.db_user,
                        password=self.db_password,
                        port=self.db_port,
                    )
                    logger.info(
                        f"PostgreSQL connection pool established to "
                        f"{self.db_host}:{self.db_port}/{self.db_name}"
                    )

                # Initialize database schema
                self._init_db()
                return

            except Exception as e:
                last_error = e
                retry_count += 1
                logger.warning(
                    f"Connection attempt {retry_count}/{max_retries} failed: {e}"
                )
                if retry_count < max_retries:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)

        # If we get here, all retries failed
        logger.error(
            f"Failed to establish database connection after {max_retries} attempts: "
            f"{last_error}"
        )
        logger.error(
            "Please ensure the database is running and accessible. "
            "Check your environment variables: "
            "DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD"
        )
        raise ConnectionError(f"Could not connect to database: {last_error}")

    def _init_db(self) -> None:
        """Initialize the database schema if it doesn't exist."""
        connection = None
        try:
            connection = self._get_connection()
            cursor = connection.cursor()

            # Create messages table with proper indexing
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    sender TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            connection.commit()
            cursor.close()
            logger.info("Database schema initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing database schema: {e}")
            if connection:
                connection.rollback()
            raise
        finally:
            self._return_connection(connection)

    def _get_connection(self):
        """Get a connection from the pool with validation."""
        if not self._connection_pool:
            logger.warning("Connection pool not initialized, attempting to reconnect")
            self._initialize_connection_pool()

        try:
            connection = self._connection_pool.getconn()
            # Test connection with a simple query
            cursor = connection.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            return connection
        except Exception as e:
            logger.error(f"Failed to get valid connection from pool: {e}")
            # Try to reinitialize the pool
            self._initialize_connection_pool()
            return self._connection_pool.getconn()

    def _return_connection(self, connection):
        """Return a connection to the pool safely."""
        if connection and self._connection_pool:
            try:
                self._connection_pool.putconn(connection)
            except Exception as e:
                logger.warning(f"Error returning connection to pool: {e}")
                # Try to close it directly if returning fails
                with suppress(Exception):
                    connection.close()

    def close_connection(self):
        """Close the database connection pool."""
        if self._connection_pool:
            try:
                self._connection_pool.closeall()
                logger.info("PostgreSQL connection pool closed")
                self._connection_pool = None
            except Exception as e:
                logger.error(f"Error closing connection pool: {e}")

    def add_message(self, sender: str, content: str) -> bool:
        """
        Add a new message to the database.

        Args:
            sender: The name/identifier of the message sender
            content: The message content

        Returns:
            bool: True if message was added successfully, False otherwise
        """
        connection = None
        try:
            # Input validation
            if not sender or not sender.strip():
                logger.warning("Attempted to add message with empty sender")
                return False

            if not content or not content.strip():
                logger.warning(f"Attempted to add empty message from {sender}")
                return False

            connection = self._get_connection()
            cursor = connection.cursor()
            cursor.execute(
                "INSERT INTO messages (sender, content) VALUES (%s, %s) RETURNING id",
                (sender, content),
            )
            message_id = cursor.fetchone()[0]
            connection.commit()
            cursor.close()
            logger.info(f"Message added successfully with ID {message_id}")
            return True
        except Exception as e:
            logger.error(f"Error adding message to database: {e}")
            if connection:
                connection.rollback()
            return False
        finally:
            self._return_connection(connection)

    def get_all_messages(self, limit: int = 100) -> list[tuple[int, str, str, str]]:
        """
        Retrieve messages from the database with pagination.

        Args:
            limit: Maximum number of messages to retrieve (default: 100)

        Returns:
            List of tuples containing (id, sender, content, timestamp)
        """
        connection = None
        try:
            connection = self._get_connection()
            cursor = connection.cursor()
            cursor.execute(
                "SELECT id, sender, content, timestamp "
                "FROM messages ORDER BY timestamp DESC LIMIT %s",
                (limit,),
            )
            messages = cursor.fetchall()
            cursor.close()
            logger.info(f"Retrieved {len(messages)} messages successfully")
            return messages
        except Exception as e:
            logger.error(f"Error retrieving messages from database: {e}")
            return []
        finally:
            self._return_connection(connection)

    def get_message_by_id(self, message_id: int) -> tuple[int, str, str, str] | None:
        """
        Retrieve a specific message by its ID.

        Args:
            message_id: The ID of the message to retrieve

        Returns:
            Tuple containing (id, sender, content, timestamp) or None if not found
        """
        connection = None
        try:
            if not isinstance(message_id, int) or message_id <= 0:
                logger.warning(f"Invalid message ID: {message_id}")
                return None

            connection = self._get_connection()
            cursor = connection.cursor()
            cursor.execute(
                "SELECT id, sender, content, timestamp FROM messages WHERE id = %s",
                (message_id,),
            )
            message = cursor.fetchone()
            cursor.close()

            if message:
                logger.info(f"Retrieved message with ID {message_id}")
            else:
                logger.info(f"No message found with ID {message_id}")

            return message
        except Exception as e:
            logger.error(f"Error retrieving message from database: {e}")
            return None
        finally:
            self._return_connection(connection)

    def delete_message(self, message_id: int) -> bool:
        """
        Delete a message from the database.

        Args:
            message_id: The ID of the message to delete

        Returns:
            bool: True if message was deleted successfully, False otherwise
        """
        connection = None
        try:
            if not isinstance(message_id, int) or message_id <= 0:
                logger.warning(f"Invalid message ID for deletion: {message_id}")
                return False

            connection = self._get_connection()
            cursor = connection.cursor()
            cursor.execute("DELETE FROM messages WHERE id = %s", (message_id,))
            deleted = cursor.rowcount > 0
            connection.commit()
            cursor.close()

            if deleted:
                logger.info(f"Message with ID {message_id} deleted successfully")
            else:
                logger.info(f"No message found with ID {message_id} for deletion")

            return deleted
        except Exception as e:
            logger.error(f"Error deleting message from database: {e}")
            if connection:
                connection.rollback()
            return False
        finally:
            self._return_connection(connection)
