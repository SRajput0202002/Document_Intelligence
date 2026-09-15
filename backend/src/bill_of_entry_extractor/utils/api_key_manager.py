#!/usr/bin/env python3
"""
Multi-API Key Manager with Rate Limiting
Handles round-robin API key selection and enforces rate limits per key
"""

import time
import threading
from typing import List, Optional
from dataclasses import dataclass, field
from collections import deque
from datetime import datetime, timedelta
import google.generativeai as genai


@dataclass
class APIKeyState:
    """State tracking for a single API key"""
    key: str
    requests_made: deque = field(default_factory=deque)  # Timestamps of recent requests
    is_available: bool = True
    last_error: Optional[str] = None
    error_count: int = 0
    total_requests: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def can_make_request(self, requests_per_minute: int) -> bool:
        """Check if this key can make a request within rate limit"""
        with self.lock:
            now = datetime.now()
            cutoff = now - timedelta(minutes=1)

            # Remove old timestamps
            while self.requests_made and self.requests_made[0] < cutoff:
                self.requests_made.popleft()

            # Check if under rate limit
            return len(self.requests_made) < requests_per_minute and self.is_available

    def record_request(self):
        """Record a successful request"""
        with self.lock:
            self.requests_made.append(datetime.now())
            self.total_requests += 1

    def record_error(self, error_msg: str):
        """Record an error for this key"""
        with self.lock:
            self.error_count += 1
            self.last_error = error_msg

            # Disable key after 5 consecutive errors
            if self.error_count >= 5:
                self.is_available = False

    def reset_errors(self):
        """Reset error count after successful request"""
        with self.lock:
            self.error_count = 0
            self.last_error = None
            self.is_available = True

    def get_wait_time(self, requests_per_minute: int) -> float:
        """Get time in seconds until this key can make next request"""
        with self.lock:
            if not self.requests_made:
                return 0.0

            oldest_request = self.requests_made[0]
            time_since_oldest = (datetime.now() - oldest_request).total_seconds()

            if time_since_oldest >= 60:
                return 0.0

            return max(0, 60 - time_since_oldest)


class APIKeyManager:
    """Manages multiple API keys with round-robin selection and rate limiting"""

    def __init__(self, api_keys: List[str], requests_per_minute: int = 15):
        if not api_keys:
            raise ValueError("At least one API key must be provided")

        self.key_states = [APIKeyState(key=key) for key in api_keys]
        self.requests_per_minute = requests_per_minute
        self.current_index = 0
        self.lock = threading.Lock()

        # Configure first key by default
        genai.configure(api_key=self.key_states[0].key)

    def get_available_key(self, wait: bool = True, max_wait: float = 60.0) -> str:
        """
        Get an available API key that's under rate limit

        Args:
            wait: If True, wait for a key to become available
            max_wait: Maximum time to wait in seconds

        Returns:
            API key string

        Raises:
            RuntimeError: If no keys available and wait=False or timeout exceeded
        """
        start_time = time.time()

        while True:
            # Try to find an available key
            key_state = self._find_available_key()

            if key_state:
                # Configure genai with this key
                genai.configure(api_key=key_state.key)
                return key_state.key

            # No keys available
            if not wait:
                raise RuntimeError("No API keys available within rate limit")

            # Check timeout
            elapsed = time.time() - start_time
            if elapsed >= max_wait:
                raise RuntimeError(f"Timeout waiting for available API key after {max_wait}s")

            # Wait a bit before trying again
            wait_time = min(1.0, max_wait - elapsed)
            time.sleep(wait_time)

    def _find_available_key(self) -> Optional[APIKeyState]:
        """Find next available key using round-robin"""
        with self.lock:
            # Try each key starting from current index
            for _ in range(len(self.key_states)):
                key_state = self.key_states[self.current_index]
                self.current_index = (self.current_index + 1) % len(self.key_states)

                if key_state.can_make_request(self.requests_per_minute):
                    return key_state

            return None

    def record_success(self, api_key: str):
        """Record a successful request for an API key"""
        key_state = self._get_key_state(api_key)
        if key_state:
            key_state.record_request()
            key_state.reset_errors()

    def record_failure(self, api_key: str, error_msg: str):
        """Record a failed request for an API key"""
        key_state = self._get_key_state(api_key)
        if key_state:
            key_state.record_error(error_msg)

    def _get_key_state(self, api_key: str) -> Optional[APIKeyState]:
        """Get key state by API key"""
        for key_state in self.key_states:
            if key_state.key == api_key:
                return key_state
        return None

    def get_stats(self) -> dict:
        """Get statistics for all API keys"""
        stats = {
            'total_keys': len(self.key_states),
            'available_keys': sum(1 for ks in self.key_states if ks.is_available),
            'total_requests': sum(ks.total_requests for ks in self.key_states),
            'keys': []
        }

        for i, key_state in enumerate(self.key_states):
            key_info = {
                'index': i,
                'key_preview': f"{key_state.key[:8]}...{key_state.key[-4:]}",
                'is_available': key_state.is_available,
                'total_requests': key_state.total_requests,
                'recent_requests': len(key_state.requests_made),
                'error_count': key_state.error_count,
                'last_error': key_state.last_error,
                'wait_time': key_state.get_wait_time(self.requests_per_minute)
            }
            stats['keys'].append(key_info)

        return stats

    def reset_all(self):
        """Reset all key states (useful for testing)"""
        with self.lock:
            for key_state in self.key_states:
                key_state.requests_made.clear()
                key_state.is_available = True
                key_state.last_error = None
                key_state.error_count = 0


if __name__ == "__main__":
    # Test the manager
    from config import config

    manager = APIKeyManager(
        api_keys=config.gemini.api_keys,
        requests_per_minute=config.gemini.requests_per_minute
    )

    print("API Key Manager initialized")
    print(f"Total keys: {len(manager.key_states)}")
    print(f"Rate limit: {manager.requests_per_minute} requests/minute per key")
    print()

    # Test getting keys
    for i in range(5):
        try:
            key = manager.get_available_key(wait=True, max_wait=5.0)
            print(f"Request {i+1}: Got key {key[:8]}...{key[-4:]}")
            manager.record_success(key)
        except RuntimeError as e:
            print(f"Request {i+1}: {e}")

    print("\nStats:")
    stats = manager.get_stats()
    for key_stat in stats['keys']:
        print(f"  Key {key_stat['index']}: {key_stat['total_requests']} requests, "
              f"available={key_stat['is_available']}, wait={key_stat['wait_time']:.1f}s")
