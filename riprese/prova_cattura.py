# /// script
# dependencies = ["obsws-python"]
# ///
import base64, json, sys, time
from pathlib import Path
import obsws_python as obs
PWD = json.loads((Path.home() / "AppData/Roaming/obs-studio/plugin_config/obs-websocket/config.json").read_text())["server_password"]
c = obs.ReqClient(host="localhost", port=4455, password=PWD, timeout=10)
S = "Schermo MCP"
print(c.get_input_settings(S).input_settings)
mons = c.get_input_properties_list_property_items(S, "monitor_id").property_items
print(mons)
mid = next(m["itemValue"] for m in mons if m["itemEnabled"])
c.set_input_settings(S, {"monitor_id": mid}, True)
for m in sys.argv[1:]:
    c.set_input_settings(S, {"method": int(m), "capture_cursor": False}, True)
    time.sleep(1.5)
    img = c.get_source_screenshot(S, "jpg", 480, 270, 70).image_data
    raw = base64.b64decode(img.split(",", 1)[1])
    p = Path(__file__).with_name(f"cattura_m{m}.jpg"); p.write_bytes(raw)
    print(m, len(raw))
