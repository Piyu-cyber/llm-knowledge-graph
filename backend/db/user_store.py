"""
Persistent user storage using JSON with thread-safe access.
"""

import json
import os
import threading
from typing import Dict, Optional, List
import logging

logger = logging.getLogger(__name__)


class UserStore:
    """Thread-safe persistent user store backed by JSON file."""
    
    def __init__(self, data_dir: str = "data"):
        """
        Initialize the user store.
        
        Args:
            data_dir: Directory where users.json will be stored
        """
        self.data_dir = data_dir
        self.file_path = os.path.join(data_dir, "users.json")
        self._lock = threading.Lock()
        
        # Ensure data directory exists
        os.makedirs(data_dir, exist_ok=True)
        
        # Initialize file if it doesn't exist
        if not os.path.exists(self.file_path):
            self._write_file({})
    
    def _read_file(self) -> Dict:
        """
        Read users from JSON file.
        Must be called within a lock.
        
        Returns:
            Dictionary of users keyed by username
        """
        try:
            if not os.path.exists(self.file_path):
                return {}
            
            with open(self.file_path, 'r') as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.error(f"Error reading user store: {e}")
            return {}
    
    def _write_file(self, data: Dict) -> None:
        """
        Write users to JSON file atomically.
        Must be called within a lock.
        
        Args:
            data: Dictionary of users to write
        """
        try:
            # Write to temp file first, then move (atomic on most systems)
            temp_path = self.file_path + ".tmp"
            with open(temp_path, 'w') as f:
                json.dump(data, f, indent=2)
            
            # Atomic move
            if os.name == 'nt':  # Windows
                # On Windows, need to remove target first
                if os.path.exists(self.file_path):
                    os.remove(self.file_path)
            
            os.rename(temp_path, self.file_path)
        except Exception as e:
            logger.error(f"Error writing user store: {e}")
            raise
    
    def add_user(self, username: str, user_dict: Dict) -> None:
        """
        Add a new user to the store.
        
        Args:
            username: Username (key)
            user_dict: User data dictionary
        """
        with self._lock:
            users = self._read_file()
            users[username] = user_dict
            self._write_file(users)
            logger.debug(f"Added user: {username}")
    
    def get_user_by_username(self, username: str) -> Optional[Dict]:
        """
        Get user by username.
        
        Args:
            username: Username to look up
            
        Returns:
            User dict or None if not found
        """
        with self._lock:
            users = self._read_file()
            return users.get(username)
    
    def get_user_by_email(self, email: str) -> Optional[Dict]:
        """
        Get user by email.
        
        Args:
            email: Email to look up
            
        Returns:
            User dict or None if not found
        """
        with self._lock:
            users = self._read_file()
            for user in users.values():
                if user.get("email") == email:
                    return user
            return None
    
    def get_user_by_id(self, user_id: str) -> Optional[Dict]:
        """
        Get user by user_id.
        
        Args:
            user_id: User ID to look up
            
        Returns:
            User dict or None if not found
        """
        with self._lock:
            users = self._read_file()
            for user in users.values():
                if user.get("user_id") == user_id:
                    return user
            return None
    
    def update_user(self, username: str, updates: Dict) -> None:
        """
        Update specific fields of a user.
        
        Args:
            username: Username to update
            updates: Dictionary of fields to update
        """
        with self._lock:
            users = self._read_file()
            if username not in users:
                raise ValueError(f"User not found: {username}")
            
            users[username].update(updates)
            self._write_file(users)
            logger.debug(f"Updated user: {username}")
    
    def list_users(self) -> List[Dict]:
        """
        Get all users.
        
        Returns:
            List of all user dictionaries
        """
        with self._lock:
            users = self._read_file()
            return list(users.values())
    
    def user_exists(self, username: str) -> bool:
        """
        Check if user exists by username.
        
        Args:
            username: Username to check
            
        Returns:
            True if user exists, False otherwise
        """
        with self._lock:
            users = self._read_file()
            return username in users
    
    def email_exists(self, email: str) -> bool:
        """
        Check if email is already registered.
        
        Args:
            email: Email to check
            
        Returns:
            True if email exists, False otherwise
        """
        with self._lock:
            users = self._read_file()
            for user in users.values():
                if user.get("email") == email:
                    return True
            return False
    
    def delete_user(self, username: str) -> None:
        """
        Delete a user by username.
        
        Args:
            username: Username to delete
        """
        with self._lock:
            users = self._read_file()
            if username in users:
                del users[username]
                self._write_file(users)
                logger.debug(f"Deleted user: {username}")
    
    def get_user_count(self) -> int:
        """
        Get total number of users.
        
        Returns:
            Number of users in store
        """
        with self._lock:
            users = self._read_file()
            return len(users)
