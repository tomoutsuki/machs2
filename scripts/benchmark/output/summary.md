# Benchmark Summary

| Mode | Write ms | Read ms | Decrypt ms | Avg bytes |
|---|---:|---:|---:|---:|
| fabeo | 498.69 | 77.64 | 77.82 | 273.0 |
| aes_gcm | 480.38 | 79.56 | 64.55 | 291.0 |
| tde | 582.81 | 76.07 | 78.41 | 287.0 |
| column_level | 486.48 | 85.52 | 87.44 | 296.0 |
| app_level | 506.74 | 72.84 | 70.38 | 293.0 |

## Notes
- CPU/memory: run `docker stats` while benchmark executes.
- TDE is simulated for local comparability in this MVP.