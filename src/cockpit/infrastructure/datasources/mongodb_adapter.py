"""MongoDB datasource adapter."""

from __future__ import annotations

import json

from cockpit.domain.models.datasource import DataSourceOperationResult, DataSourceProfile
from cockpit.infrastructure.datasources.base import DataSourceInspection

try:
    from pymongo import MongoClient
except Exception:  # pragma: no cover - optional dependency guard
    MongoClient = None


class MongoDatasourceAdapter:
    def inspect(self, profile: DataSourceProfile) -> DataSourceInspection:
        if MongoClient is None:
            return DataSourceInspection(
                success=False,
                profile_id=profile.id,
                backend=profile.backend,
                summary="PyMongo is not installed.",
                details={},
            )
        try:
            client = MongoClient(profile.connection_url)
            database_names = client.list_database_names()[:12]
            details: dict[str, object] = {"databases": [str(item) for item in database_names]}
            if profile.database_name:
                details["collections"] = [
                    str(item) for item in client[profile.database_name].list_collection_names()[:20]
                ]
            return DataSourceInspection(
                success=True,
                profile_id=profile.id,
                backend=profile.backend,
                summary=f"Connected to MongoDB datasource {profile.name}.",
                details=details,
            )
        except Exception as exc:
            return DataSourceInspection(
                success=False,
                profile_id=profile.id,
                backend=profile.backend,
                summary=str(exc),
                details={},
            )

    def run(
        self,
        profile: DataSourceProfile,
        statement: str,
        *,
        operation: str = "query",
        row_limit: int = 50,
    ) -> DataSourceOperationResult:
        if MongoClient is None:
            return DataSourceOperationResult(
                success=False,
                profile_id=profile.id,
                backend=profile.backend,
                operation=operation,
                message="PyMongo is not installed.",
            )
        try:
            payload = json.loads(statement)
            if not isinstance(payload, dict):
                raise ValueError("MongoDB payload must be a JSON object.")
            client = MongoClient(profile.connection_url)
            database_name = str(payload.get("database") or profile.database_name or "")
            collection_name = str(payload.get("collection") or "")
            op_name = str(payload.get("operation") or "find")
            if not database_name or not collection_name:
                raise ValueError("MongoDB payload must include database and collection.")
            collection = client[database_name][collection_name]
            if op_name == "find":
                cursor = collection.find(payload.get("filter", {}), payload.get("projection"))
                rows = [json.dumps(document, default=str, sort_keys=True) for document in cursor.limit(max(1, int(row_limit)))]
                return DataSourceOperationResult(
                    success=True,
                    profile_id=profile.id,
                    backend=profile.backend,
                    operation=operation,
                    columns=["document"],
                    rows=[[row] for row in rows],
                    message=f"Returned {len(rows)} document(s).",
                )
            if op_name == "insert_one":
                result = collection.insert_one(payload.get("document", {}))
                return DataSourceOperationResult(
                    success=True,
                    profile_id=profile.id,
                    backend=profile.backend,
                    operation=operation,
                    affected_rows=1,
                    message=f"Inserted document {result.inserted_id}.",
                )
            if op_name == "update_many":
                result = collection.update_many(payload.get("filter", {}), payload.get("update", {}))
                return DataSourceOperationResult(
                    success=True,
                    profile_id=profile.id,
                    backend=profile.backend,
                    operation=operation,
                    affected_rows=int(result.modified_count),
                    message=f"Updated {result.modified_count} document(s).",
                )
            if op_name == "delete_many":
                result = collection.delete_many(payload.get("filter", {}))
                return DataSourceOperationResult(
                    success=True,
                    profile_id=profile.id,
                    backend=profile.backend,
                    operation=operation,
                    affected_rows=int(result.deleted_count),
                    message=f"Deleted {result.deleted_count} document(s).",
                )
            raise ValueError(f"Unsupported MongoDB operation '{op_name}'.")
        except Exception as exc:
            return DataSourceOperationResult(
                success=False,
                profile_id=profile.id,
                backend=profile.backend,
                operation=operation,
                message=str(exc),
            )
