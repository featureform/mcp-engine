import sqlite3
from datetime import datetime
from typing import List, Optional, Tuple

class MessageDB:
    def __init__(self, db_path: str = "/Users/riddhibagadiaa/Documents/smack-mcp-server/messages.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the database and create the messages table if it doesn't exist."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.commit()

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
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'INSERT INTO messages (sender, content) VALUES (?, ?)',
                    (sender, content)
                )
                conn.commit()
                return True
        except sqlite3.Error as e:
            print(f"Error adding message to database: {e}")
            return False

    def get_all_messages(self) -> List[Tuple[int, str, str, str]]:
        """
        Retrieve all messages from the database.
        
        Returns:
            List of tuples containing (id, sender, content, timestamp)
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT id, sender, content, timestamp FROM messages ORDER BY timestamp DESC'
                )
                return cursor.fetchall()
        except sqlite3.Error as e:
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
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT id, sender, content, timestamp FROM messages WHERE id = ?',
                    (message_id,)
                )
                return cursor.fetchone()
        except sqlite3.Error as e:
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
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM messages WHERE id = ?', (message_id,))
                conn.commit()
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            print(f"Error deleting message from database: {e}")
            return False 