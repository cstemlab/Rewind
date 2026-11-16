# Bundled WebSocket transport

- Package: `websocket-client==1.9.0`, Python wheel `websocket_client-1.9.0-py3-none-any.whl`.
- Source: official PyPI package distribution, downloaded by pip on 2026-11-16 with `--no-deps --only-binary=:all:`. Installed only into this service's `vendor/` using `--no-index --no-deps --no-compile --target`; no global Python environment changes.
- Wheel SHA-256: `af248a825037ef591efbf6ed20cc5faa03d3b47b9e5a2230a529eeee1c1fc3ef`.
- Upstream licenses and package metadata are retained under `vendor/websocket_client-1.9.0.dist-info/`. Vendored library source is unchanged. Transport bounds are applied in the application's `BoundedWebSocket` subclass.
- Runtime packaging must retain `vendor/websocket/` and the distribution metadata/license directory. The `vendor-wheels/` directory is an optional offline reinstall archive.

The app uses TLS verification, the fixed official OpenAI websocket URL, no redirect following and no debug trace. Secrets remain in the local process and are not embedded in the frontend.

## Document extraction added in r11

`pypdf==6.21.4` is copied from the installed Codex bundled Python runtime package on 2026-11-16. Its package metadata identifies the official pure-Python pypdf project and BSD-3-Clause license. Source is unchanged; cache files and local installation URL metadata are excluded. Runtime packaging retains `vendor/pypdf/` and `vendor/pypdf-6.21.4.dist-info/licenses/LICENSE`, `METADATA` and `WHEEL`. The optional command-line entry points and installer bookkeeping are not required.

The application configures an 8 MB Flate decoding bound and runs extraction in a short-lived, timeout-limited process. No source document or extracted text is written to disk by that process. No optional cryptography dependency is added: encrypted PDFs are rejected with a clear message.
