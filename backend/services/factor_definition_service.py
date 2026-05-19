from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from uuid import uuid4

import httpx

from backend.db.database import GENERATED_FACTOR_ANALYSIS_DIR, get_conn
from backend.schemas import FactorDefinitionCreate, FactorDefinitionOut, FactorDefinitionUpdate
from backend.services.ai_factor_analysis_prompt import FACTOR_ANALYSIS_SYSTEM_PROMPT
from backend.services.factor_analysis_validator import FactorAnalysisValidator
from config import settings


SOURCE_MAP = {
    "手动导入": "manual",
    "AI生成": "ai",
    "内置": "builtin",
}

MOMENTUM_20_FACTOR_SQL_CODE = """from __future__ import annotations

from factor_analysis.template import FactorAnalysisTemplate


class Momentum20Factor(FactorAnalysisTemplate):
    def __init__(self):
        super().__init__(\"20日动量因子\")

    def compute(self, context):
        current_date = context[\"current_date\"].strftime(\"%Y-%m-%d\")
        market = context[\"market_data\"][[\"ts_code\"]].drop_duplicates().copy()
        market[\"ts_code\"] = market[\"ts_code\"].astype(str)
        if market.empty:
            return market.assign(trade_date=current_date, factor_value=[])

        sql = f\"\"\"
            WITH recent AS (
                SELECT
                    d.ts_code,
                    d.close,
                    ROW_NUMBER() OVER (PARTITION BY d.ts_code ORDER BY d.trade_date DESC) AS rn
                FROM daily_bar d
                WHERE d.trade_date <= '{current_date}'
                  AND d.ts_code IN (
                      SELECT ts_code FROM market_codes
                  )
            ), pivoted AS (
                SELECT
                    ts_code,
                    MAX(CASE WHEN rn = 1 THEN close END) AS close_now,
                    MAX(CASE WHEN rn = 21 THEN close END) AS close_then
                FROM recent
                WHERE rn <= 21
                GROUP BY ts_code
            )
            SELECT
                ts_code,
                '{current_date}' AS trade_date,
                close_now / NULLIF(close_then, 0) - 1 AS factor_value
            FROM pivoted
            WHERE close_now IS NOT NULL
              AND close_then IS NOT NULL
        \"\"\"
        context[\"conn\"].register(\"market_codes\", market)
        try:
            return context[\"conn\"].execute(sql).fetchdf()
        finally:
            context[\"conn\"].unregister(\"market_codes\")
""".strip()


class FactorDefinitionService:
    def __init__(self):
        self.validator = FactorAnalysisValidator()
        self._sync_current_files()
        self._sync_builtin_definitions()

    def _sync_current_files(self):
        try:
            with get_conn() as conn:
                rows = conn.execute(
                    """
                    SELECT f.key, v.id AS version_id, v.code
                    FROM factor_definitions f
                    JOIN factor_definition_versions v ON v.id = f.current_version_id
                    """
                ).fetchall()
                for row in rows:
                    file_path = GENERATED_FACTOR_ANALYSIS_DIR / f"{row['key']}.py"
                    self._write_factor_file(file_path, row["code"])
                    conn.execute(
                        "UPDATE factor_definition_versions SET file_path = ? WHERE id = ?",
                        (str(file_path), row["version_id"]),
                    )
        except Exception:
            pass

    def _sync_builtin_definitions(self):
        try:
            with get_conn() as conn:
                row = conn.execute(
                    """
                    SELECT f.id, f.key, f.current_version_id, v.version, v.code
                    FROM factor_definitions f
                    JOIN factor_definition_versions v ON v.id = f.current_version_id
                    WHERE f.key = ?
                    """,
                    ("momentum_20_factor",),
                ).fetchone()
                if row is None or not self._needs_momentum_factor_upgrade(row["code"]):
                    return
                validation = self.validator.validate(MOMENTUM_20_FACTOR_SQL_CODE)
                if not validation.ok:
                    return
                version_id = self._insert_version(
                    conn,
                    row["id"],
                    row["key"],
                    int(row["version"] or 0) + 1,
                    MOMENTUM_20_FACTOR_SQL_CODE,
                    self._hash_code(MOMENTUM_20_FACTOR_SQL_CODE),
                    validation.status,
                    validation.message,
                    validation.dependencies,
                )
                conn.execute(
                    "UPDATE factor_definitions SET current_version_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (version_id, row["id"]),
                )
        except Exception:
            pass

    def list_definitions(self) -> list[FactorDefinitionOut]:
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT f.*, v.version, v.validation_status, v.validation_message, v.code
                FROM factor_definitions f
                LEFT JOIN factor_definition_versions v ON v.id = f.current_version_id
                ORDER BY f.updated_at DESC, f.id DESC
                """
            ).fetchall()
        return [self._row_to_out(row) for row in rows]

    def get_definition(self, definition_id: int) -> FactorDefinitionOut | None:
        with get_conn() as conn:
            row = conn.execute(
                """
                SELECT f.*, v.version, v.validation_status, v.validation_message, v.code
                FROM factor_definitions f
                LEFT JOIN factor_definition_versions v ON v.id = f.current_version_id
                WHERE f.id = ?
                """,
                (definition_id,),
            ).fetchone()
        return self._row_to_out(row) if row else None

    def create_definition(self, payload: FactorDefinitionCreate) -> FactorDefinitionOut:
        key = self._normalize_key(payload.key)
        validation = self.validator.validate(payload.code)
        if not validation.ok:
            raise ValueError(validation.message)
        with get_conn() as conn:
            exists = conn.execute("SELECT id FROM factor_definitions WHERE key = ?", (key,)).fetchone()
            if exists:
                raise ValueError("因子标识已存在")
            cursor = conn.execute(
                """
                INSERT INTO factor_definitions (key, name, description, source, tags_json, status)
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
                "UPDATE factor_definitions SET current_version_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (version_id, definition_id),
            )
        definition = self.get_definition(definition_id)
        if definition is None:
            raise ValueError("因子定义保存失败")
        return definition

    def update_definition(self, definition_id: int, payload: FactorDefinitionUpdate) -> FactorDefinitionOut | None:
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
            if payload.code is not None and payload.code != current.code:
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
                    f"UPDATE factor_definitions SET {', '.join(updates)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    values,
                )
        return self.get_definition(definition_id)

    def set_status(self, definition_id: int, status: str) -> FactorDefinitionOut | None:
        with get_conn() as conn:
            conn.execute(
                "UPDATE factor_definitions SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status, definition_id),
            )
        return self.get_definition(definition_id)

    def delete_definition(self, definition_id: int) -> bool:
        with get_conn() as conn:
            definition = conn.execute(
                """
                SELECT f.id, f.key, v.file_path AS current_file_path
                FROM factor_definitions f
                LEFT JOIN factor_definition_versions v ON v.id = f.current_version_id
                WHERE f.id = ?
                """,
                (definition_id,),
            ).fetchone()
            if definition is None:
                return False
            running_tasks = conn.execute(
                "SELECT COUNT(*) as cnt FROM factor_analysis_tasks WHERE factor_definition_id = ? AND status IN ('queued', 'running')",
                (definition_id,),
            ).fetchone()
            if running_tasks and running_tasks["cnt"] > 0:
                raise ValueError("该因子定义存在运行中的分析任务，请先终止任务后再删除")
            current_file_path = definition["current_file_path"] or str(GENERATED_FACTOR_ANALYSIS_DIR / f"{definition['key']}.py")
            file_path = Path(current_file_path)
            if file_path.exists() and file_path.is_file():
                try:
                    file_path.unlink()
                except OSError:
                    pass
            conn.execute("DELETE FROM factor_definition_versions WHERE factor_definition_id = ?", (definition_id,))
            conn.execute("DELETE FROM factor_definitions WHERE id = ?", (definition_id,))
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
                raise ValueError(f"AI 生成的因子分析未通过校验: {validation.message}")
        raw_key = str(draft.get("key") or self._build_ai_key_seed(prompt))
        key = f"{self._normalize_key(raw_key)[:48]}_{uuid4().hex[:8]}"
        return {
            "name": str(draft.get("name") or "AI 因子分析草稿")[:120],
            "key": key,
            "source": "AI生成",
            "description": str(draft.get("description") or f"根据自然语言描述生成：{prompt}"),
            "tags": self._normalize_tags(draft.get("tags")),
            "code": code,
        }

    def _insert_version(self, conn, definition_id: int, key: str, version: int, code: str, code_hash: str, validation_status: str, validation_message: str, dependencies: list[str]) -> int:
        GENERATED_FACTOR_ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
        file_path = GENERATED_FACTOR_ANALYSIS_DIR / f"{key}.py"
        self._write_factor_file(file_path, code)
        cursor = conn.execute(
            """
            INSERT INTO factor_definition_versions (
                factor_definition_id, version, code, code_hash, file_path,
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

    def _write_factor_file(self, file_path: Path, code: str) -> None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        if file_path.exists():
            try:
                if file_path.read_text(encoding="utf-8") == code:
                    return
            except OSError:
                pass
        file_path.write_text(code, encoding="utf-8")

    def _row_to_out(self, row) -> FactorDefinitionOut:
        return FactorDefinitionOut(
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
            raise ValueError("因子标识不能为空")
        return normalized

    def _hash_code(self, code: str) -> str:
        return hashlib.sha256(code.encode("utf-8")).hexdigest()

    def _needs_momentum_factor_upgrade(self, code: str | None) -> bool:
        text = (code or "").strip()
        if not text:
            return False
        return "context[\"get_history\"](ts_code, current_date, window=21)" in text and "register(\"market_codes\", market)" not in text

    def _generate_ai_definition(self, prompt: str, validation_error: str | None = None) -> dict:
        api_key = settings.AI_API_KEY or settings.OPENAI_API_KEY
        if not api_key:
            raise ValueError("缺少 AI_API_KEY，请在项目根目录 .env 中配置。")

        user_prompt = (
            "请根据下面的自然语言需求生成一个完整因子分析定义。\n"
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
                {"role": "system", "content": FACTOR_ANALYSIS_SYSTEM_PROMPT},
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
        return f"ai_factor_analysis_{key_seed or 'draft'}"

    def _normalize_tags(self, tags) -> list[str]:
        if not isinstance(tags, list):
            return ["AI生成", "因子分析"]
        normalized = [str(tag)[:30] for tag in tags if str(tag).strip()]
        merged = ["AI生成", *normalized]
        return list(dict.fromkeys(merged))[:8]

    def _default_code(self) -> str:
        return """from __future__ import annotations

import pandas as pd

from factor_analysis.template import FactorAnalysisTemplate


class AiFactorAnalysis(FactorAnalysisTemplate):
    def __init__(self):
        super().__init__("AI 因子分析草稿")

    def compute(self, context):
        market_data = context["market_data"]
        return pd.DataFrame({
            "ts_code": market_data["ts_code"],
            "trade_date": context["current_date"].strftime("%Y-%m-%d"),
            "factor_value": market_data["close"],
        })
"""
