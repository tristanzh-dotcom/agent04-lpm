import tempfile
import unittest
from pathlib import Path

import numpy as np

from backend.face_engine import FaceEmbedding, FaceVectorEngine, FaceVectorError


class FaceEngineTests(unittest.TestCase):
    def test_register_profile_averages_and_normalizes_sample_vectors(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            samples = [root / "sample1.jpg", root / "sample2.jpg", root / "sample3.jpg"]
            for sample in samples:
                sample.write_bytes(b"fake")

            vectors = {
                "sample1.jpg": [1.0, 0.0, 0.0],
                "sample2.jpg": [1.0, 1.0, 0.0],
                "sample3.jpg": [0.0, 1.0, 0.0],
            }

            def fake_extractor(path):
                return [FaceEmbedding(embedding=np.array(vectors[Path(path).name], dtype=np.float32))]

            engine = FaceVectorEngine(data_dir=root / "data", face_extractor=fake_extractor)

            profile = engine.register_profile("小菲", samples)
            stored = engine.load_profiles()["小菲"]["embedding"]

            self.assertEqual(profile["label"], "小菲")
            self.assertEqual(profile["sample_count"], 3)
            self.assertAlmostEqual(float(np.linalg.norm(stored)), 1.0, places=6)
            self.assertTrue((root / "data" / "face_profiles.pkl").exists())

    def test_register_profile_requires_at_least_three_sample_images(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            engine = FaceVectorEngine(data_dir=root / "data", face_extractor=lambda path: [])

            with self.assertRaises(FaceVectorError):
                engine.register_profile("小菲", [root / "one.jpg", root / "two.jpg"])

    def test_delete_profile_removes_label_from_vector_library(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            samples = [root / "sample1.jpg", root / "sample2.jpg", root / "sample3.jpg"]
            for sample in samples:
                sample.write_bytes(b"fake")

            def fake_extractor(path):
                return [FaceEmbedding(embedding=np.array([1.0, 0.0, 0.0], dtype=np.float32))]

            engine = FaceVectorEngine(data_dir=root / "data", face_extractor=fake_extractor)
            engine.register_profile("老张", samples)

            deleted = engine.delete_profile("老张")

            self.assertEqual(deleted["label"], "老张")
            self.assertEqual(deleted["status"], "deleted")
            self.assertNotIn("老张", engine.load_profiles())
            self.assertEqual(engine.known_labels_in_query("老张吃饭"), [])

    def test_register_profile_persists_new_avatar_and_delete_removes_old_avatar(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            samples = [root / "sample1.jpg", root / "sample2.jpg", root / "sample3.jpg"]
            new_samples = [root / "new1.jpg", root / "new2.jpg", root / "new3.jpg"]
            for index, sample in enumerate(samples + new_samples):
                sample.write_bytes(f"fake-image-{index}".encode("utf-8"))

            def fake_extractor(path):
                return [FaceEmbedding(embedding=np.array([1.0, 0.0, 0.0], dtype=np.float32))]

            engine = FaceVectorEngine(data_dir=root / "data", face_extractor=fake_extractor)
            engine.register_profile("小菲", samples)
            first_avatar = Path(engine.load_profiles()["小菲"]["avatar_path"])

            self.assertTrue(first_avatar.exists())

            deleted = engine.delete_profile("小菲")

            self.assertEqual(deleted["label"], "小菲")
            self.assertFalse(first_avatar.exists())

            engine.register_profile("小菲", new_samples)
            second_avatar = Path(engine.load_profiles()["小菲"]["avatar_path"])

            self.assertTrue(second_avatar.exists())
            self.assertNotEqual(first_avatar, second_avatar)

    def test_scan_directory_and_match_label_filters_by_cosine_threshold(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            photo_root = root / "photos"
            photo_root.mkdir()
            xiaofei_photo = photo_root / "xiaofei-dog.jpg"
            other_photo = photo_root / "other-dog.jpg"
            xiaofei_photo.write_bytes(b"fake")
            other_photo.write_bytes(b"fake")
            samples = [root / "sample1.jpg", root / "sample2.jpg", root / "sample3.jpg"]
            for sample in samples:
                sample.write_bytes(b"fake")

            vectors = {
                "sample1.jpg": [1.0, 0.0, 0.0],
                "sample2.jpg": [1.0, 0.0, 0.0],
                "sample3.jpg": [1.0, 0.0, 0.0],
                "xiaofei-dog.jpg": [0.98, 0.02, 0.0],
                "other-dog.jpg": [0.0, 1.0, 0.0],
            }

            def fake_extractor(path):
                return [FaceEmbedding(embedding=np.array(vectors[Path(path).name], dtype=np.float32))]

            engine = FaceVectorEngine(data_dir=root / "data", face_extractor=fake_extractor, face_threshold=0.8)
            engine.register_profile("小菲", samples)
            stats = engine.scan_photo_directory(photo_root)

            matches = engine.match_label("小菲", candidate_paths=[xiaofei_photo, other_photo], limit=10)

            self.assertEqual(stats["indexed"], 2)
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0]["path"], str(xiaofei_photo.resolve()))
            self.assertGreater(matches[0]["face_score"], 0.8)

    def test_scan_photo_paths_indexes_explicit_derivative_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            originals = root / "Photos Library.photoslibrary" / "originals"
            derivative = root / "Photos Library.photoslibrary" / "resources" / "derivatives" / "A" / "asset.jpeg"
            originals.mkdir(parents=True)
            derivative.parent.mkdir(parents=True)
            derivative.write_bytes(b"fake")

            def fake_extractor(path):
                return [FaceEmbedding(embedding=np.array([1.0, 0.0, 0.0], dtype=np.float32))]

            engine = FaceVectorEngine(data_dir=root / "data", face_extractor=fake_extractor)

            stats = engine.scan_photo_paths([derivative])
            index = engine.load_photo_index()

            self.assertEqual(stats["indexed"], 1)
            self.assertIn(str(derivative.resolve()), index)
            self.assertNotIn(str(originals.resolve()), index)

    def test_scan_photo_paths_saves_batches_and_reports_progress(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "first.jpg"
            second = root / "second.jpg"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            snapshots = []

            def fake_extractor(path):
                return [FaceEmbedding(embedding=np.array([1.0, 0.0, 0.0], dtype=np.float32))]

            def progress_callback(snapshot):
                snapshots.append(dict(snapshot))
                if snapshot["processed"] == 1:
                    saved_index = FaceVectorEngine(data_dir=root / "data").load_photo_index()
                    self.assertIn(str(first.resolve()), saved_index)
                    self.assertNotIn(str(second.resolve()), saved_index)

            engine = FaceVectorEngine(data_dir=root / "data", face_extractor=fake_extractor)

            stats = engine.scan_photo_paths(
                [first, second],
                progress_callback=progress_callback,
                save_every=1,
            )

            self.assertEqual(stats, {"indexed": 2, "skipped": 0, "failed": 0})
            self.assertEqual([item["processed"] for item in snapshots], [1, 2])
            self.assertEqual([item["total"] for item in snapshots], [2, 2])


if __name__ == "__main__":
    unittest.main()
