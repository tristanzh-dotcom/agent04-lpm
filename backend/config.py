"""本地图像检索 local runtime configuration.

Edit this file on the local Mac before starting the FastAPI backend.
Values in this file take priority over launchd or shell environment variables.
"""

import os


DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")
LIMB_PHOTO_ROOT = os.environ.get(
    "LIMB_PHOTO_ROOT",
    "/Users/tristanzh/Pictures/Photos Library.photoslibrary/originals",
)
LIMB_THUMBNAIL_DIR = os.environ.get("LIMB_THUMBNAIL_DIR", os.path.expanduser("~/.cache/local-photo-model/thumbnails"))
LIMB_FACE_THRESHOLD = os.environ.get("LIMB_FACE_THRESHOLD", "0.65")
LIMB_PHOTOS_BASE_URL = os.environ.get("LIMB_PHOTOS_BASE_URL", "http://127.0.0.1:8004/photos")
