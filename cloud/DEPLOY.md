# Rewind hosted demonstration

Prepared 2026-11-16. This package is **not a deployed service**. The project selected by the user is `rewind-514904`. Billing, runtime permissions, actual Google responses and the final public URL must be checked before inviting users.

The GitHub Pages player calls a Cloud Run backend. The owner pays the backend and provider bills. Visitors enter a trial access code; they do not enter provider keys. Google is the default hosted provider: Gemini handles script conversion, live transcription and recorded-audio feedback; Cloud Text-to-Speech narrates the approved Cantonese text. Gemini feedback remains experimental audio coaching, not a calibrated Cantonese tone test. Live transcription tracks words that were heard; it does not certify their pronunciation. Google Live Cantonese support is experimental and its actual availability must be checked in this project.

## 1. Project and billing

1. Open [Google Cloud Console](https://console.cloud.google.com/) and select **Rewind / rewind-514904**.
2. In **Billing**, link an active billing account to that project. The project ID alone does not enable billing.
3. In **Billing → Budgets & alerts**, create a small test budget with email alerts. A budget is an alert, not an automatic spending cap.
4. Install [Google Cloud CLI](https://cloud.google.com/sdk/docs/install), or use Cloud Shell. For this Windows deployment script, run `gcloud auth login` and finish the account authorization yourself. No service-account JSON key is needed.

Only share the project ID and deployment status in chat; do not paste a provider key or access code.

## 2. Owner-managed invitation secret

Use **Secret Manager → Create secret** to create `rewind-demo-access`, with a random 20–200-character value. Keep the value in your password manager. Note the numeric secret version, normally `1`. The access code is shared only with invited testers.

Alternatively, the included helper prompts privately and sends the secret to `gcloud` through stdin. The value is never written to a file or command-line argument:

```powershell
gcloud services enable secretmanager.googleapis.com --project=rewind-514904
python .\provision-secret.py --project rewind-514904 --name rewind-demo-access
```

The deployment uses a numeric version, not `latest`. To rotate the code, create a new version and deploy with that number. Redeployment invalidates in-memory visitor sessions. The optional OpenAI backend uses a separate `rewind-openai-key` secret; Google deployment does not need it. If that secret is configured, visitors can explicitly switch between Google and OpenAI; there is no automatic fallback or visitor API-key entry. Changing a billing owner or adding a backend does not remove a provider's regional availability rules.

## 3. Deploy from this package

For Cloud Shell, the Linux scripts separate review/preparation from deployment:

```bash
cd ~/rewind-cloud
bash prepare-cloud.sh
# After reviewing the printed IAM/resource plan:
bash prepare-cloud.sh --apply
python3 provision-secret.py --project rewind-514904 --name rewind-demo-access
python3 verify.py
ACCESS_SECRET_VERSION=1 bash build-and-deploy.sh
```

The secret helper is interactive and owner-operated. To add OpenAI later, provision `rewind-openai-key`, then supply its numeric version with `OPENAI_SECRET_VERSION=1` when running the build/deploy script. Leave `DEFAULT_PROVIDER=gemini` to retain Google as the default.

Review `deploy.ps1`, then run from this folder:

```powershell
.\deploy.ps1 -ProjectId rewind-514904 -AccessSecretVersion 1
```

The script enables required APIs, creates separate runtime and build identities, grants narrowly scoped runtime access, builds a container in Artifact Registry, and deploys `rewind-api` in `asia-east2`. The Gemini API uses its `global` location; this does not promise a particular data-processing location.

The runtime identity gets `roles/aiplatform.user`, `roles/serviceusage.serviceUsageConsumer`, and Secret Accessor on the invitation secret only (plus the optional OpenAI secret if configured). The build identity gets logs writer, source-object viewer, service usage consumer, and writer on the dedicated Artifact Registry repository. Standard synchronous TTS uses the attached ADC identity and enabled API; no downloaded service-account key is used. The person running deployment needs permission to create these resources and act as the service accounts. Organization policies may prevent public Cloud Run invocation or require an administrator to grant permissions; the script stops at an error.

Cloud Run configuration: Python 3.11, 1 vCPU, 1 GiB RAM, minimum 0 instances, maximum 1, concurrency 32, request timeout 300 seconds, CPU always allocated, session affinity enabled. `--no-cpu-throttling` is necessary because creator jobs continue between status polls. The service accepts public HTTP invocation but requires an application access code and bearer session before paid actions.

No cost estimate is asserted. CPU allocation, model calls, TTS, build/storage and network traffic can all incur charges; check the project's billing dashboard after a small test.

## 4. Connect the public player

After successful deployment, copy the printed HTTPS Cloud Run URL into `player/rewind-cloud.json` as `apiBase`. Use a bare origin with no trailing path. The public adapter reads this file; never put a secret in it.

Only the browser origin `https://cstemlab.github.io` is accepted. This is the GitHub account origin, not a repository path. A different custom domain must be reviewed and explicitly added in backend code before deployment.

The frontend agent owns the player and its release instructions. Publish the player and configuration only after the smoke checks below pass. No deployment command automatically publishes GitHub Pages.

## 5. Verify before sharing

- Visit `/health`: expect `{ "ok": true }`. This verifies the process, not provider credentials. Use `/health` for public Cloud Run requests; `/healthz` remains an internal compatibility alias only.
- Open the GitHub player, enter the invitation code, and confirm Google is displayed as the speech provider.
- Record a short Cantonese sentence; check actual coaching feedback, failure feedback and permission handling.
- Convert a short pasted script, review its text, generate its sample audio, and import the resulting session.
- Use two separate browser sessions. Neither session may see or cancel the other's recording or generation job.
- Try a wrong code and an expired session; confirm the frontend provides a clear reconnect path.
- Confirm no provider key appears in browser source, requests, storage or public GitHub files.
- Check billing and service errors after these tests. Do not call the service production-ready based only on offline tests.

## Session and capacity limits

This is a small invited demo, not a durable multi-user service. Up to 4 visitor sessions are retained. Each expires after 30 minutes idle or 2 hours absolute. Tokens are random bearer credentials; the access code is not a user identity. Ending a session cancels only that visitor's work. The server retains no source or audio files on disk; completed generation results are held in memory for 5 minutes and then discarded. Download a generated session promptly.

At most 1 creator job, 2 audio assessments and 1 document extraction run at once. Per-visitor and shared request limits bound bursts; they are not a currency budget. Each live session is separately owned and bounded by the existing 25-second limit. Result timestamps inside sentences remain estimated, as in the local player. Linux PDF extraction runs in a separate process with 256 MiB address-space and 10-second CPU ceilings, plus the existing 20-second wall timeout; exceeding a limit returns a safe import failure.

Sessions/jobs disappear after a restart, scale-to-zero or deployment. Cloud Run does not guarantee that an idle instance survives while a background job runs; active frontend polling keeps requests flowing, but this is still best effort. CPU always allocated permits work between polls; it does not provide durable job execution. A production service needs a shared session store, job queue, durable result storage, individual access controls and stronger abuse/billing limits before increasing the instance count. Maximum instance counts can also be briefly exceeded during infrastructure events; do not treat this setting as an exact financial cap.

## Local verification

```powershell
python .\verify.py
```

All hosted tests use mock providers and synthetic audio. They do not read a local Rewind key or call a paid provider. The copied audio modules and vendored pypdf/websocket libraries preserve their prior implementation; the hosted PDF worker adds Linux resource ceilings. Original library licenses remain in `service/vendor`.

Docker and gcloud were not available in the development agent's PATH when this package was prepared. Python tests and script parsing can run locally; container build and real cloud integration must be verified by the deployment steps, and have not been silently substituted with mocks.

## Official references checked

- [Cloud Run secrets and runtime identity](https://cloud.google.com/run/docs/configuring/services/secrets)
- [Cloud Run billing/CPU allocation](https://cloud.google.com/run/docs/configuring/billing-settings)
- [Cloud Run deployment flags](https://cloud.google.com/sdk/gcloud/reference/run/deploy)
- [Cloud Build user-specified service accounts](https://cloud.google.com/build/docs/securing-builds/configure-user-specified-service-accounts)
- [Cloud Text-to-Speech authentication](https://cloud.google.com/text-to-speech/docs/authentication)
