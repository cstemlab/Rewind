# Hosted frontend contract

All API calls use exact `Origin: https://cstemlab.github.io`, JSON request bodies and `Cache-Control: no-store` responses. CORS permits only GET, POST, OPTIONS and the Authorization/Content-Type request headers. No cookies are used.

1. `GET /api/status` without authorization returns `{configured:false,mode:'hosted-trial',requires_access_code:true,supported_providers:['gemini']}`. The list includes `openai` as well only when its owner secret is configured.
2. `POST /api/session` with `{access_code}` returns `{ok:true,token,expires_in:1800,absolute_expires_in:7200}`. Save this opaque token per browser session; do not put it in a URL.
3. Use `Authorization: Bearer <token>` for every functional request. GET `/api/status` returns the same status structure as the local app, with `mode:'hosted-trial'`, `key_storage:'server-environment'`, session expiration fields and truthful runtime provider capabilities. Provider configured does not mean it has passed a real API call; `connection_verified` is false until assessment succeeds.
4. Existing POST routes `/api/assess-recording`, `/api/live/start|audio|events|stop|cancel` and `/api/creator/extract|translate|render|status|cancel` retain body/result contracts. `provider` in assessment and live requests must match status. Check `live_transcription.available` before starting live capture. Both provider adapters are implemented; actual project/model availability still needs a live connection test. Browser PCM remains 24 kHz; the Google adapter converts to 16 kHz internally.
5. `POST /api/session/end` with `{}` ends only the current visitor. `/api/config` and `/api/disconnect` return 404; browser clients cannot change the owner's provider or key.
6. `POST /api/session/provider` with `{provider:'gemini'}` or `{provider:'openai'}` explicitly selects a configured provider for this visitor. It cancels only this visitor's live/generation work and returns updated status. The bearer token, original creation time, absolute lifetime and rate windows survive the switch. It never silently falls back and never accepts a key.

Errors preserve `{error:humanMessage,code:machineCode}`. Session missing/expired yields 401 (`session_required` or `session_expired`); wrong invite code yields 403 `access_denied`; unsupported Origin yields 403 `origin_denied`; capacity/rate exhaustion yields 429 `rate_limited` with `Retry-After:60`. Job/session mismatch yields 409. Refresh the invitation connection after 401; do not silently resubmit paid work.

Valid authenticated activity refreshes idle expiration, never the 2-hour absolute limit. Creation/status/live data belong only to that visitor, so another visitor's job ID or recording ID is rejected. Generated results expire 5 minutes after terminal status, even while a visitor remains connected.

The app serializes one generation job globally and two assessments globally. Limits: assessment 5/61s per visitor and 20/61s total; live starts 5/61s per visitor and 20/61s total; creator starts 4/10min per visitor and 12/10min total. Invalid attempts can consume rate-limit slots. Per-request JSON caps are 1,200,000 bytes, except extraction 6,700,000 bytes and handshake 4,096 bytes. Existing model/audio/document limits still apply.

`GET /health` is public and requires no Origin, for process and container probes only. It returns only `{ok:true}`. Its success does not verify billing, model access or runtime credentials. `/healthz` is retained as an internal compatibility alias; use `/health` through the public Cloud Run gateway.
