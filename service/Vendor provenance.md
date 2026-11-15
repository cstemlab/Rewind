# Bundled WebSocket transport

- Package: `websocket-client==1.9.0`, Python wheel `websocket_client-1.9.0-py3-none-any.whl`.
- Source: official PyPI package distribution, downloaded by pip on 2026-11-16 with `--no-deps --only-binary=:all:`. Installed only into this service's `vendor/` using `--no-index --no-deps --no-compile --target`; no global Python environment changes.
- Wheel SHA-256: `af248a825037ef591efbf6ed20cc5faa03d3b47b9e5a2230a529eeee1c1fc3ef`.
- Upstream licenses and package metadata are retained under `vendor/websocket_client-1.9.0.dist-info/`. Vendored library source is unchanged. Transport bounds are applied in the application's `BoundedWebSocket` subclass.
- Runtime packaging must retain `vendor/websocket/` and the distribution metadata/license directory. The `vendor-wheels/` directory is an optional offline reinstall archive.

The app uses TLS verification, the fixed official OpenAI websocket URL, no redirect following and no debug trace. Secrets remain in the local process and are not embedded in the frontend.

Published source includes runtime modules and licenses; optional upstream test fixtures, command-line launcher, pip local-source metadata and wheel archive are omitted.
