#!/usr/bin/env bash
# Cloud Shell phase 2. Owner runs after preparation and private secret provisioning.
# Variables contain IDs/versions only, NEVER the actual invitation or API key.
set -euo pipefail
project="${PROJECT_ID:-rewind-514904}"
region="${REGION:-asia-east2}"
service="${SERVICE_NAME:-rewind-api}"
access_version="${ACCESS_SECRET_VERSION:-1}"
openai_version="${OPENAI_SECRET_VERSION:-}"
provider="${DEFAULT_PROVIDER:-gemini}"
[[ "$project" =~ ^[a-z][a-z0-9-]{4,61}[a-z0-9]$ && "$region" =~ ^[a-z]+-[a-z]+[0-9]$ && "$service" =~ ^[a-z][a-z0-9-]{0,48}$ ]] || { echo 'Invalid resource name.' >&2; exit 1; }
[[ "$access_version" =~ ^[1-9][0-9]*$ && ( -z "$openai_version" || "$openai_version" =~ ^[1-9][0-9]*$ ) ]] || { echo 'Numeric secret versions required.' >&2; exit 1; }
[[ "$provider" == gemini || "$provider" == openai ]] || { echo 'Invalid provider.' >&2; exit 1; }
[[ "$provider" != openai || -n "$openai_version" ]] || { echo 'OpenAI requires its separately provisioned secret version.' >&2; exit 1; }
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
gc() { gcloud "$@" --project="$project" --quiet; }
runtime="rewind-runtime@$project.iam.gserviceaccount.com"
builder="rewind-build@$project.iam.gserviceaccount.com"
image="$region-docker.pkg.dev/$project/rewind/$service:$(date -u +%Y%m%d-%H%M%S)"
state="$(gc secrets versions describe "$access_version" --secret=rewind-demo-access --format='value(state)')"
[[ "$state" == ENABLED ]] || { echo 'Invitation secret version is not enabled.' >&2; exit 1; }
secret_refs="REWIND_ACCESS_CODE=rewind-demo-access:$access_version"
if [[ -n "$openai_version" ]]; then
  state="$(gc secrets versions describe "$openai_version" --secret=rewind-openai-key --format='value(state)')"
  [[ "$state" == ENABLED ]] || { echo 'OpenAI secret version is not enabled.' >&2; exit 1; }
  gc secrets add-iam-policy-binding rewind-openai-key --member="serviceAccount:$runtime" --role=roles/secretmanager.secretAccessor >/dev/null
  secret_refs+=",OPENAI_API_KEY=rewind-openai-key:$openai_version"
fi
gc builds submit . --config=cloudbuild.yaml --ignore-file=.gcloudignore --region="$region" --service-account="projects/$project/serviceAccounts/$builder" --substitutions="_IMAGE=$image"
gc run deploy "$service" --image="$image" --region="$region" --service-account="$runtime" \
  --allow-unauthenticated --ingress=all --cpu=1 --memory=1Gi --concurrency=32 --timeout=300 \
  --min=0 --max=1 --min-instances=0 --max-instances=1 --no-cpu-throttling --session-affinity \
  --execution-environment=gen2 --port=8080 \
  --startup-probe='httpGet.path=/health,httpGet.port=8080,initialDelaySeconds=0,timeoutSeconds=3,periodSeconds=5,failureThreshold=12' \
  --set-env-vars="REWIND_SPEECH_PROVIDER=$provider,GOOGLE_CLOUD_PROJECT=$project,GOOGLE_CLOUD_LOCATION=global" \
  --set-secrets="$secret_refs"
gc run services describe "$service" --region="$region" --format='value(status.url)'
echo 'Verify this service before adding its URL to the GitHub player configuration.'
