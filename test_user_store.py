#!/usr/bin/env python3
"""
Test script for UserStore persistent storage.
Verifies thread-safe JSON persistence and all methods.
"""

import os
import sys
import tempfile
import json
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from backend.db.user_store import UserStore


def test_user_store():
    """Test UserStore functionality with a temporary directory."""
    
    # Create temp directory for testing
    with tempfile.TemporaryDirectory() as temp_dir:
        print(f"Testing UserStore with directory: {temp_dir}")
        
        # Initialize store
        store = UserStore(data_dir=temp_dir)
        print("✅ UserStore initialized")
        
        # Test add_user
        user1 = {
            "user_id": "user_1",
            "username": "alice",
            "email": "alice@example.com",
            "password": "hashed_pwd_1",
            "full_name": "Alice Smith",
            "role": "student",
            "course_ids": [],
            "created_at": "2026-04-07"
        }
        store.add_user("alice", user1)
        print("✅ add_user() works")
        
        # Test get_user_by_username
        retrieved = store.get_user_by_username("alice")
        assert retrieved == user1, "Retrieved user doesn't match"
        print("✅ get_user_by_username() works")
        
        # Test get_user_by_id
        retrieved = store.get_user_by_id("user_1")
        assert retrieved == user1, "Retrieved user by ID doesn't match"
        print("✅ get_user_by_id() works")
        
        # Test user_exists
        assert store.user_exists("alice"), "user_exists should return True"
        assert not store.user_exists("bob"), "user_exists should return False"
        print("✅ user_exists() works")
        
        # Test email_exists
        assert store.email_exists("alice@example.com"), "email_exists should return True"
        assert not store.email_exists("bob@example.com"), "email_exists should return False"
        print("✅ email_exists() works")
        
        # Test add another user
        user2 = {
            "user_id": "user_2",
            "username": "bob",
            "email": "bob@example.com",
            "password": "hashed_pwd_2",
            "full_name": "Bob Jones",
            "role": "professor",
            "course_ids": [],
            "created_at": "2026-04-07"
        }
        store.add_user("bob", user2)
        print("✅ Added second user")
        
        # Test list_users
        users = store.list_users()
        assert len(users) == 2, "Should have 2 users"
        print("✅ list_users() works")
        
        # Test get_user_count
        assert store.get_user_count() == 2, "User count should be 2"
        print("✅ get_user_count() works")
        
        # Test update_user
        store.update_user("alice", {"course_ids": ["bio_101", "chem_101"]})
        updated = store.get_user_by_username("alice")
        assert updated["course_ids"] == ["bio_101", "chem_101"], "Update failed"
        print("✅ update_user() works")
        
        # Test delete_user
        store.delete_user("bob")
        assert not store.user_exists("bob"), "User should be deleted"
        assert store.get_user_count() == 1, "User count should be 1"
        print("✅ delete_user() works")
        
        # Test JSON persistence: create new store with same directory
        store2 = UserStore(data_dir=temp_dir)
        alice = store2.get_user_by_username("alice")
        assert alice is not None, "Persistence check failed"
        assert alice["course_ids"] == ["bio_101", "chem_101"], "Persisted data check failed"
        print("✅ Persistence to JSON works (data survives reload)")
        
        # Verify JSON file exists and has correct structure
        json_file = os.path.join(temp_dir, "users.json")
        assert os.path.exists(json_file), "JSON file should exist"
        with open(json_file, 'r') as f:
            data = json.load(f)
            assert "alice" in data, "Alice should be in JSON"
            assert data["alice"]["user_id"] == "user_1", "User data in JSON should match"
        print("✅ JSON file structure is correct")
        
        print("\n" + "="*50)
        print("✅ ALL TESTS PASSED")
        print("="*50)


if __name__ == "__main__":
    test_user_store()
