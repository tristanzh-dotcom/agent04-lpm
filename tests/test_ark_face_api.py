import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import ark_main
from backend.ark_index_engine import ArkPhotoIndexDatabase
from backend.ark_main import ArkSearchService


class FakeFaceEngine:
    def __init__(self):
        self.registered = []
        self.scanned_root = None
        self.indexed_paths = []
        self.profiles = [{"label": "小菲", "sample_count": 3, "updated_at": "2026-05-22T00:00:00+0800"}]

    def register_profile(self, label, image_paths):
        self.registered.append((label, [str(path) for path in image_paths]))
        return {"label": label, "sample_count": len(image_paths), "updated_at": "now"}

    def list_profiles(self):
        return self.profiles

    def scan_photo_directory(self, photo_root):
        self.scanned_root = str(photo_root)
        return {"indexed": 2, "skipped": 1, "failed": 0}

    def delete_profile(self, label):
        self.profiles = [profile for profile in self.profiles if profile["label"] != label]
        return {"status": "deleted", "label": label}

    def known_labels_in_query(self, query):
        return [profile["label"] for profile in self.profiles if profile["label"] in query]

    def match_label(self, label, *, candidate_paths=None, threshold=None, limit=100):
        paths = [str(path) for path in (candidate_paths if candidate_paths is not None else self.indexed_paths)]
        return [
            {"path": path, "label": label, "face_score": 0.91}
            for path in paths
            if path.endswith("xiaofei-dog.jpg") or path.endswith("xiaofei-birthday.jpg")
        ]


class FakeApplePeopleBridge:
    def __init__(self, *, links=None):
        self.links = links or []

    def list_named_people(self):
        return [
            {
                "label": "小菲",
                "uuid": "APPLE-PERSON-1",
                "entity_type": "person",
                "face_count": 12,
                "asset_count": len(self.links) or 2,
                "source": "apple_photos",
            }
        ]

    def iter_person_asset_links(self, *, limit=None):
        return list(self.links)


class DeniedApplePeopleBridge:
    def list_named_people(self):
        raise PermissionError("authorization denied")

    def iter_person_asset_links(self, *, limit=None):
        raise PermissionError("authorization denied")


class ArkFaceApiTests(unittest.TestCase):
    def test_face_register_route_accepts_label_and_three_files(self):
        fake = FakeFaceEngine()
        with patch("backend.ark_main.face_engine", fake):
            client = TestClient(ark_main.app)
            files = [
                ("files", ("a.jpg", b"a", "image/jpeg")),
                ("files", ("b.jpg", b"b", "image/jpeg")),
                ("files", ("c.jpg", b"c", "image/jpeg")),
            ]

            response = client.post("/api/face/register", data={"label": "小菲"}, files=files)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["label"], "小菲")
        self.assertEqual(payload["sample_count"], 3)
        self.assertEqual(fake.registered[0][0], "小菲")

    def test_face_profiles_and_reindex_routes_use_face_engine(self):
        fake = FakeFaceEngine()
        with patch("backend.ark_main.face_engine", fake):
            client = TestClient(ark_main.app)

            profiles_response = client.get("/api/face/profiles")
            reindex_response = client.post("/api/face/reindex", json={"photo_root": "/tmp/photos"})

        self.assertEqual(profiles_response.status_code, 200)
        self.assertEqual(profiles_response.json()[0]["label"], "小菲")
        self.assertEqual(reindex_response.json()["indexed"], 2)
        self.assertEqual(fake.scanned_root, "/tmp/photos")

    def test_face_profile_delete_route_removes_named_profile(self):
        fake = FakeFaceEngine()
        with patch("backend.ark_main.face_engine", fake):
            client = TestClient(ark_main.app)

            response = client.delete("/api/face/profiles/%E5%B0%8F%E8%8F%B2")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "deleted", "label": "小菲"})
        self.assertEqual(fake.profiles, [])

    def test_search_fuses_semantic_candidates_with_face_matches(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            xiaofei = root / "xiaofei-dog.jpg"
            other = root / "other-dog.jpg"
            xiaofei.write_bytes(b"fake")
            other.write_bytes(b"fake")
            db = ArkPhotoIndexDatabase(root / "limb.sqlite3")
            db.upsert_photo(
                path=xiaofei,
                md5="xiaofei-md5",
                modify_time=1.0,
                description="一位女性和狗狗在草地上合影",
                tags=["女性", "狗狗", "草地"],
                colors=["绿色"],
            )
            db.upsert_photo(
                path=other,
                md5="other-md5",
                modify_time=1.0,
                description="一位陌生人和狗狗在草地上合影",
                tags=["陌生人", "狗狗", "草地"],
                colors=["绿色"],
            )
            fake = FakeFaceEngine()
            fake.indexed_paths = [str(xiaofei)]
            service = ArkSearchService(
                db_path=root / "limb.sqlite3",
                photo_root=root,
                query_bridge=None,
                face_engine=fake,
            )

            rows = service.search("小菲和狗狗的照片", limit=10)

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["md5"], "xiaofei-md5")
            self.assertEqual(rows[0]["matched_labels"], ["小菲"])
            self.assertAlmostEqual(rows[0]["face_score"], 0.91)

    def test_people_profiles_route_merges_limb_and_apple_photos_sources(self):
        fake_face = FakeFaceEngine()
        fake_service = ArkSearchService(
            db_path=Path(tempfile.gettempdir()) / "unused-people-route.sqlite3",
            face_engine=fake_face,
            apple_people_bridge=FakeApplePeopleBridge(),
        )
        with patch("backend.ark_main.service", fake_service):
            client = TestClient(ark_main.app)

            response = client.get("/api/people/profiles")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual([item["source"] for item in payload], ["apple_photos", "limb_manual"])
        self.assertEqual(payload[0]["label"], "小菲")
        self.assertEqual(payload[0]["asset_count"], 2)
        self.assertEqual(payload[1]["sample_count"], 3)

    def test_people_profiles_include_avatar_urls_for_apple_and_limb_sources(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            apple_photo = root / "apple-xiaofei.jpg"
            limb_photo = root / "xiaofei-dog.jpg"
            apple_photo.write_bytes(b"fake")
            limb_photo.write_bytes(b"fake")
            db = ArkPhotoIndexDatabase(root / "limb.sqlite3")
            db.upsert_photo(
                path=apple_photo,
                md5="apple-avatar-md5",
                modify_time=1.0,
                description="Apple Photos 人物代表图",
                tags=["小菲"],
                colors=["白色"],
            )
            db.upsert_photo(
                path=limb_photo,
                md5="limb-avatar-md5",
                modify_time=1.0,
                description="LIMB 人物代表图",
                tags=["小菲"],
                colors=["绿色"],
            )
            fake_face = FakeFaceEngine()
            fake_face.indexed_paths = [str(limb_photo)]
            bridge = FakeApplePeopleBridge(
                links=[
                    {
                        "label": "小菲",
                        "uuid": "APPLE-PERSON-1",
                        "asset_uuid": "ASSET-1",
                        "original_path": str(apple_photo),
                        "quality": 0.95,
                        "source": "apple_photos",
                    }
                ]
            )
            service = ArkSearchService(
                db_path=root / "limb.sqlite3",
                photo_root=root,
                query_bridge=None,
                face_engine=fake_face,
                apple_people_bridge=bridge,
            )

            profiles = service.list_person_profiles()

            self.assertEqual(profiles[0]["source"], "apple_photos")
            self.assertEqual(profiles[0]["avatar_url"], "http://127.0.0.1:8004/thumbnails/apple-avatar-md5.jpg")
            self.assertEqual(profiles[1]["source"], "limb_manual")
            self.assertEqual(profiles[1]["avatar_url"], "http://127.0.0.1:8004/thumbnails/limb-avatar-md5.jpg")

    def test_people_profiles_reuses_apple_asset_links_for_avatar_resolution(self):
        class CountingApplePeopleBridge:
            def __init__(self, links):
                self.links = links
                self.asset_link_calls = 0

            def list_named_people(self):
                return [
                    {
                        "label": "小菲",
                        "uuid": "APPLE-PERSON-1",
                        "entity_type": "person",
                        "face_count": 12,
                        "asset_count": 1,
                        "source": "apple_photos",
                    },
                    {
                        "label": "老妈",
                        "uuid": "APPLE-PERSON-2",
                        "entity_type": "person",
                        "face_count": 10,
                        "asset_count": 1,
                        "source": "apple_photos",
                    },
                ]

            def iter_person_asset_links(self, *, limit=None):
                self.asset_link_calls += 1
                return list(self.links)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            xiaofei_photo = root / "xiaofei.jpg"
            laoma_photo = root / "laoma.jpg"
            xiaofei_photo.write_bytes(b"fake")
            laoma_photo.write_bytes(b"fake")
            db = ArkPhotoIndexDatabase(root / "limb.sqlite3")
            db.upsert_photo(
                path=xiaofei_photo,
                md5="xiaofei-avatar-md5",
                modify_time=1.0,
                description="小菲头像",
                tags=["小菲"],
                colors=["绿色"],
            )
            db.upsert_photo(
                path=laoma_photo,
                md5="laoma-avatar-md5",
                modify_time=1.0,
                description="老妈头像",
                tags=["老妈"],
                colors=["蓝色"],
            )
            bridge = CountingApplePeopleBridge(
                [
                    {"label": "小菲", "original_path": str(xiaofei_photo), "quality": 0.9},
                    {"label": "老妈", "original_path": str(laoma_photo), "quality": 0.8},
                ]
            )
            service = ArkSearchService(
                db_path=root / "limb.sqlite3",
                photo_root=root,
                query_bridge=None,
                face_engine=None,
                apple_people_bridge=bridge,
            )

            profiles = service.list_person_profiles()

            self.assertEqual(bridge.asset_link_calls, 1)
            self.assertEqual([profile["label"] for profile in profiles], ["小菲", "老妈"])
            self.assertEqual(profiles[0]["avatar_url"], "http://127.0.0.1:8004/thumbnails/xiaofei-avatar-md5.jpg")
            self.assertEqual(profiles[1]["avatar_url"], "http://127.0.0.1:8004/thumbnails/laoma-avatar-md5.jpg")

    def test_manual_people_profile_avatar_prefers_registered_sample_avatar_over_face_match(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sample_avatar = root / "sample-avatar.jpg"
            old_match = root / "old-xiaofei.jpg"
            sample_avatar.write_bytes(b"sample-avatar")
            old_match.write_bytes(b"old-match")
            db = ArkPhotoIndexDatabase(root / "limb.sqlite3")
            db.upsert_photo(
                path=old_match,
                md5="old-match-md5",
                modify_time=1.0,
                description="旧相册匹配图",
                tags=["小菲"],
                colors=["白色"],
            )
            fake_face = FakeFaceEngine()
            fake_face.indexed_paths = [str(old_match)]
            fake_face.profiles = [
                {
                    "label": "小菲",
                    "sample_count": 3,
                    "updated_at": "2026-05-22T00:00:00+0800",
                    "avatar_path": str(sample_avatar),
                }
            ]
            service = ArkSearchService(
                db_path=root / "limb.sqlite3",
                photo_root=root,
                query_bridge=None,
                face_engine=fake_face,
                apple_people_bridge=FakeApplePeopleBridge(links=[]),
            )

            profiles = service.list_person_profiles()

            self.assertEqual(profiles[1]["source"], "limb_manual")
            self.assertEqual(profiles[1]["avatar_url"], "http://127.0.0.1:8004/face-avatars/sample-avatar.jpg")

    def test_apple_people_avatar_falls_back_to_photo_url_when_not_indexed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            apple_photo = root / "apple-only.jpg"
            apple_photo.write_bytes(b"fake")
            bridge = FakeApplePeopleBridge(
                links=[
                    {
                        "label": "小菲",
                        "uuid": "APPLE-PERSON-1",
                        "asset_uuid": "ASSET-1",
                        "original_path": str(apple_photo),
                        "quality": 0.95,
                        "source": "apple_photos",
                    }
                ]
            )
            service = ArkSearchService(
                db_path=root / "limb.sqlite3",
                photo_root=root,
                query_bridge=None,
                face_engine=None,
                apple_people_bridge=bridge,
            )

            profiles = service.list_person_profiles()

            self.assertEqual(profiles[0]["avatar_url"], "http://127.0.0.1:8004/photos/apple-only.jpg")

    def test_search_uses_apple_photos_person_links_without_manual_face_profile(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            xiaofei = root / "xiaofei-dog.jpg"
            other = root / "other-dog.jpg"
            xiaofei.write_bytes(b"fake")
            other.write_bytes(b"fake")
            db = ArkPhotoIndexDatabase(root / "limb.sqlite3")
            db.upsert_photo(
                path=xiaofei,
                md5="apple-xiaofei-md5",
                modify_time=1.0,
                description="小菲和狗狗在草地合影",
                tags=["小菲", "狗狗", "草地"],
                colors=["绿色"],
            )
            db.upsert_photo(
                path=other,
                md5="other-md5",
                modify_time=1.0,
                description="陌生人和狗狗在草地合影",
                tags=["狗狗", "草地"],
                colors=["绿色"],
            )
            bridge = FakeApplePeopleBridge(
                links=[
                    {
                        "label": "小菲",
                        "uuid": "APPLE-PERSON-1",
                        "asset_uuid": "ASSET-1",
                        "original_path": str(xiaofei),
                        "quality": 0.95,
                        "source": "apple_photos",
                    }
                ]
            )
            service = ArkSearchService(
                db_path=root / "limb.sqlite3",
                photo_root=root,
                query_bridge=None,
                face_engine=None,
                apple_people_bridge=bridge,
            )

            rows = service.search("小菲和狗狗的照片", limit=10)

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["md5"], "apple-xiaofei-md5")
            self.assertEqual(rows[0]["matched_labels"], ["小菲"])
            self.assertEqual(rows[0]["identity_source"], "apple_photos")

    def test_people_profiles_route_uses_apple_cache_when_photos_sqlite_is_denied(self):
        fake_face = FakeFaceEngine()
        fake_cache = FakeApplePeopleBridge()
        fake_service = ArkSearchService(
            db_path=Path(tempfile.gettempdir()) / "unused-people-cache-route.sqlite3",
            face_engine=fake_face,
            apple_people_bridge=DeniedApplePeopleBridge(),
            apple_people_cache=fake_cache,
        )
        with patch("backend.ark_main.service", fake_service):
            client = TestClient(ark_main.app)

            response = client.get("/api/people/profiles")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload[0]["label"], "小菲")
        self.assertEqual(payload[0]["source"], "apple_photos")
        self.assertEqual(payload[1]["source"], "limb_manual")

    def test_search_uses_apple_cache_links_when_photos_sqlite_is_denied(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            xiaofei = root / "xiaofei-dog.jpg"
            xiaofei.write_bytes(b"fake")
            db = ArkPhotoIndexDatabase(root / "limb.sqlite3")
            db.upsert_photo(
                path=xiaofei,
                md5="cached-apple-xiaofei-md5",
                modify_time=1.0,
                description="小菲和狗狗在草地合影",
                tags=["小菲", "狗狗", "草地"],
                colors=["绿色"],
            )
            fake_cache = FakeApplePeopleBridge(
                links=[
                    {
                        "label": "小菲",
                        "uuid": "APPLE-PERSON-1",
                        "asset_uuid": "ASSET-1",
                        "original_path": str(xiaofei),
                        "quality": 0.95,
                        "source": "apple_photos",
                    }
                ]
            )
            service = ArkSearchService(
                db_path=root / "limb.sqlite3",
                photo_root=root,
                query_bridge=None,
                face_engine=None,
                apple_people_bridge=DeniedApplePeopleBridge(),
                apple_people_cache=fake_cache,
            )

            rows = service.search("小菲和狗狗的照片", limit=10)

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["md5"], "cached-apple-xiaofei-md5")
            self.assertEqual(rows[0]["matched_labels"], ["小菲"])
            self.assertEqual(rows[0]["identity_source"], "apple_photos")

    def test_search_falls_back_to_face_matches_when_semantic_terms_miss_index(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            xiaofei = root / "xiaofei-birthday.jpg"
            xiaofei.write_bytes(b"fake")
            db = ArkPhotoIndexDatabase(root / "limb.sqlite3")
            db.upsert_photo(
                path=xiaofei,
                md5="xiaofei-md5",
                modify_time=1.0,
                description="一位女性拿着生日蛋糕微笑",
                tags=["女性", "生日", "蛋糕"],
                colors=["蓝色"],
            )
            fake = FakeFaceEngine()
            fake.indexed_paths = [str(xiaofei)]
            service = ArkSearchService(
                db_path=root / "limb.sqlite3",
                photo_root=root,
                query_bridge=None,
                face_engine=fake,
            )

            rows = service.search("小菲跳伞", limit=10)

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["md5"], "xiaofei-md5")
            self.assertTrue(rows[0]["semantic_miss"])
            self.assertEqual(rows[0]["matched_labels"], ["小菲"])

    def test_search_reports_diagnostic_when_semantic_terms_miss_index_and_face_fallback_is_used(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            zhang = root / "xiaofei-birthday.jpg"
            zhang.write_bytes(b"fake")
            db = ArkPhotoIndexDatabase(root / "limb.sqlite3")
            db.upsert_photo(
                path=zhang,
                md5="zhang-md5",
                modify_time=1.0,
                description="老张在室内自拍",
                tags=["老张", "自拍"],
                colors=["白色"],
            )
            fake = FakeFaceEngine()
            fake.profiles = [{"label": "老张", "sample_count": 3, "updated_at": "now"}]
            fake.indexed_paths = [str(zhang)]
            service = ArkSearchService(
                db_path=root / "limb.sqlite3",
                photo_root=root,
                query_bridge=None,
                face_engine=fake,
            )

            rows = service.search("我想看老张和狗狗在一起的照片", limit=10)

            self.assertEqual(len(rows), 1)
            self.assertTrue(rows[0]["semantic_miss"])
            self.assertEqual(service.last_search_diagnostic["kind"], "semantic_face_terms_not_found")
            self.assertEqual(service.last_search_diagnostic["labels"], ["老张"])
            self.assertIn("场景条件未命中", service.last_search_diagnostic["message"])

    def test_search_falls_back_to_face_matches_when_semantic_candidates_fail_face_filter(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dog = root / "dog-with-other-person.jpg"
            xiaofei = root / "xiaofei-birthday.jpg"
            dog.write_bytes(b"fake")
            xiaofei.write_bytes(b"fake")
            db = ArkPhotoIndexDatabase(root / "limb.sqlite3")
            db.upsert_photo(
                path=dog,
                md5="dog-md5",
                modify_time=1.0,
                description="一位陌生人和小狗在草地上合影",
                tags=["陌生人", "小狗", "草地"],
                colors=["绿色"],
            )
            db.upsert_photo(
                path=xiaofei,
                md5="xiaofei-md5",
                modify_time=1.0,
                description="小菲在室内过生日",
                tags=["小菲", "生日", "室内"],
                colors=["白色"],
            )
            fake = FakeFaceEngine()
            fake.indexed_paths = [str(xiaofei)]
            service = ArkSearchService(
                db_path=root / "limb.sqlite3",
                photo_root=root,
                query_bridge=None,
                face_engine=fake,
            )

            rows = service.search("小菲和小狗", limit=10)

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["md5"], "xiaofei-md5")
            self.assertTrue(rows[0]["semantic_miss"])
            self.assertEqual(rows[0]["matched_labels"], ["小菲"])
            self.assertEqual(service.last_search_diagnostic["kind"], "semantic_face_intersection_empty")
            self.assertEqual(service.last_search_diagnostic["semantic_candidate_count"], 1)
            self.assertEqual(service.last_search_diagnostic["labels"], ["小菲"])

    def test_search_treats_relation_particle_yu_as_connector_for_pet_terms(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dog = root / "dog-with-other-person.jpg"
            xiaofei = root / "xiaofei-birthday.jpg"
            dog.write_bytes(b"fake")
            xiaofei.write_bytes(b"fake")
            db = ArkPhotoIndexDatabase(root / "limb.sqlite3")
            db.upsert_photo(
                path=dog,
                md5="dog-md5",
                modify_time=1.0,
                description="一位陌生人和狗狗在草地上合影",
                tags=["陌生人", "狗狗", "草地"],
                colors=["绿色"],
            )
            db.upsert_photo(
                path=xiaofei,
                md5="xiaofei-md5",
                modify_time=1.0,
                description="小菲在室内过生日",
                tags=["小菲", "生日", "室内"],
                colors=["白色"],
            )
            fake = FakeFaceEngine()
            fake.indexed_paths = [str(xiaofei)]
            service = ArkSearchService(
                db_path=root / "limb.sqlite3",
                photo_root=root,
                query_bridge=None,
                face_engine=fake,
            )

            rows = service.search("小菲与狗狗", limit=10)

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["md5"], "xiaofei-md5")
            self.assertTrue(rows[0]["semantic_miss"])
            self.assertEqual(service.last_search_diagnostic["kind"], "semantic_face_intersection_empty")
            self.assertEqual(service.last_search_diagnostic["semantic_query"], "狗狗")
            self.assertEqual(service.last_search_diagnostic["semantic_candidate_count"], 1)

    def test_search_returns_missing_profile_diagnostic_for_known_unregistered_person(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile_path = root / "family_profile.json"
            profile_path.write_text('{"小菲": "夫人，亚洲女性"}', encoding="utf-8")
            fake = FakeFaceEngine()
            fake.profiles = []
            service = ArkSearchService(
                db_path=root / "limb.sqlite3",
                photo_root=root,
                family_profile_path=profile_path,
                query_bridge=None,
                face_engine=fake,
            )

            rows = service.search("小菲和小狗", limit=10)

            self.assertEqual(rows, [])
            self.assertEqual(service.last_search_diagnostic["kind"], "face_profile_missing")
            self.assertEqual(service.last_search_diagnostic["labels"], ["小菲"])

    def test_search_diagnostic_header_is_exposed_to_browser_cors(self):
        class DiagnosticService:
            last_search_diagnostic = {
                "kind": "face_filter_empty",
                "message": "已找到 2 张符合 [吃饭] 的照片，但没有照片同时匹配 [老张] 的人脸。",
            }

            def search(self, query, *, limit=50):
                return []

        with patch("backend.ark_main.service", DiagnosticService()):
            client = TestClient(ark_main.app)
            response = client.post(
                "/api/search",
                headers={"Origin": "http://127.0.0.1:3000"},
                json={"query": "老张吃饭", "limit": 10},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("x-limb-search-diagnostic", response.headers)
        self.assertIn(
            "X-LIMB-Search-Diagnostic",
            response.headers.get("access-control-expose-headers", ""),
        )


if __name__ == "__main__":
    unittest.main()
