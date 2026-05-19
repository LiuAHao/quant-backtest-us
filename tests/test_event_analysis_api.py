from __future__ import annotations

import backend.db.database as database
from tests.helpers.api import ApiTestCase


class EventAnalysisApiTest(ApiTestCase):
    def _seed_event_definition(self):
        with database.get_conn() as conn:
            conn.execute(
                "INSERT INTO event_definitions (id, key, name, description, source, tags_json, status, current_version_id, created_at, updated_at) VALUES (1, 'test_event', 'Test Event', '', 'manual', '[]', 'enabled', 1, '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            )
            conn.execute(
                "INSERT INTO event_definition_versions (id, event_definition_id, version, code, code_hash, file_path, validation_status, validation_message, created_at) VALUES (1, 1, 1, 'pass', 'abc', '/tmp/x.py', 'passed', '', '2026-01-01 00:00:00')"
            )

    def test_event_analysis_page_default(self):
        self._seed_event_definition()
        with database.get_conn() as conn:
            for _ in range(3):
                conn.execute(
                    "INSERT INTO event_analysis_tasks (event_definition_id, event_definition_version_id, status, start_date, end_date, created_at) VALUES (1, 1, 'queued', '2026-01-01', '2026-01-31', '2026-01-01 00:00:00')"
                )
        resp = self.client.get("/api/event-analyses/page")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["total"], 3)
        self.assertEqual(body["page"], 1)
        self.assertEqual(len(body["items"]), 3)

    def test_event_analysis_page_with_pagination(self):
        self._seed_event_definition()
        with database.get_conn() as conn:
            for _ in range(5):
                conn.execute(
                    "INSERT INTO event_analysis_tasks (event_definition_id, event_definition_version_id, status, start_date, end_date, created_at) VALUES (1, 1, 'queued', '2026-01-01', '2026-01-31', '2026-01-01 00:00:00')"
                )
        resp = self.client.get("/api/event-analyses/page?page=1&page_size=2")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["total"], 5)
        self.assertEqual(len(body["items"]), 2)

        resp2 = self.client.get("/api/event-analyses/page?page=3&page_size=2")
        self.assertEqual(resp2.status_code, 200)
        body2 = resp2.json()
        self.assertEqual(body2["total"], 5)
        self.assertEqual(len(body2["items"]), 1)

    def test_event_analysis_batch_delete(self):
        self._seed_event_definition()
        with database.get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO event_analysis_tasks (event_definition_id, event_definition_version_id, status, start_date, end_date, created_at) VALUES (1, 1, 'success', '2026-01-01', '2026-01-31', '2026-01-01 00:00:00')"
            )
            t1_id = cursor.lastrowid
            cursor = conn.execute(
                "INSERT INTO event_analysis_tasks (event_definition_id, event_definition_version_id, status, start_date, end_date, created_at) VALUES (1, 1, 'success', '2026-01-01', '2026-01-31', '2026-01-01 00:00:00')"
            )
            t2_id = cursor.lastrowid
        resp = self.client.post("/api/event-analyses/batch-delete", json={"ids": [t1_id, t2_id, 99999]})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["ok"])
        self.assertEqual(sorted(body["deleted_ids"]), sorted([t1_id, t2_id]))
        self.assertEqual(len(body["failed"]), 1)
        self.assertEqual(body["failed"][0]["id"], 99999)

    def test_event_analysis_batch_delete_refuses_running(self):
        self._seed_event_definition()
        with database.get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO event_analysis_tasks (event_definition_id, event_definition_version_id, status, start_date, end_date, created_at) VALUES (1, 1, 'running', '2026-01-01', '2026-01-31', '2026-01-01 00:00:00')"
            )
            t_id = cursor.lastrowid
        resp = self.client.post("/api/event-analyses/batch-delete", json={"ids": [t_id]})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["ok"])
        self.assertEqual(len(body["deleted_ids"]), 0)
        self.assertIn("终止", body["failed"][0]["reason"])
