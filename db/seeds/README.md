Database seed data is loaded by machs_main_api startup from /workspace/resources.

Deterministic reset behavior:
- MAIN_API_RESET_ON_START=true clears mode tables and session_usk.
- users are upserted from resources/users_seed.yaml.
- FHIR seed files are encrypted and inserted into all modes.
