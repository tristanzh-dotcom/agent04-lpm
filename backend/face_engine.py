from __future__ import annotations

import os
import pickle
import hashlib
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
from PIL import Image, ImageOps


VALID_FACE_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".heic", ".heif", ".tif", ".tiff")


class FaceVectorError(RuntimeError):
    """本地人脸向量注册、索引或匹配失败。"""


@dataclass
class FaceEmbedding:
    embedding: np.ndarray
    bbox: list[float] | None = None
    det_score: float = 1.0


FaceExtractor = Callable[[Any], list[FaceEmbedding]]


class FaceVectorEngine:
    """LIMB 本地人脸向量库。

    该模块只在本机提取和保存人脸 embedding。它不调用 Ark、DeepSeek 或任何云端 API。
    单元测试通过注入 `face_extractor` 避免加载真实 InsightFace；生产环境按需懒加载。
    """

    def __init__(
        self,
        *,
        data_dir: str | os.PathLike[str] | None = None,
        model_dir: str | os.PathLike[str] | None = None,
        profiles_path: str | os.PathLike[str] | None = None,
        photo_index_path: str | os.PathLike[str] | None = None,
        face_threshold: float | None = None,
        face_extractor: FaceExtractor | None = None,
    ) -> None:
        self.data_dir = Path(data_dir or os.environ.get("LIMB_DATA_DIR") or "data").expanduser().resolve()
        self.model_dir = Path(model_dir or os.environ.get("LIMB_FACE_MODEL_DIR") or "backend/models").expanduser().resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.profiles_path = Path(profiles_path or self.data_dir / "face_profiles.pkl").expanduser().resolve()
        self.photo_index_path = Path(photo_index_path or self.data_dir / "photo_face_index.pkl").expanduser().resolve()
        self.avatar_dir = Path(os.environ.get("LIMB_FACE_AVATAR_DIR") or Path(".cache") / "face-avatars").expanduser().resolve()
        self.avatar_dir.mkdir(parents=True, exist_ok=True)
        self.face_threshold = float(face_threshold if face_threshold is not None else os.environ.get("LIMB_FACE_THRESHOLD", 0.45))
        self.face_extractor = face_extractor
        self._face_app: Any | None = None

    def register_profile(self, label: str, image_paths: Iterable[str | os.PathLike[str]]) -> dict[str, Any]:
        clean_label = str(label).strip()
        if not clean_label:
            raise FaceVectorError("昵称不能为空。")

        paths = [Path(path).expanduser().resolve() for path in image_paths]
        if len(paths) < 3:
            raise FaceVectorError("至少需要上传 3 张清晰人脸样张。")

        vectors: list[np.ndarray] = []
        for path in paths:
            faces = self.extract_faces(path)
            if faces:
                vectors.append(self._normalize(self._select_best_face(faces).embedding))

        if not vectors:
            raise FaceVectorError("上传样张中未检测到可用人脸。")

        mean_vector = self._normalize(np.mean(np.stack(vectors, axis=0), axis=0))
        profiles = self.load_profiles()
        now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        previous = profiles.get(clean_label, {})
        avatar_path = self._persist_profile_avatar(clean_label, paths[0])
        previous_avatar_path = previous.get("avatar_path")
        if previous_avatar_path and str(previous_avatar_path) != str(avatar_path):
            self._remove_profile_avatar(previous_avatar_path)
        profiles[clean_label] = {
            "label": clean_label,
            "embedding": mean_vector,
            "sample_count": len(vectors),
            "created_at": previous.get("created_at", now),
            "updated_at": now,
            "avatar_path": str(avatar_path),
        }
        self._save_pickle(self.profiles_path, profiles)
        return self._profile_public(profiles[clean_label])

    def scan_photo_directory(self, target_dir: str | os.PathLike[str]) -> dict[str, int]:
        root = Path(target_dir).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise FaceVectorError(f"相册目录不存在: {root}")

        index = self.load_photo_index()
        stats = {"indexed": 0, "skipped": 0, "failed": 0}

        for path in self.iter_image_files(root):
            resolved = str(path.resolve())
            modify_time = path.stat().st_mtime
            if resolved in index and float(index[resolved].get("modify_time", -1)) == float(modify_time):
                stats["skipped"] += 1
                continue
            try:
                faces = self.extract_faces(path)
                index[resolved] = {
                    "modify_time": modify_time,
                    "faces": [
                        {
                            "embedding": self._normalize(face.embedding),
                            "bbox": face.bbox or [],
                            "det_score": float(face.det_score),
                        }
                        for face in faces
                    ],
                }
                stats["indexed"] += 1
            except Exception as exc:
                print(f"[LIMB-Face] 人脸索引失败 {path}: {exc}", flush=True)
                stats["failed"] += 1

        self._save_pickle(self.photo_index_path, index)
        return stats

    def match_label(
        self,
        label: str,
        *,
        candidate_paths: Iterable[str | os.PathLike[str]] | None = None,
        threshold: float | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        profiles = self.load_profiles()
        clean_label = str(label).strip()
        if clean_label not in profiles:
            return []

        target_vector = self._normalize(profiles[clean_label]["embedding"])
        photo_index = self.load_photo_index()
        candidate_set = None
        if candidate_paths is not None:
            candidate_set = {str(Path(path).expanduser().resolve()) for path in candidate_paths}

        min_score = float(threshold if threshold is not None else self.face_threshold)
        matches: list[dict[str, Any]] = []
        for path, record in photo_index.items():
            if candidate_set is not None and path not in candidate_set:
                continue
            best_score = self._best_face_score(target_vector, record.get("faces", []))
            if best_score >= min_score:
                matches.append({"path": path, "label": clean_label, "face_score": best_score})

        matches.sort(key=lambda item: item["face_score"], reverse=True)
        return matches[: max(1, int(limit))]

    def list_profiles(self) -> list[dict[str, Any]]:
        return [self._profile_public(profile) for profile in self.load_profiles().values()]

    def delete_profile(self, label: str) -> dict[str, Any]:
        clean_label = str(label).strip()
        if not clean_label:
            raise FaceVectorError("昵称不能为空。")

        profiles = self.load_profiles()
        if clean_label not in profiles:
            raise KeyError(clean_label)

        deleted = self._profile_public(profiles.pop(clean_label))
        self._remove_profile_avatar(deleted.get("avatar_path"))
        self._save_pickle(self.profiles_path, profiles)
        return {"status": "deleted", **deleted}

    def known_labels_in_query(self, query: str) -> list[str]:
        text = str(query)
        return [label for label in self.load_profiles() if label and label in text]

    def extract_faces(self, image_path: str | os.PathLike[str]) -> list[FaceEmbedding]:
        if self.face_extractor is not None:
            return [self._coerce_face(face) for face in self.face_extractor(image_path)]
        return self._extract_faces_with_insightface(image_path)

    def load_profiles(self) -> dict[str, dict[str, Any]]:
        return self._load_pickle(self.profiles_path)

    def load_photo_index(self) -> dict[str, dict[str, Any]]:
        return self._load_pickle(self.photo_index_path)

    def iter_image_files(self, root: Path) -> Iterable[Path]:
        for current_root, _, files in os.walk(root):
            for file_name in files:
                if file_name.lower().endswith(VALID_FACE_IMAGE_EXTENSIONS):
                    yield Path(current_root) / file_name

    def _extract_faces_with_insightface(self, image_path: str | os.PathLike[str]) -> list[FaceEmbedding]:
        try:
            from insightface.app import FaceAnalysis
        except ImportError as exc:
            raise FaceVectorError(
                "缺少 InsightFace 依赖，请执行: python3 -m pip install insightface onnxruntime opencv-python-headless"
            ) from exc

        if self._face_app is None:
            self._face_app = FaceAnalysis(root=str(self.model_dir), allowed_modules=["detection", "recognition"])
            self._face_app.prepare(ctx_id=-1, det_size=(640, 640))

        with Image.open(image_path) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            bgr = np.array(image)[:, :, ::-1]

        faces = []
        for face in self._face_app.get(bgr):
            faces.append(
                FaceEmbedding(
                    embedding=np.asarray(face.embedding, dtype=np.float32),
                    bbox=[float(value) for value in getattr(face, "bbox", [])],
                    det_score=float(getattr(face, "det_score", 1.0)),
                )
            )
        return faces

    def _select_best_face(self, faces: list[FaceEmbedding]) -> FaceEmbedding:
        def score(face: FaceEmbedding) -> float:
            area = 1.0
            if face.bbox and len(face.bbox) >= 4:
                area = max(1.0, (face.bbox[2] - face.bbox[0]) * (face.bbox[3] - face.bbox[1]))
            return float(face.det_score) * area

        return max(faces, key=score)

    def _best_face_score(self, target_vector: np.ndarray, faces: list[dict[str, Any]]) -> float:
        best = 0.0
        for face in faces:
            vector = self._normalize(face.get("embedding"))
            best = max(best, float(np.dot(target_vector, vector)))
        return best

    def _coerce_face(self, face: Any) -> FaceEmbedding:
        if isinstance(face, FaceEmbedding):
            return FaceEmbedding(
                embedding=self._normalize(face.embedding),
                bbox=face.bbox,
                det_score=face.det_score,
            )
        return FaceEmbedding(
            embedding=self._normalize(getattr(face, "embedding", face["embedding"])),
            bbox=getattr(face, "bbox", face.get("bbox", [])),
            det_score=float(getattr(face, "det_score", face.get("det_score", 1.0))),
        )

    def _profile_public(self, profile: dict[str, Any]) -> dict[str, Any]:
        return {
            "label": profile["label"],
            "sample_count": int(profile.get("sample_count", 0)),
            "updated_at": profile.get("updated_at", ""),
            "avatar_path": profile.get("avatar_path", ""),
        }

    def _persist_profile_avatar(self, label: str, sample_path: Path) -> Path:
        data = sample_path.read_bytes()
        label_hash = hashlib.sha256(label.encode("utf-8")).hexdigest()[:12]
        content_hash = hashlib.md5(data).hexdigest()[:12]
        avatar_path = self.avatar_dir / f"{label_hash}-{content_hash}.jpg"
        if avatar_path.exists():
            return avatar_path
        try:
            with Image.open(sample_path) as image:
                image = ImageOps.exif_transpose(image).convert("RGB")
                image.thumbnail((512, 512), Image.Resampling.LANCZOS)
                image.save(avatar_path, format="JPEG", quality=86, optimize=True)
        except Exception:
            shutil.copyfile(sample_path, avatar_path)
        return avatar_path

    def _remove_profile_avatar(self, avatar_path: Any) -> None:
        if not avatar_path:
            return
        try:
            candidate = Path(str(avatar_path)).expanduser().resolve()
            candidate.relative_to(self.avatar_dir)
        except Exception:
            return
        candidate.unlink(missing_ok=True)

    def _normalize(self, vector: Any) -> np.ndarray:
        array = np.asarray(vector, dtype=np.float32).flatten()
        norm = float(np.linalg.norm(array))
        if norm <= 0:
            raise FaceVectorError("人脸向量为空或无法归一化。")
        return array / norm

    def _load_pickle(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        with path.open("rb") as file:
            payload = pickle.load(file)
        return payload if isinstance(payload, dict) else {}

    def _save_pickle(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as file:
            pickle.dump(payload, file)
