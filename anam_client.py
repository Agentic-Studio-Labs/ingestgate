"""anam.ai REST API client for knowledge base management.

Handles folder creation, 3-step presigned file upload, and
document status polling. Also supports attaching multiple
folders to a persona's knowledge tool.
"""

import os
import re
import time
from pathlib import Path
from typing import Callable, Optional

import requests

from config import Config
from models import (
    DocumentStatus,
    FolderNode,
    FolderRecommendation,
    UploadReport,
    UploadResult,
    UploadSession,
)

# Network timeouts (seconds)
API_TIMEOUT = 30
UPLOAD_TIMEOUT = 300  # Large file uploads need more time

# Filename constraints
MAX_FILENAME_LENGTH = 200
INVALID_FILENAME_CHARS = re.compile(r'[<>:"|?*]')


class AnamClient:
    """REST API client for anam.ai knowledge base."""

    def __init__(self, config: Config):
        if not config.anam_api_key:
            raise ValueError("anam.ai API key required. Set ANAM_API_KEY or use --api-key.")
        self.base_url = config.anam_base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {config.anam_api_key}",
            "Content-Type": "application/json",
        })

    # ------------------------------------------------------------------
    # Folder management
    # ------------------------------------------------------------------

    def create_folder(self, name: str, description: str) -> str:
        """Create a knowledge folder and return its ID."""
        resp = self.session.post(
            f"{self.base_url}/v1/knowledge/groups",
            json={"name": name, "description": description},
            timeout=API_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()["id"]

    def list_folders(self) -> list[dict]:
        """List all knowledge folders."""
        resp = self.session.get(
            f"{self.base_url}/v1/knowledge/groups",
            timeout=API_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("groups", [])

    def search_folder(self, folder_id: str, query: str, limit: int = 5) -> list[dict]:
        """Search a knowledge folder using vector similarity."""
        resp = self.session.post(
            f"{self.base_url}/v1/knowledge/groups/{folder_id}/search",
            json={"query": query, "limit": limit},
            timeout=API_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        for key in ("results", "data", "chunks", "documents"):
            if key in data:
                return data[key]
        return [data]

    def create_folder_tree(
        self, recommendation: FolderRecommendation
    ) -> dict[str, str]:
        """Create all folders from a recommendation, return name->ID mapping."""
        folder_map: dict[str, str] = {}

        def create_recursive(node: FolderNode, path_prefix: str = ""):
            path = f"{path_prefix}/{node.name}" if path_prefix else node.name
            if node.name == "Knowledge Base":
                # Skip root node, just process children
                for child in node.children:
                    create_recursive(child, "")
                return

            folder_id = self.create_folder(node.name, node.description)
            folder_map[path] = folder_id

            for child in node.children:
                create_recursive(child, path)

        create_recursive(recommendation.root)
        return folder_map

    # ------------------------------------------------------------------
    # File upload (3-step presigned flow)
    # ------------------------------------------------------------------

    def request_upload(self, folder_id: str, filename: str, file_size: int) -> UploadSession:
        """Step 1: Request a presigned upload URL."""
        resp = self.session.post(
            f"{self.base_url}/v1/knowledge/groups/{folder_id}/presigned-upload",
            json={
                "fileName": filename,
                "fileSize": file_size,
            },
            timeout=API_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        # Extract session ID with explicit validation
        session_id = data.get("uploadId") or data.get("id")
        if not session_id:
            raise ValueError(
                f"Upload response missing uploadId/id. Response keys: {list(data.keys())}"
            )

        presigned_url = data.get("presignedUrl")
        if not presigned_url:
            raise ValueError(
                f"Upload response missing presignedUrl. Response keys: {list(data.keys())}"
            )

        return UploadSession(
            session_id=session_id,
            presigned_url=presigned_url,
            filename=filename,
        )

    def upload_file(self, presigned_url: str, file_path: str, content_type: str) -> bool:
        """Step 2: PUT the file to the presigned URL."""
        with open(file_path, "rb") as f:
            # Presigned URLs don't need auth headers — only content-type
            resp = requests.put(
                presigned_url,
                data=f,
                headers={"Content-Type": content_type},
                timeout=UPLOAD_TIMEOUT,
            )
        resp.raise_for_status()
        return True

    def confirm_upload(self, folder_id: str, upload_id: str) -> dict:
        """Step 3: Confirm the upload to start processing."""
        resp = self.session.post(
            f"{self.base_url}/v1/knowledge/groups/{folder_id}/confirm-upload",
            json={"uploadId": upload_id},
            timeout=API_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    def upload_document(
        self,
        file_path: str,
        folder_id: str,
        folder_name: str = "",
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> UploadResult:
        """Execute the full 3-step upload for one file."""
        filename = Path(file_path).name
        file_size = os.path.getsize(file_path)
        content_type = self._get_content_type(file_path)

        # Validate filename before upload
        self._validate_filename(filename)

        try:
            # Step 1
            if progress_callback:
                progress_callback(f"Requesting upload URL for {filename}...")
            session = self.request_upload(folder_id, filename, file_size)

            # Step 2
            if progress_callback:
                progress_callback(f"Uploading {filename}...")
            self.upload_file(session.presigned_url, file_path, content_type)

            # Step 3
            if progress_callback:
                progress_callback(f"Confirming {filename}...")
            result = self.confirm_upload(folder_id, session.session_id)

            doc_id = result.get("documentId") or result.get("id") or ""

            return UploadResult(
                file_path=file_path,
                document_id=doc_id,
                folder_id=folder_id,
                folder_name=folder_name,
                status=DocumentStatus.PROCESSING,
            )
        except (requests.HTTPError, requests.ConnectionError, requests.Timeout, ValueError) as e:
            # Sanitize error message to avoid leaking presigned URLs or tokens
            error_msg = str(e)
            if "presigned" in error_msg.lower() or "https://" in error_msg:
                error_msg = f"{type(e).__name__}: Upload failed for {filename}"
            return UploadResult(
                file_path=file_path,
                document_id="",
                folder_id=folder_id,
                folder_name=folder_name,
                status=DocumentStatus.FAILED,
                error=error_msg,
            )

    # ------------------------------------------------------------------
    # Persona / Knowledge Tool management
    # ------------------------------------------------------------------

    def create_knowledge_tool(
        self,
        name: str,
        description: str,
        folder_ids: list[str],
    ) -> str:
        """Create a knowledge tool that searches multiple folders.

        The description is critical — it tells the LLM when to use this tool.
        Be specific about what questions should trigger a search.
        """
        resp = self.session.post(
            f"{self.base_url}/v1/tools",
            json={
                "name": name,
                "type": "server",
                "subtype": "knowledge",
                "description": description,
                "documentFolderIds": folder_ids,
            },
            timeout=API_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()["id"]

    # ------------------------------------------------------------------
    # Batch upload orchestration
    # ------------------------------------------------------------------

    def upload_batch(
        self,
        files: list[str],
        folder_map: dict[str, str],
        file_assignments: dict[str, str],
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> UploadReport:
        """Upload multiple files to their assigned folders."""
        report = UploadReport(folders_created=list(folder_map.keys()))

        for file_path in files:
            filename = Path(file_path).name
            # Look up assigned folder
            folder_path = file_assignments.get(filename)

            if not folder_path:
                # Warn but fall back to first folder
                if folder_map:
                    folder_path = next(iter(folder_map.keys()))
                    if progress_callback:
                        progress_callback(
                            f"WARNING: No assignment for {filename}, using {folder_path}"
                        )
                else:
                    report.results.append(
                        UploadResult(
                            file_path=file_path,
                            document_id="",
                            folder_id="",
                            folder_name="unknown",
                            status=DocumentStatus.FAILED,
                            error=f"No folder assignment for {filename} and no folders exist",
                        )
                    )
                    continue

            if folder_path not in folder_map:
                report.results.append(
                    UploadResult(
                        file_path=file_path,
                        document_id="",
                        folder_id="",
                        folder_name=folder_path,
                        status=DocumentStatus.FAILED,
                        error=f"Folder '{folder_path}' not found in created folders",
                    )
                )
                continue

            folder_id = folder_map[folder_path]
            result = self.upload_document(
                file_path=file_path,
                folder_id=folder_id,
                folder_name=folder_path,
                progress_callback=progress_callback,
            )
            report.results.append(result)

        return report

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_filename(filename: str) -> None:
        """Validate filename before sending to anam.ai API."""
        if len(filename) > MAX_FILENAME_LENGTH:
            raise ValueError(
                f"Filename too long ({len(filename)} chars, max {MAX_FILENAME_LENGTH}): {filename}"
            )
        if INVALID_FILENAME_CHARS.search(filename):
            raise ValueError(
                f"Filename contains invalid characters: {filename}"
            )

    @staticmethod
    def _get_content_type(file_path: str) -> str:
        """Map file extension to MIME type."""
        ext = Path(file_path).suffix.lower()
        types = {
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".txt": "text/plain",
            ".md": "text/markdown",
            ".csv": "text/csv",
            ".json": "application/json",
            ".log": "text/plain",
        }
        return types.get(ext, "application/octet-stream")
