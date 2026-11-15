# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx>=0.27"]
# ///
"""Quanti PUT al secondo regge Resolume: decide se lo strobo si puo' fare da qui
o va lasciato a un effetto interno. A 170 bpm un quarto di battuta e' 88 ms."""
import os
import time

import httpx

BASE = os.environ.get("RESOLUME_URL", "http://127.0.0.1:8080").rstrip("/") + "/api/v1"
http = httpx.Client(timeout=5.0)

N = 60
t0 = time.time()
for i in range(N):
    v = 1.0 if i % 2 else 0.98
    http.put(BASE + "/composition", json={"video": {"opacity": {"value": v}}})
dt = time.time() - t0
print(f"{N} PUT in {dt:.2f}s -> {N/dt:.1f} al secondo, {dt/N*1000:.0f} ms l'uno")
http.put(BASE + "/composition", json={"video": {"opacity": {"value": 1.0}}})
