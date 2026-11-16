#!/usr/bin/env bash
# Cloud Shell phase 1. Default is a readable plan; pass --apply to make changes.
set -euo pipefail
project="${PROJECT_ID:-rewind-514904}"
region="${REGION:-asia-east2}"
[[ "$project" =~ ^[a-z][a-z0-9-]{4,61}[a-z0-9]$ ]] || { echo 'Invalid project ID.' >&2; exit 1; }
[[ "$region" =~ ^[a-z]+-[a-z]+[0-9]$ ]] || { echo 'Invalid region.' >&2; exit 1; }
runtime="rewind-runtime@$project.iam.gserviceaccount.com"
builder="rewind-build@$project.iam.gserviceaccount.com"
cat <<PLAN
Project: $project
Region: $region
Enable APIs: Cloud Run, Cloud Build, Artifact Registry, Secret Manager, IAM,
Service Usage, Vertex AI, Text-to-Speech.
Create service accounts: $runtime and $builder
Runtime project roles: roles/aiplatform.user, roles/serviceusage.serviceUsageConsumer
Build project roles: roles/logging.logWriter, roles/storage.objectViewer,
roles/serviceusage.serviceUsageConsumer
Create Docker repository: $region/rewind
Grant build identity roles/artifactregistry.writer on that repository only.
Create an EMPTY rewind-demo-access secret if it does not exist.
Grant runtime roles/secretmanager.secretAccessor on that secret only.
No secret value is read or written; no service is deployed by this stage.
PLAN
[[ "${1:-}" == '--apply' ]] || { echo 'Review the plan, then run: bash prepare-cloud.sh --apply'; exit 0; }
gc() { gcloud "$@" --project="$project" --quiet; }
gc services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com iam.googleapis.com serviceusage.googleapis.com aiplatform.googleapis.com texttospeech.googleapis.com
accounts="$(gc iam service-accounts list --format='value(email)')"
for name in rewind-runtime rewind-build; do
  if ! printf '%s\n' "$accounts" | grep -Fxq "$name@$project.iam.gserviceaccount.com"; then
    gc iam service-accounts create "$name" --display-name="$name"
  fi
done
for role in roles/aiplatform.user roles/serviceusage.serviceUsageConsumer; do
  gc projects add-iam-policy-binding "$project" --member="serviceAccount:$runtime" --role="$role" --condition=None >/dev/null
done
for role in roles/logging.logWriter roles/storage.objectViewer roles/serviceusage.serviceUsageConsumer; do
  gc projects add-iam-policy-binding "$project" --member="serviceAccount:$builder" --role="$role" --condition=None >/dev/null
done
repositories="$(gc artifacts repositories list --location="$region" --format='value(name)')"
if ! printf '%s\n' "$repositories" | grep -Eq '(^|/)rewind$'; then
  gc artifacts repositories create rewind --repository-format=docker --location="$region"
fi
gc artifacts repositories add-iam-policy-binding rewind --location="$region" --member="serviceAccount:$builder" --role=roles/artifactregistry.writer >/dev/null
secret_names="$(gc secrets list --format='value(name)')"
if ! printf '%s\n' "$secret_names" | grep -Eq '(^|/)rewind-demo-access$'; then
  gc secrets create rewind-demo-access --replication-policy=automatic
fi
gc secrets add-iam-policy-binding rewind-demo-access --member="serviceAccount:$runtime" --role=roles/secretmanager.secretAccessor >/dev/null
echo 'Preparation complete. Owner can now provision the invitation secret privately.'
