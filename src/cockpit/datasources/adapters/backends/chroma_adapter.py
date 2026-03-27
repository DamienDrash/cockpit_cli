"""ChromaDB datasource adapter."""

from __future__ import annotations

import json

from cockpit.datasources.models.datasource import (
    DataSourceOperationResult,
    DataSourceProfile,
)
from cockpit.datasources.adapters.backends.base import DataSourceInspection

try:
    import chromadb
except Exception:  # pragma: no cover - optional dependency guard
    chromadb = None


class ChromaDatasourceAdapter:
    def inspect(self, profile: DataSourceProfile) -> DataSourceInspection:
        if chromadb is None:
            return DataSourceInspection(
                success=False,
                profile_id=profile.id,
                backend=profile.backend,
                summary="chromadb is not installed.",
                details={},
            )
        try:
            client = self._client(profile)
            collections = client.list_collections()
            names = [
                getattr(collection, "name", str(collection))
                for collection in collections[:20]
            ]
            return DataSourceInspection(
                success=True,
                profile_id=profile.id,
                backend=profile.backend,
                summary=f"Connected to Chroma datasource {profile.name}.",
                details={"collections": [str(item) for item in names]},
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
        del row_limit
        if chromadb is None:
            return DataSourceOperationResult(
                success=False,
                profile_id=profile.id,
                backend=profile.backend,
                operation=operation,
                message="chromadb is not installed.",
            )
        try:
            payload = json.loads(statement)
            if not isinstance(payload, dict):
                raise ValueError("Chroma payload must be a JSON object.")
            client = self._client(profile)
            operation_name = str(payload.get("operation") or "list")
            collection_name = str(
                payload.get("collection") or profile.database_name or ""
            )
            if operation_name == "list":
                collections = client.list_collections()
                rows = [[str(getattr(item, "name", item))] for item in collections]
                return DataSourceOperationResult(
                    success=True,
                    profile_id=profile.id,
                    backend=profile.backend,
                    operation=operation,
                    columns=["collection"],
                    rows=rows,
                    message=f"Listed {len(rows)} collection(s).",
                )
            if not collection_name:
                raise ValueError("Chroma payload must include a collection.")
            collection = client.get_or_create_collection(collection_name)
            if operation_name == "query":
                result = collection.query(
                    query_texts=payload.get("query_texts"),
                    query_embeddings=payload.get("query_embeddings"),
                    n_results=int(payload.get("n_results", 5)),
                )
                return DataSourceOperationResult(
                    success=True,
                    profile_id=profile.id,
                    backend=profile.backend,
                    operation=operation,
                    output_text=json.dumps(result, default=str, sort_keys=True),
                    message="Chroma query completed.",
                )
            if operation_name == "add":
                collection.add(
                    ids=payload.get("ids") or [],
                    documents=payload.get("documents"),
                    embeddings=payload.get("embeddings"),
                    metadatas=payload.get("metadatas"),
                )
                return DataSourceOperationResult(
                    success=True,
                    profile_id=profile.id,
                    backend=profile.backend,
                    operation=operation,
                    affected_rows=len(payload.get("ids") or []),
                    message="Added Chroma documents.",
                )
            if operation_name == "delete":
                collection.delete(ids=payload.get("ids"), where=payload.get("where"))
                return DataSourceOperationResult(
                    success=True,
                    profile_id=profile.id,
                    backend=profile.backend,
                    operation=operation,
                    message="Deleted Chroma documents.",
                )
            if operation_name == "get":
                result = collection.get(
                    ids=payload.get("ids"), where=payload.get("where")
                )
                return DataSourceOperationResult(
                    success=True,
                    profile_id=profile.id,
                    backend=profile.backend,
                    operation=operation,
                    output_text=json.dumps(result, default=str, sort_keys=True),
                    message="Fetched Chroma documents.",
                )
            raise ValueError(f"Unsupported Chroma operation '{operation_name}'.")
        except Exception as exc:
            return DataSourceOperationResult(
                success=False,
                profile_id=profile.id,
                backend=profile.backend,
                operation=operation,
                message=str(exc),
            )

    def _client(self, profile: DataSourceProfile):
        if profile.connection_url and profile.connection_url.startswith("http"):
            return chromadb.HttpClient(host=profile.connection_url)
        path = str(profile.options.get("path", ".cockpit/chroma"))
        return chromadb.PersistentClient(path=path)
