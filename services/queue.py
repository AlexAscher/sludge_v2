"""
Async queue system for managing concurrent file processing.
Prevents server overload by limiting concurrent users.
"""
import asyncio
from collections import deque
from typing import Dict, Optional
import logging
import time

logger = logging.getLogger(__name__)


class AsyncProcessingQueue:
    """Manages concurrent file processing with user limits"""

    def __init__(self, max_concurrent: int = 5):
        self.max_concurrent = max_concurrent
        self.active_users: Dict[int, asyncio.Task] = {}  # user_id -> task
        self.queue: deque = deque()  # Queue of pending tasks
        self.queue_positions: Dict[int, int] = {}  # user_id -> position in queue
        self._lock = asyncio.Lock()

    async def add_task(self, user_id: int, callback_query, count: int, file_uuid: str, media_type: str):
        """Add a task to the queue"""
        async with self._lock:
            # If user already has an active task, reject
            if user_id in self.active_users:
                return False, "You already have a task in progress. Please wait."

            # If user is in queue, reject
            if user_id in self.queue_positions:
                return False, "You're already in queue. Please wait."

            # If can process immediately
            if len(self.active_users) < self.max_concurrent:
                logger.info(f"Starting immediate processing for user {user_id}")
                task = asyncio.create_task(self._process_task(user_id, callback_query, count, file_uuid, media_type))
                self.active_users[user_id] = task
                return True, "Processing started immediately."

            # Otherwise add to queue
            self.queue.append({
                'user_id': user_id,
                'callback_query': callback_query,
                'count': count,
                'file_uuid': file_uuid,
                'media_type': media_type,
                'added_at': time.time()
            })
            self._update_queue_positions()
            position = self.queue_positions[user_id]
            logger.info(f"User {user_id} added to queue at position {position}")
            return True, "Your request is in queue. You'll be notified when processing starts."

    def _update_queue_positions(self):
        """Update queue position numbers"""
        self.queue_positions = {item['user_id']: idx + 1 for idx, item in enumerate(self.queue)}

    async def _process_task(self, user_id: int, callback_query, count: int, file_uuid: str, media_type: str):
        """Process a single task"""
        try:
            # Import here to avoid circular dependency
            from handlers.process import process_copies_internal

            logger.info(f"Processing task for user {user_id}: {count} copies")
            await process_copies_internal(callback_query, count, file_uuid, media_type)

        except Exception as e:
            logger.error(f"Error processing task for user {user_id}: {e}")
            try:
                await callback_query.message.answer(f"❌ Error processing your request: {e}")
            except Exception:
                pass
        finally:
            async with self._lock:
                # Remove from active users
                if user_id in self.active_users:
                    del self.active_users[user_id]

                # Process next in queue if available
                if self.queue:
                    next_task = self.queue.popleft()
                    self._update_queue_positions()

                    next_user_id = next_task['user_id']
                    logger.info(f"Starting queued task for user {next_user_id}")

                    # Notify user their task is starting
                    try:
                        await next_task['callback_query'].message.answer("🔄 Your task is now being processed...")
                    except Exception:
                        pass

                    task = asyncio.create_task(
                        self._process_task(
                            next_user_id,
                            next_task['callback_query'],
                            next_task['count'],
                            next_task['file_uuid'],
                            next_task['media_type']
                        )
                    )
                    self.active_users[next_user_id] = task

    def get_queue_position(self, user_id: int) -> Optional[int]:
        """Get user's position in queue"""
        return self.queue_positions.get(user_id)

    def get_status(self) -> Dict:
        """Get current queue status"""
        return {
            'active_users': len(self.active_users),
            'queued_users': len(self.queue),
            'max_concurrent': self.max_concurrent
        }


# Global queue instance
processing_queue = AsyncProcessingQueue(max_concurrent=5)
