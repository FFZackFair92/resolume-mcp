# /// script
# dependencies = ["obsws-python"]
# ///
import json
from pathlib import Path
import obsws_python as obs
PWD = json.loads((Path.home() / "AppData/Roaming/obs-studio/plugin_config/obs-websocket/config.json").read_text())["server_password"]
c = obs.ReqClient(host="localhost", port=4455, password=PWD, timeout=10)
if c.get_record_status().output_active:
    print("fermata:", c.stop_record().output_path)
else:
    print("nessuna registrazione attiva")
