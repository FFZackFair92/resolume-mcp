"""Autopilot del set: cambia colonna ogni N secondi. Ctrl+C per fermare."""
import sys, time, urllib.request

API = "http://127.0.0.1:8080/api/v1"
SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 30
COLUMNS = 8

while True:
    for col in range(1, COLUMNS + 1):
        urllib.request.urlopen(
            urllib.request.Request(f"{API}/composition/columns/{col}/connect", method="POST")
        ).read()
        print(f"colonna {col}")
        time.sleep(SECONDS)
