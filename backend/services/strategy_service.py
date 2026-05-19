from __future__ import annotations

import ast
import hashlib
import json
import re
import time
import unicodedata
from uuid import uuid4
from pathlib import Path

import httpx

from config import settings
from backend.db.database import GENERATED_STRATEGY_DIR, get_conn
from backend.schemas import StrategyCreate, StrategyOut, StrategyUpdate, StrategyVersionOut
from backend.services.ai_strategy_prompt import STRATEGY_SYSTEM_PROMPT
from backend.services.strategy_validator import StrategyValidator


SOURCE_MAP = {
    "手动导入": "manual",
    "AI生成": "ai",
    "内置": "builtin",
}


class StrategyService:
    _startup_synced: bool = False

    def __init__(self):
        self.validator = StrategyValidator()
        if not StrategyService._startup_synced:
            self._sync_current_files()
            self._sync_file_strategies()
            StrategyService._startup_synced = True

    def _sync_current_files(self):
        try:
            with get_conn() as conn:
                rows = conn.execute(
                    """
                    SELECT s.key, v.id AS version_id, v.code
                    FROM strategies s
                    JOIN strategy_versions v ON v.id = s.current_version_id
                    """
                ).fetchall()
                for row in rows:
                    file_path = GENERATED_STRATEGY_DIR / f"{row['key']}.py"
                    self._write_strategy_file(file_path, row["code"])
                    conn.execute(
                        "UPDATE strategy_versions SET file_path = ? WHERE id = ?",
                        (str(file_path), row["version_id"]),
                    )
        except Exception:
            pass

    def _sync_file_strategies(self):
        """扫描文件系统，自动导入未注册的策略"""
        try:
            with get_conn() as conn:
                registered = {row["key"] for row in conn.execute("SELECT key FROM strategies").fetchall()}
            
            for py_file in GENERATED_STRATEGY_DIR.glob("*.py"):
                if py_file.name in ("__init__.py", "templates.py"):
                    continue
                
                key = py_file.stem.lower()
                key = "".join(c if c.isalnum() or c == "_" else "_" for c in key)
                key = key.strip("_")
                
                if key in registered:
                    continue
                
                code = py_file.read_text(encoding="utf-8")
                result = self.validator.validate(code)
                if not result.ok:
                    continue
                
                try:
                    self._import_strategy(key, py_file.stem, code)
                    registered.add(key)
                except Exception:
                    pass
        except Exception:
            pass

    def _import_strategy(self, key: str, name: str, code: str):
        """导入单个策略到数据库"""
        metadata = self.derive_metadata_from_code(code, fallback_name=name)
        strategy_name = str(metadata.get("name") or name)
        description = str(metadata.get("description") or strategy_name)
        tags = metadata.get("tags") if isinstance(metadata.get("tags"), list) else []

        with get_conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO strategies (key, name, description, source, tags_json, status) VALUES (?, ?, ?, ?, ?, ?)",
                (key, strategy_name, description, "ai", json.dumps(tags, ensure_ascii=False), "enabled"),
            )
            strategy = conn.execute("SELECT id FROM strategies WHERE key = ?", (key,)).fetchone()
            if strategy:
                conn.execute(
                    "INSERT OR IGNORE INTO strategy_versions (strategy_id, version, code, code_hash, file_path, validation_status, validation_message) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (strategy["id"], 1, code, hashlib.sha256(code.encode()).hexdigest(), str(GENERATED_STRATEGY_DIR / f"{name}.py"), "passed", "校验通过"),
                )
                version = conn.execute("SELECT id FROM strategy_versions WHERE strategy_id = ? ORDER BY version DESC LIMIT 1", (strategy["id"],)).fetchone()
                if version:
                    conn.execute("UPDATE strategies SET current_version_id = ? WHERE id = ?", (version["id"], strategy["id"]))

    def _write_strategy_file(self, file_path: Path, code: str) -> None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        if file_path.exists():
            try:
                if file_path.read_text(encoding="utf-8") == code:
                    return
            except OSError:
                pass
        file_path.write_text(code, encoding="utf-8")

    def _extract_strategy_class_name(self, code: str) -> str:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return ""
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            if any(isinstance(base, ast.Name) and base.id == "StrategyTemplate" for base in node.bases):
                return node.name.strip()
        return ""

    def derive_metadata_from_code(self, code: str, fallback_name: str = "") -> dict[str, object]:
        summary = ""
        fallback_name = fallback_name.strip()
        display_name = ""
        tags: list[str] = []
        class_name = ""
        module_doc = ""
        class_doc = ""
        try:
            tree = ast.parse(code)
        except SyntaxError:
            tree = None
        if tree is not None:
            module_doc = ast.get_docstring(tree) or ""
            if not module_doc:
                for stmt in tree.body:
                    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                        module_doc = stmt.value.value
                        break
            if module_doc:
                lines = [line.strip() for line in module_doc.splitlines() if line.strip()]
                if lines:
                    summary = lines[0]
                tag_match = re.search(r"Tags:\s*\[(.*?)\]", module_doc, re.S)
                if tag_match:
                    raw_tags = re.findall(r'"([^"]+)"|\'([^\']+)\'', tag_match.group(1))
                    tags = [left or right for left, right in raw_tags if (left or right).strip()]
            for node in tree.body:
                if not isinstance(node, ast.ClassDef):
                    continue
                is_strategy = any(isinstance(base, ast.Name) and base.id == "StrategyTemplate" for base in node.bases)
                if not is_strategy:
                    continue
                class_name = node.name.strip()
                class_doc = ast.get_docstring(node) or ""
                if class_doc and not summary:
                    first_line = next((line.strip() for line in class_doc.splitlines() if line.strip()), "")
                    if first_line:
                        summary = first_line
                if not display_name:
                    for stmt in node.body:
                        if not isinstance(stmt, ast.FunctionDef) or stmt.name != "__init__":
                            continue
                        for inner in ast.walk(stmt):
                            if not isinstance(inner, ast.Call):
                                continue
                            if not isinstance(inner.func, ast.Attribute) or inner.func.attr != "__init__":
                                continue
                            if not inner.args:
                                continue
                            arg = inner.args[0]
                            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value.strip():
                                display_name = arg.value.strip()
                                break
                        if display_name:
                            break
                break
        fallback_display_name = display_name or fallback_name or class_name
        description = summary or display_name or fallback_name or class_name
        clean_tags = self._normalize_strategy_tags(tags)
        if not clean_tags:
            clean_tags = self._infer_strategy_tags("\n".join(part for part in [module_doc, class_doc, fallback_display_name] if part))
        if self._is_generic_or_low_quality_description(description, fallback_display_name, class_name):
            description = display_name or fallback_name or class_name
        return {
            "name": display_name or fallback_name or class_name,
            "description": description,
            "tags": clean_tags,
        }

    def _contains_cjk(self, text: str) -> bool:
        return any("CJK" in unicodedata.name(char, "") for char in text)

    def _looks_like_identifier(self, text: str) -> bool:
        compact = re.sub(r"[^A-Za-z0-9_]", "", text or "")
        if not compact:
            return False
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", compact):
            return False
        return bool(re.search(r"[a-z][A-Z]|[A-Z]{2,}|\d", compact))

    def _normalize_strategy_tags(self, tags) -> list[str]:
        if not isinstance(tags, list):
            return []
        clean_tags: list[str] = []
        seen: set[str] = set()
        generic_tags = {"AI生成", "量化策略", "agent", "AI", "策略草稿"}
        for tag in tags:
            text = str(tag).strip()[:30]
            if not text or text in seen or text in generic_tags:
                continue
            seen.add(text)
            clean_tags.append(text)
        return clean_tags[:8]

    def _infer_strategy_tags(self, text: str) -> list[str]:
        source = text.strip()
        if not source:
            return []
        rules = [
            ("主板", ["主板"]),
            ("市值", ["市值", "小市值"]),
            ("估值", ["估值"]),
            ("波动", ["波动", "低波"]),
            ("动量", ["动量"]),
            ("反转", ["反转", "均值回复"]),
            ("低PE", ["低PE", "PE"]),
            ("PE", ["低PE", "PE"]),
            ("PB", ["PB"]),
            ("ROE", ["ROE", "质量"]),
            ("盈利", ["盈利", "基本面"]),
            ("年报", ["年报", "基本面"]),
            ("月调仓", ["月调仓"]),
        ]
        tags: list[str] = []
        for _, candidates in rules:
            if any(keyword in source for keyword in candidates):
                tags.extend(candidates)
        if "波动" in source and "低波" not in tags:
            tags.append("低波")
        if "反转" in source and "均值回复" not in tags:
            tags.append("均值回复")
        if "主板" in source and "主板" not in tags:
            tags.append("主板")
        return self._normalize_strategy_tags(tags)

    def _is_generic_or_low_quality_description(self, description: str | None, name: str | None, class_name: str | None = None) -> bool:
        text = (description or "").strip()
        strategy_name = (name or "").strip()
        class_name = (class_name or "").strip()
        generic_descriptions = {
            "通过标准化回测脚本创建",
            "通过标准化回测脚本更新",
            "由Agent自动创建",
            "AI 策略草稿",
        }
        if not text:
            return True
        if text in generic_descriptions:
            return True
        if text.startswith("AI生成的") and text.endswith("策略"):
            return True
        if self._looks_like_identifier(text) and not self._contains_cjk(text):
            return True
        if strategy_name and text == strategy_name and self._looks_like_identifier(strategy_name) and not self._contains_cjk(strategy_name):
            return True
        if class_name and text == class_name:
            return True
        return False

    def _has_generic_metadata(self, name: str | None, description: str | None, tags: list[str] | None, class_name: str | None = None) -> bool:
        current_tags = {str(tag).strip() for tag in (tags or []) if str(tag).strip()}
        if self._is_generic_or_low_quality_description(description, name, class_name):
            return True
        return not self._normalize_strategy_tags(list(current_tags))

    def list_strategies(self) -> list[StrategyOut]:
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT s.*, v.version, v.validation_status, v.validation_message, v.code
                FROM strategies s
                LEFT JOIN strategy_versions v ON v.id = s.current_version_id
                ORDER BY s.updated_at DESC, s.id DESC
                """
            ).fetchall()
            for row in rows:
                if not row["code"] or not self._has_generic_metadata(row["name"], row["description"], json.loads(row["tags_json"] or "[]"), self._extract_strategy_class_name(row["code"])):
                    continue
                metadata = self.derive_metadata_from_code(row["code"], fallback_name=row["name"])
                name = str(metadata.get("name") or row["name"])
                description = str(metadata.get("description") or row["description"])
                tags = metadata.get("tags") if isinstance(metadata.get("tags"), list) else json.loads(row["tags_json"] or "[]")
                conn.execute(
                    "UPDATE strategies SET name = ?, description = ?, tags_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (name, description, json.dumps(tags, ensure_ascii=False), row["id"]),
                )
            rows = conn.execute(
                """
                SELECT s.*, v.version, v.validation_status, v.validation_message, v.code
                FROM strategies s
                LEFT JOIN strategy_versions v ON v.id = s.current_version_id
                ORDER BY s.updated_at DESC, s.id DESC
                """
            ).fetchall()
        return [self._row_to_out(row) for row in rows]

    def get_strategy(self, strategy_id: int) -> StrategyOut | None:
        with get_conn() as conn:
            row = conn.execute(
                """
                SELECT s.*, v.version, v.validation_status, v.validation_message, v.code
                FROM strategies s
                LEFT JOIN strategy_versions v ON v.id = s.current_version_id
                WHERE s.id = ?
                """,
                (strategy_id,),
            ).fetchone()
        return self._row_to_out(row) if row else None

    def list_versions(self, strategy_id: int) -> list[StrategyVersionOut]:
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT id, strategy_id, version, code, code_hash, file_path,
                       validation_status, validation_message, created_at
                FROM strategy_versions
                WHERE strategy_id = ?
                ORDER BY version DESC
                """,
                (strategy_id,),
            ).fetchall()
        return [
            StrategyVersionOut(
                id=row["id"],
                strategy_id=row["strategy_id"],
                version=row["version"],
                code_hash=row["code_hash"],
                file_path=row["file_path"],
                validation_status=row["validation_status"],
                validation_message=row["validation_message"],
                code_length=len(row["code"]) if row["code"] else 0,
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def create_strategy(self, payload: StrategyCreate) -> StrategyOut:
        key = self._normalize_key(payload.key)
        validation = self.validator.validate(payload.code)
        if not validation.ok:
            raise ValueError(validation.message)

        code_hash = self._hash_code(payload.code)
        source = SOURCE_MAP.get(payload.source, payload.source)

        with get_conn() as conn:
            exists = conn.execute("SELECT id FROM strategies WHERE key = ?", (key,)).fetchone()
            if exists:
                raise ValueError("策略标识已存在")

            cursor = conn.execute(
                """
                INSERT INTO strategies (key, name, description, source, tags_json, status)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    key,
                    payload.name,
                    payload.description,
                    source,
                    json.dumps(payload.tags, ensure_ascii=False),
                    payload.status,
                ),
            )
            strategy_id = int(cursor.lastrowid)
            version_id = self._insert_version(
                conn=conn,
                strategy_id=strategy_id,
                key=key,
                version=1,
                code=payload.code,
                code_hash=code_hash,
                validation_status=validation.status,
                validation_message=validation.message,
                dependencies=validation.dependencies,
            )
            conn.execute(
                "UPDATE strategies SET current_version_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (version_id, strategy_id),
            )

        strategy = self.get_strategy(strategy_id)
        if strategy is None:
            raise ValueError("策略保存失败")
        return strategy

    def update_strategy(self, strategy_id: int, payload: StrategyUpdate) -> StrategyOut | None:
        current = self.get_strategy(strategy_id)
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
                last_version = current.version or 0
                version_id = self._insert_version(
                    conn=conn,
                    strategy_id=strategy_id,
                    key=current.key,
                    version=last_version + 1,
                    code=payload.code,
                    code_hash=self._hash_code(payload.code),
                    validation_status=validation.status,
                    validation_message=validation.message,
                    dependencies=validation.dependencies,
                )
                updates.append("current_version_id = ?")
                values.append(version_id)

            if updates:
                values.append(strategy_id)
                conn.execute(
                    f"UPDATE strategies SET {', '.join(updates)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    values,
                )

        return self.get_strategy(strategy_id)

    def set_status(self, strategy_id: int, status: str) -> StrategyOut | None:
        with get_conn() as conn:
            conn.execute(
                "UPDATE strategies SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status, strategy_id),
            )
        return self.get_strategy(strategy_id)

    def delete_strategy(self, strategy_id: int) -> bool:
        with get_conn() as conn:
            strategy = conn.execute(
                """
                SELECT s.id, s.key, s.current_version_id, v.file_path AS current_file_path
                FROM strategies s
                LEFT JOIN strategy_versions v ON v.id = s.current_version_id
                WHERE s.id = ?
                """,
                (strategy_id,),
            ).fetchone()
            if strategy is None:
                return False
            running_tasks = conn.execute(
                "SELECT COUNT(*) as cnt FROM backtest_tasks WHERE strategy_id = ? AND status IN ('queued', 'running')",
                (strategy_id,),
            ).fetchone()
            if running_tasks and running_tasks["cnt"] > 0:
                raise ValueError("该策略存在运行中的回测任务，请先终止任务后再删除")
            current_file_path = strategy["current_file_path"] or str(GENERATED_STRATEGY_DIR / f"{strategy['key']}.py")
            file_path = Path(current_file_path)
            if file_path.exists() and file_path.is_file():
                try:
                    file_path.unlink()
                except OSError:
                    pass
            conn.execute("DELETE FROM strategy_versions WHERE strategy_id = ?", (strategy_id,))
            conn.execute("DELETE FROM strategies WHERE id = ?", (strategy_id,))
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
        draft = self._generate_ai_strategy(prompt, validation_feedback)
        code = draft["code"]
        validation = self.validator.validate(code)
        if not validation.ok:
            draft = self._generate_ai_strategy(prompt, validation.message)
            code = draft["code"]
            validation = self.validator.validate(code)
            if not validation.ok:
                raise ValueError(f"AI 生成的策略未通过校验: {validation.message}")

        raw_key = str(draft.get("key") or self._build_ai_key_seed(prompt))
        key = f"{self._normalize_key(raw_key)[:48]}_{uuid4().hex[:8]}"
        return {
            "name": str(draft.get("name") or "AI 策略草稿")[:120],
            "key": key,
            "source": "AI生成",
            "description": str(draft.get("description") or f"根据自然语言描述生成：{prompt}"),
            "tags": self._normalize_tags(draft.get("tags")),
            "code": code,
        }

    def _insert_version(
        self,
        conn,
        strategy_id: int,
        key: str,
        version: int,
        code: str,
        code_hash: str,
        validation_status: str,
        validation_message: str,
        dependencies: list[str],
    ) -> int:
        GENERATED_STRATEGY_DIR.mkdir(parents=True, exist_ok=True)
        file_path = GENERATED_STRATEGY_DIR / f"{key}.py"
        self._write_strategy_file(file_path, code)
        cursor = conn.execute(
            """
            INSERT INTO strategy_versions (
                strategy_id, version, code, code_hash, file_path,
                validation_status, validation_message, dependencies_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                strategy_id,
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

    def _row_to_out(self, row) -> StrategyOut:
        return StrategyOut(
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
            raise ValueError("策略标识不能为空")
        return normalized

    def _hash_code(self, code: str) -> str:
        return hashlib.sha256(code.encode("utf-8")).hexdigest()

    def _generate_ai_strategy(self, prompt: str, validation_error: str | None = None) -> dict:
        api_key = settings.AI_API_KEY or settings.OPENAI_API_KEY
        if not api_key:
            raise ValueError("缺少 AI_API_KEY，请在项目根目录 .env 中配置。")

        user_prompt = (
            "请根据下面的自然语言需求生成一个完整策略。\n"
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
                {"role": "system", "content": STRATEGY_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 4096,
        }
        url = settings.AI_BASE_URL.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

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
        message = data["choices"][0].get("message", {})
        content = message.get("content") or data["choices"][0].get("text") or ""
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
                text = text[start : end + 1]
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            fallback = self._parse_loose_ai_json(text)
            if fallback is not None:
                return fallback
            preview = text[:300].replace("\n", "\\n")
            raise ValueError(f"AI 返回内容不是合法 JSON: {preview}") from exc

    def _parse_loose_ai_json(self, text: str) -> dict | None:
        code_match = re.search(r'"code"\s*:\s*"', text)
        if code_match is None:
            return None

        prefix = text[: code_match.start()] + '"code": ""}'
        try:
            metadata = json.loads(prefix)
        except json.JSONDecodeError:
            metadata = {}
            for field in ("name", "key", "description"):
                match = re.search(rf'"{field}"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.S)
                if match:
                    metadata[field] = match.group(1)
            tags_match = re.search(r'"tags"\s*:\s*(\[[^\]]*\])', text, re.S)
            if tags_match:
                try:
                    metadata["tags"] = json.loads(tags_match.group(1))
                except json.JSONDecodeError:
                    pass

        code = text[code_match.end() :]
        code = re.sub(r'"\s*}\s*$', "", code, flags=re.S)
        code = re.sub(r'"\s*,\s*}\s*$', "", code, flags=re.S)
        code = code.replace("\\n", "\n").replace('\\"', '"')
        if not code.strip():
            return None
        metadata["code"] = code
        return metadata

    def _build_ai_key_seed(self, prompt: str) -> str:
        key_seed = re.sub(r"[^a-zA-Z0-9_]+", "_", prompt.strip().lower())[:32].strip("_")
        return f"ai_strategy_{key_seed or 'draft'}"

    def _normalize_tags(self, tags) -> list[str]:
        normalized = self._normalize_strategy_tags(tags)
        return normalized or ["策略草稿"]

    def _build_ai_template(self, prompt: str) -> str:
        return f'''from __future__ import annotations

from backtest.strategy import StrategyTemplate


class AIGeneratedStrategy(StrategyTemplate):
    """AI 生成策略草稿。

    用户描述:
    {prompt}
    """

    def __init__(self):
        super().__init__("AI 策略草稿")
        self.lookback_days = 20
        self.max_positions = 10

    def init(self, context):
        self.day_count = 0

    def next(self, context):
        self.day_count += 1
        market_data = context["market_data"]
        if market_data.empty:
            return

        candidates = market_data.copy()
        if "amount" in candidates.columns:
            candidates = candidates.sort_values("amount", ascending=False)

        selected = candidates.head(self.max_positions)
        if selected.empty:
            return

        weight = 0.9 / len(selected)
        selected_codes = set(selected["ts_code"].tolist())

        for ts_code, position in context["broker"].account.positions.items():
            if position.volume > 0 and ts_code not in selected_codes:
                context["order_target_percent"](ts_code, 0)

        for ts_code in selected_codes:
            context["order_target_percent"](ts_code, weight)
'''
