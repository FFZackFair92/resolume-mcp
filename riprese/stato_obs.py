# /// script
# dependencies = ["obsws-python"]
# ///
import json
from pathlib import Path
import obsws_python as obs
PWD = json.loads((Path.home() / "AppData/Roaming/obs-studio/plugin_config/obs-websocket/config.json").read_text())["server_password"]
c = obs.ReqClient(host="localhost", port=4455, password=PWD, timeout=10)
r = c.get_record_status()
print("record attivo:", r.output_active, "durata:", r.output_timecode)
print("scena:", c.get_current_program_scene().scene_name)
