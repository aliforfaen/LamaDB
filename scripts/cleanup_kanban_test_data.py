#!/usr/bin/env python3
"""Clean up kanban test data from development.

Deletes kanban boards/tasks with "test" in their name, associated
agent logs, comments, and test users. Runs inside the container.

Usage:
    docker exec lamadb_api python3 scripts/cleanup_kanban_test_data.py
"""
from __future__ import annotations

import asyncio
import os

import asyncpg


async def main() -> None:
    dsn = os.environ.get(
        "DATABASE_URL",
        "postgresql://lamadb:lamadb_secret@postgres:5432/lamadb",
    )
    conn = await asyncpg.connect(dsn)

    try:
        # ── Step 1: Find test boards ──────────────────────────
        test_boards = await conn.fetch(
            "SELECT id, name FROM kanban_boards "
            "WHERE name ILIKE '%test%'"
        )
        board_ids = [r["id"] for r in test_boards]
        print(f"Found {len(test_boards)} test board(s):")
        for r in test_boards:
            print(f"  {r['name']} ({r['id']})")

        # ── Step 2: Find tasks belonging to test boards ───────
        task_ids = []
        if board_ids:
            task_rows = await conn.fetch(
                "SELECT id FROM kanban_tasks WHERE board_id = ANY($1::uuid[])",
                board_ids,
            )
            task_ids = [r["id"] for r in task_rows]

        # ── Step 3: Delete agent_logs for test boards ─────────
        # (board_id FK has CASCADE, but task_id FK does not,
        #  so delete by both board_id and task_id to be safe)
        logs_deleted_count = 0
        if board_ids:
            result = await conn.execute(
                "DELETE FROM kanban_agent_logs WHERE board_id = ANY($1::uuid[])",
                board_ids,
            )
            logs_deleted_count += int(result.split()[-1])
        if task_ids:
            result = await conn.execute(
                "DELETE FROM kanban_agent_logs WHERE task_id = ANY($1::uuid[])",
                task_ids,
            )
            logs_deleted_count += int(result.split()[-1])
        print(f"Deleted {logs_deleted_count} agent log(s) for test boards")

        # ── Step 4: Delete the boards (CASCADEs to columns,
        #    tasks, subtasks, dependencies, comments) ──────────
        if board_ids:
            boards_deleted = await conn.execute(
                "DELETE FROM kanban_boards WHERE id = ANY($1::uuid[])",
                board_ids,
            )
            boards_count = int(boards_deleted.split()[-1])
            print(f"Deleted {boards_count} board(s)")

        # ── Step 5: Find and delete test users ────────────────
        test_users = await conn.fetch(
            "SELECT id, name FROM users WHERE name ILIKE '%test%'"
        )
        user_ids = [r["id"] for r in test_users]
        print(f"\nFound {len(test_users)} test user(s):")
        for r in test_users:
            print(f"  {r['name']} ({r['id']})")

        if user_ids:
            # Detach api_keys first
            keys_detached = await conn.execute(
                "UPDATE api_keys SET user_id = NULL WHERE user_id = ANY($1::uuid[])",
                user_ids,
            )
            keys_count = int(keys_detached.split()[-1])
            print(f"Detached {keys_count} API key(s) from test users")

            # Detach kanban references
            await conn.execute(
                "UPDATE kanban_boards SET owner_id = NULL WHERE owner_id = ANY($1::uuid[])",
                user_ids,
            )
            await conn.execute(
                "UPDATE kanban_tasks SET assignee_id = NULL WHERE assignee_id = ANY($1::uuid[])",
                user_ids,
            )
            await conn.execute(
                "UPDATE kanban_comments SET user_id = NULL WHERE user_id = ANY($1::uuid[])",
                user_ids,
            )
            await conn.execute(
                "UPDATE kanban_agent_logs SET user_id = NULL WHERE user_id = ANY($1::uuid[])",
                user_ids,
            )

            # Now safe to delete
            users_deleted = await conn.execute(
                "DELETE FROM users WHERE id = ANY($1::uuid[])",
                user_ids,
            )
            users_count = int(users_deleted.split()[-1])
            print(f"Deleted {users_count} user(s)")

        # ── Summary ────────────────────────────────────────────
        remaining_boards = await conn.fetchval("SELECT count(*) FROM kanban_boards")
        remaining_users = await conn.fetchval("SELECT count(*) FROM users")
        remaining_tasks = await conn.fetchval("SELECT count(*) FROM kanban_tasks")
        print(f"\nRemaining: {remaining_boards} boards, "
              f"{remaining_tasks} tasks, "
              f"{remaining_users} users")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
