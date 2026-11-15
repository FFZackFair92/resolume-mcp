# /// script
# requires-python = ">=3.10"
# dependencies = ["opencv-python>=4.10", "numpy>=1.26"]
# ///
"""Esposizione e guadagno spinti al massimo.

Se anche cosi' resta nero, la luce non arriva proprio al sensore: otturatore
fisico chiuso o stanza al buio. Se invece si schiarisce, era solo esposizione.
"""
import time

import cv2

cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

for i in range(20):
    cap.read()
    time.sleep(0.02)

print("auto  :", round(float(cap.read()[1].mean()), 2))

cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)      # 0.25 = manuale, in DSHOW
for esp in (-4, -3, -2, -1, 0):
    cap.set(cv2.CAP_PROP_EXPOSURE, esp)
    for _ in range(12):
        cap.read()
        time.sleep(0.03)
    ok, f = cap.read()
    print(f"esp {esp:>3}:", round(float(f.mean()), 2), "max", int(f.max()))

cap.set(cv2.CAP_PROP_GAIN, 255)
cap.set(cv2.CAP_PROP_BRIGHTNESS, 255)
for _ in range(15):
    cap.read()
    time.sleep(0.03)
ok, f = cap.read()
print("gain+lum al massimo:", round(float(f.mean()), 2), "max", int(f.max()))
cv2.imwrite("diagnosi.jpg", f)
cap.release()
