import os
import sys
from collections import defaultdict

try:
    from backend.apple_photos_bridge import ApplePhotosPeopleBridge
    from backend.models.entity_registry import EntityRegistry
except ImportError:  # pragma: no cover - direct script execution fallback
    from apple_photos_bridge import ApplePhotosPeopleBridge
    from models.entity_registry import EntityRegistry


def run_sync_pipeline(db_path: str):
    print("=== STARTING LIMB HYBRID ENTITY SYNC PIPELINE ===")
    registry = EntityRegistry(db_path)
    bridge = ApplePhotosPeopleBridge(_resolve_photo_library_path())

    try:
        named_people = bridge.list_named_people()
        asset_links = bridge.iter_person_asset_links()
        links_by_person = _group_asset_links_by_person(asset_links)

        print(f"[SYNC] Detected {len(named_people)} named entities from Apple Photos library.")

        for person in named_people:
            uuid = _person_external_uuid(person)
            name = _person_display_name(person)
            asset_paths = links_by_person.get(_person_link_key(person), [])
            registry.sync_apple_person(uuid, name, asset_paths)
            print(f"  -> Synchronized inherited entity: [{name}] | Connected Assets: {len(asset_paths)}")
    except Exception as exc:
        print(f"[CRITICAL] Apple Photos bridge synchronization broken: {exc}", file=sys.stderr)
        sys.exit(1)

    print("[SYNC] Registering LIMB exclusive custom entity objects...")
    registry.register_custom_entity(
        entity_id="custom_defender_110",
        category="vehicle",
        display_name="路虎卫士",
        aliases=["Defender", "卫士", "车"],
    )
    registry.register_custom_entity(
        entity_id="custom_pet_mantou",
        category="pet",
        display_name="馒头",
        aliases=["Mantu", "Mantou", "小狗"],
    )

    print("=== HYBRID ENTITY PIPELINE COMPLETED SUCCESSFULLY ===")


def _resolve_photo_library_path():
    return (
        os.environ.get("LIMB_PHOTO_LIBRARY_ROOT")
        or os.environ.get("APPLE_PHOTOS_LIBRARY")
        or os.path.expanduser("~/Pictures/Photos Library.photoslibrary")
    )


def _group_asset_links_by_person(asset_links):
    grouped = defaultdict(list)
    for link in asset_links:
        grouped[_person_link_key(link)].append(link["original_path"])
    return grouped


def _person_link_key(person):
    return person.get("uuid") or person.get("person_pk") or person.get("label") or person.get("name")


def _person_external_uuid(person):
    return str(person.get("uuid") or person.get("person_pk"))


def _person_display_name(person):
    return str(person.get("name") or person.get("label"))


if __name__ == "__main__":
    target_db = "tests/sandbox_limb_workbench.db"
    run_sync_pipeline(target_db)
