from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from uuid import uuid4

import httpx

from backend.db.database import GENERATED_EVENT_ANALYSIS_DIR, get_conn
from backend.schemas import EventDefinitionCreate, EventDefinitionOut, EventDefinitionUpdate
from backend.services.ai_event_analysis_prompt import EVENT_ANALYSIS_SYSTEM_PROMPT
from backend.services.event_analysis_validator import EventAnalysisValidator
from config import settings


SOURCE_MAP = {
    "手动导入": "manual",
    "AI生成": "ai",
    "内置": "builtin",
}


class EventDefinitionService:
    def __init__(self):
        self.validator = EventAnalysisValidator()
        self._sync_current_files()

    def _sync_current_files(self):
        try:
            with get_conn() as conn:
                rows = conn.execute(
                    """
                    SELECT e.key, v.id AS version_id, v.code
                    FROM event_definitions e
                    JOIN event_definition_versions v ON v.id = e.current_version_id
                    """
                ).fetchall()
                for row in rows:
                    file_path = GENERATED_EVENT_ANALYSIS_DIR / f"{row['key']}.py"
                    self._write_event_file(file_path, row["code"])
                    conn.execute(
                        "UPDATE event_definition_versions SET file_path = ? WHERE id = ?",
                        (str(file_path), row["version_id"]),
                    )
        except Exception:
            pass

    def list_definitions(self) -> list[EventDefinitionOut]:
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT e.*, v.version, v.validation_status, v.validation_message, v.code
                FROM event_definitions e
                LEFT JOIN event_definition_versions v ON v.id = e.current_version_id
                ORDER BY e.updated_at DESC, e.id DESC
                """
            ).fetchall()
        return [self._row_to_out(row) for row in rows]

    def get_definition(self, definition_id: int) -> EventDefinitionOut | None:
        with get_conn() as conn:
            row = conn.execute(
                """
                SELECT e.*, v.version, v.validation_status, v.validation_message, v.code
                FROM event_definitions e
                LEFT JOIN event_definition_versions v ON v.id = e.current_version_id
                WHERE e.id = ?
                """,
                (definition_id,),
            ).fetchone()
        return self._row_to_out(row) if row else None

    def create_definition(self, payload: EventDefinitionCreate) -> EventDefinitionOut:
        key = self._normalize_key(payload.key)
        validation = self.validator.validate(payload.code)
        if not validation.ok:
            raise ValueError(validation.message)

        with get_conn() as conn:
            exists = conn.execute("SELECT id FROM event_definitions WHERE key = ?", (key,)).fetchone()
            if exists:
                raise ValueError("事件分析标识已存在")
            cursor = conn.execute(
                """
                INSERT INTO event_definitions (key, name, description, source, tags_json, status)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    key,
                    payload.name,
                    payload.description,
                    SOURCE_MAP.get(payload.source, payload.source),
                    json.dumps(payload.tags, ensure_ascii=False),
                    payload.status,
                ),
            )
            definition_id = int(cursor.lastrowid)
            version_id = self._insert_version(
                conn,
                definition_id,
                key,
                1,
                payload.code,
                self._hash_code(payload.code),
                validation.status,
                validation.message,
                validation.dependencies,
            )
            conn.execute(
                "UPDATE event_definitions SET current_version_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (version_id, definition_id),
            )
        definition = self.get_definition(definition_id)
        if definition is None:
            raise ValueError("事件分析保存失败")
        return definition

    def update_definition(self, definition_id: int, payload: EventDefinitionUpdate) -> EventDefinitionOut | None:
        current = self.get_definition(definition_id)
        if current is None:
            return None
        with get_conn() as conn:
            updates: list[str] = []
            values: list[object] = []
            if payload.name is not None:
                updates.append("name = ?")
                values.append(payload.name)
            if payload.description is not None:
                updates.append("description = ?")
                values.append(payload.description)
            if payload.source is not None:
                updates.append("source = ?")
                values.append(SOURCE_MAP.get(payload.source, payload.source))
            if payload.tags is not None:
                updates.append("tags_json = ?")
                values.append(json.dumps(payload.tags, ensure_ascii=False))
            if payload.status is not None:
                updates.append("status = ?")
                values.append(payload.status)
            if payload.code is not None:
                validation = self.validator.validate(payload.code)
                if not validation.ok:
                    raise ValueError(validation.message)
                version_id = self._insert_version(
                    conn,
                    definition_id,
                    current.key,
                    (current.version or 0) + 1,
                    payload.code,
                    self._hash_code(payload.code),
                    validation.status,
                    validation.message,
                    validation.dependencies,
                )
                updates.append("current_version_id = ?")
                values.append(version_id)
            if updates:
                values.append(definition_id)
                conn.execute(
                    f"UPDATE event_definitions SET {', '.join(updates)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    values,
                )
        return self.get_definition(definition_id)

    def set_status(self, definition_id: int, status: str) -> EventDefinitionOut | None:
        with get_conn() as conn:
            conn.execute(
                "UPDATE event_definitions SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status, definition_id),
            )
        return self.get_definition(definition_id)

    def delete_definition(self, definition_id: int) -> bool:
        with get_conn() as conn:
            definition = conn.execute(
                """
                SELECT e.id, e.key, e.current_version_id, v.file_path AS current_file_path
                FROM event_definitions e
                LEFT JOIN event_definition_versions v ON v.id = e.current_version_id
                WHERE e.id = ?
                """,
                (definition_id,),
            ).fetchone()
            if definition is None:
                return False
            running_tasks = conn.execute(
                "SELECT COUNT(*) as cnt FROM event_analysis_tasks WHERE event_definition_id = ? AND status IN ('queued', 'running')",
                (definition_id,),
            ).fetchone()
            if running_tasks and running_tasks["cnt"] > 0:
                raise ValueError("该事件定义存在运行中的分析任务，请先终止任务后再删除")
            current_file_path = definition["current_file_path"] or str(GENERATED_EVENT_ANALYSIS_DIR / f"{definition['key']}.py")
            file_path = Path(current_file_path)
            if file_path.exists() and file_path.is_file():
                try:
                    file_path.unlink()
                except OSError:
                    pass
            conn.execute("DELETE FROM event_definition_versions WHERE event_definition_id = ?", (definition_id,))
            conn.execute("DELETE FROM event_definitions WHERE id = ?", (definition_id,))
        return True

    def validate_code(self, code: str):
        result = self.validator.validate(code)
        return {
            "ok": result.ok,
            "status": result.status,
            "message": result.message,
            "class_name": result.class_name,
            "dependencies": result.dependencies,
        }

    def ai_fill(self, prompt: str, validation_feedback: str | None = None) -> dict:
        draft = self._generate_ai_definition(prompt, validation_feedback)
        code = draft["code"]
        validation = self.validator.validate(code)
        if not validation.ok:
            draft = self._generate_ai_definition(prompt, validation.message)
            code = draft["code"]
            validation = self.validator.validate(code)
            if not validation.ok:
                raise ValueError(f"AI 生成的事件分析未通过校验: {validation.message}")
        raw_key = str(draft.get("key") or self._build_ai_key_seed(prompt))
        key = f"{self._normalize_key(raw_key)[:48]}_{uuid4().hex[:8]}"
        return {
            "name": str(draft.get("name") or "AI 事件分析草稿")[:120],
            "key": key,
            "source": "AI生成",
            "description": str(draft.get("description") or f"根据自然语言描述生成：{prompt}"),
            "tags": self._normalize_tags(draft.get("tags")),
            "code": code,
        }

    def _insert_version(self, conn, definition_id: int, key: str, version: int, code: str, code_hash: str, validation_status: str, validation_message: str, dependencies: list[str]) -> int:
        GENERATED_EVENT_ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
        file_path = GENERATED_EVENT_ANALYSIS_DIR / f"{key}.py"
        self._write_event_file(file_path, code)
        cursor = conn.execute(
            """
            INSERT INTO event_definition_versions (
                event_definition_id, version, code, code_hash, file_path,
                validation_status, validation_message, dependencies_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                definition_id,
                version,
                code,
                code_hash,
                str(file_path),
                validation_status,
                validation_message,
                json.dumps(dependencies, ensure_ascii=False),
            ),
        )
        return int(cursor.lastrowid)

    def _write_event_file(self, file_path: Path, code: str) -> None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        if file_path.exists():
            try:
                if file_path.read_text(encoding="utf-8") == code:
                    return
            except OSError:
                pass
        file_path.write_text(code, encoding="utf-8")

    def _row_to_out(self, row) -> EventDefinitionOut:
        return EventDefinitionOut(
            id=row["id"],
            key=row["key"],
            name=row["name"],
            description=row["description"],
            source=row["source"],
            tags=json.loads(row["tags_json"] or "[]"),
            status=row["status"],
            current_version_id=row["current_version_id"],
            version=row["version"],
            validation_status=row["validation_status"],
            validation_message=row["validation_message"],
            code=row["code"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _normalize_key(self, key: str) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", key.strip()).strip("_").lower()
        if not normalized:
            raise ValueError("事件分析标识不能为空")
        return normalized

    def _hash_code(self, code: str) -> str:
        return hashlib.sha256(code.encode("utf-8")).hexdigest()

    def _generate_ai_definition(self, prompt: str, validation_error: str | None = None) -> dict:
        api_key = settings.AI_API_KEY or settings.OPENAI_API_KEY
        if not api_key:
            raise ValueError("缺少 AI_API_KEY，请在项目根目录 .env 中配置。")

        user_prompt = (
            "请根据下面的自然语言需求生成一个完整事件分析定义。\n"
            f"用户需求：{prompt.strip()}\n"
        )
        if validation_error:
            user_prompt += (
                "\n上一版代码没有通过项目校验，请修正后重新输出完整 JSON。\n"
                f"校验错误：{validation_error}\n"
            )

        payload = {
            "model": settings.AI_MODEL,
            "messages": [
                {"role": "system", "content": EVENT_ANALYSIS_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 4096,
        }
        url = settings.AI_BASE_URL.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with httpx.Client(timeout=180) as client:
                    response = client.post(url, headers=headers, json=payload)
                    response.raise_for_status()
                break
            except httpx.HTTPStatusError as exc:
                detail = exc.response.text[:500]
                raise ValueError(f"AI 接口返回错误: HTTP {exc.response.status_code} {detail}") from exc
            except (httpx.ReadTimeout, httpx.RemoteProtocolError, httpx.ConnectError) as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise ValueError(f"AI 接口调用失败: {exc}") from exc
            except httpx.HTTPError as exc:
                raise ValueError(f"AI 接口调用失败: {exc}") from exc
        else:
            raise ValueError(f"AI 接口调用失败: {last_error}")

        data = response.json()
        content = data["choices"][0].get("message", {}).get("content") or data["choices"][0].get("text") or ""
        if not content.strip():
            raise ValueError(f"AI 返回内容为空: {str(data)[:500]}")
        draft = self._parse_ai_json(content)
        if not isinstance(draft.get("code"), str) or not draft["code"].strip():
            raise ValueError("AI 返回内容缺少 code 字段")
        return draft

    def _parse_ai_json(self, content: str) -> dict:
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        if not text.startswith("{"):
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                text = text[start:end + 1]
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            preview = text[:300].replace("\n", "\\n")
            raise ValueError(f"AI 返回内容不是合法 JSON: {preview}") from exc

    def _build_ai_key_seed(self, prompt: str) -> str:
        key_seed = re.sub(r"[^a-zA-Z0-9_]+", "_", prompt.strip().lower())[:32].strip("_")
        return f"ai_event_analysis_{key_seed or 'draft'}"

    def _normalize_tags(self, tags) -> list[str]:
        if not isinstance(tags, list):
            return ["AI生成", "事件分析"]
        normalized = [str(tag)[:30] for tag in tags if str(tag).strip()]
        merged = ["AI生成", *normalized]
        return list(dict.fromkeys(merged))[:8]
