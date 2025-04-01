import psycopg2
from datetime import datetime
from typing import List, Optional, Tuple
import os
import atexit

class MessagePostgresDB:
    """PostgreSQL database interface for message storage with a single persistent connection."""
    
    _instance = None
    _connection = None
    
    def __new__(cls):
        """Singleton pattern to ensure only one database instance exists."""
        if cls._instance is None:
            cls._instance = super(MessagePostgresDB, cls).__new__(cls)
            cls._instance._initialize_connection()
            # Register cleanup function
            atexit.register(cls._instance._close_connection)
        return cls._instance
    
    def _initialize_connection(self):
        """Initialize the database connection."""
        # Get connection string from environment variable with fallback to individual parameters
        database_url = os.environ.get('DATABASE_URL')
        
        try:
            if database_url:
                # Use the complete DATABASE_URL if available
                self._connection = psycopg2.connect(database_url)
                print(f"PostgreSQL connection established using DATABASE_URL")
            else:
                # Fallback to individual parameters
                self.db_host = os.environ.get('DB_HOST', 'postgres')
                self.db_name = os.environ.get('DB_NAME', 'smack')
                self.db_user = os.environ.get('DB_USER', 'postgres')
                self.db_password = os.environ.get('DB_PASSWORD', 'postgres')
                self.db_port = os.environ.get('DB_PORT', '5432')
                
                self._connection = psycopg2.connect(
                    host=self.db_host,
                    database=self.db_name,
                    user=self.db_user,
                    password=self.db_password,
                    port=self.db_port
                )
                print(f"PostgreSQL connection established to {self.db_host}:{self.db_port}/{self.db_name}")
            
            self._init_db()
        except Exception as e:
            print(f"Error connecting to PostgreSQL: {e}")
            self._connection = None
    
    def _close_connection(self):
        """Close the database connection."""
        if self._connection:
            self._connection.close()
            print("PostgreSQL connection closed")
            self._connection = None
    
    def _ensure_connection(self):
        """Ensure the connection is active, reconnecting if necessary."""
        if self._connection is None or self._connection.closed:
            self._initialize_connection()
        
        # Test connection with a simple query
        try:
            cursor = self._connection.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
        except Exception as e:
            print(f"Connection test failed, reconnecting: {e}")
            self._initialize_connection()
        
        if self._connection is None or self._connection.closed:
            raise Exception("Failed to establish database connection")
        
        return self._connection

    def _init_db(self) -> None:
        """Initialize the database and create the messages table if it doesn't exist."""
        try:
            cursor = self._connection.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    sender TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            self._connection.commit()
            cursor.close()
        except Exception as e:
            print(f"Error initializing database: {e}")
            if self._connection:
                self._connection.rollback()

    def add_message(self, sender: str, content: str) -> bool:
        """
        Add a new message to the database.
        
        Args:
            sender: The name/identifier of the message sender
            content: The message content
            
        Returns:
            bool: True if message was added successfully, False otherwise
        """
        try:
            conn = self._ensure_connection()
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO messages (sender, content) VALUES (%s, %s)',
                (sender, content)
            )
            conn.commit()
            cursor.close()
            return True
        except Exception as e:
            print(f"Error adding message to database: {e}")
            if self._connection:
                self._connection.rollback()
            return False

    def get_all_messages(self) -> List[Tuple[int, str, str, str]]:
        """
        Retrieve all messages from the database.
        
        Returns:
            List of tuples containing (id, sender, content, timestamp)
        """
        try:
            conn = self._ensure_connection()
            cursor = conn.cursor()
            cursor.execute(
                'SELECT id, sender, content, timestamp FROM messages ORDER BY timestamp DESC'
            )
            messages = cursor.fetchall()
            cursor.close()
            return messages
        except Exception as e:
            print(f"Error retrieving messages from database: {e}")
            return []

    def get_message_by_id(self, message_id: int) -> Optional[Tuple[int, str, str, str]]:
        """
        Retrieve a specific message by its ID.
        
        Args:
            message_id: The ID of the message to retrieve
            
        Returns:
            Tuple containing (id, sender, content, timestamp) or None if not found
        """
        try:
            conn = self._ensure_connection()
            cursor = conn.cursor()
            cursor.execute(
                'SELECT id, sender, content, timestamp FROM messages WHERE id = %s',
                (message_id,)
            )
            message = cursor.fetchone()
            cursor.close()
            return message
        except Exception as e:
            print(f"Error retrieving message from database: {e}")
            return None

    def delete_message(self, message_id: int) -> bool:
        """
        Delete a message from the database.
        
        Args:
            message_id: The ID of the message to delete
            
        Returns:
            bool: True if message was deleted successfully, False otherwise
        """
        try:
            conn = self._ensure_connection()
            cursor = conn.cursor()
            cursor.execute('DELETE FROM messages WHERE id = %s', (message_id,))
            deleted = cursor.rowcount > 0
            conn.commit()
            cursor.close()
            return deleted
        except Exception as e:
            print(f"Error deleting message from database: {e}")
            if self._connection:
                self._connection.rollback()
            return False