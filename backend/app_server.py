from flask import Flask, jsonify, request

try:
    from backend.models.entity_query import EntityQueryEngine
except ImportError:  # pragma: no cover - direct script execution fallback
    from models.entity_query import EntityQueryEngine


app = Flask(__name__)
DB_PATH = "/Users/tristanzh/agent/Local-photo-model/tests/sandbox_limb_workbench.db"
query_engine = EntityQueryEngine(DB_PATH)


@app.route("/", methods=["GET"])
def health_check():
    return jsonify(
        {
            "status": "SUCCESS",
            "service": "LIMB Entity Inner Core",
            "routes": [
                "/api/entities/list",
                "/api/entities/search",
            ],
        }
    )


@app.route("/api/entities/list", methods=["GET"])
def list_entities():
    """暴露给旁路画布大纲与组件资产的统一实体元数据接口。"""
    try:
        entities = query_engine.get_all_registered_entities()
        return jsonify({"status": "SUCCESS", "data": entities})
    except Exception as exc:
        return jsonify({"status": "ERROR", "message": str(exc)}), 500


@app.route("/api/entities/search", methods=["POST"])
def search_by_entities():
    """接收前端拖拽组合后的标签包，执行高级交并集碰撞。"""
    req_data = request.json or {}
    entity_ids = req_data.get("entity_ids", [])
    mode = req_data.get("mode", "INTERSECT")

    try:
        matched_assets = query_engine.query_assets_by_entities(entity_ids, match_mode=mode)
        return jsonify(
            {
                "status": "SUCCESS",
                "count": len(matched_assets),
                "assets": matched_assets,
            }
        )
    except Exception as exc:
        return jsonify({"status": "ERROR", "message": str(exc)}), 500


if __name__ == "__main__":
    app.run(port=5001)
