# Frigate discussion #23319 — System metrics screenshots

Screenshots referenced from https://github.com/blakeblackshear/frigate/discussions/23319

Captured **after** the QSV workaround was applied (the auto-VAAPI bug was already
mitigated). They show the healthy steady-state with `hwaccel_args:
preset-intel-qsv-h264` — confirming the workaround is stable rather than
documenting the original failure (which is captured by the ffmpeg crash logs
in the discussion body).

## Files

- `01-system-general.png` — Frigate System → General tab. Shows
  `intel-qsv 0.0%` GPU usage (proves QSV is active, not VAAPI), Coral at
  10ms inference / 0% CPU / 1% mem, Frigate `0.17.1-416a9b7`.
- `02-system-cameras.png` — Frigate System → Cameras tab. Shows
  **skipped 0** across both cameras (key metric: zero frame loss under QSV),
  ffmpeg CPU ~1% per camera, 5fps detect rate matching configured value.
- `03-system-storage.png` — Frigate System → Storage tab. Included for
  template completeness; not directly bug-relevant.

Frigate 0.17.1 only has three System tabs (General / Storage / Cameras);
detector info is consolidated into General.
