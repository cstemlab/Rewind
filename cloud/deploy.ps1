<# Owner-run deployment. No API key or access code is accepted as an argument.
   Requires billing, Google Cloud CLI login, and a provisioned access-code secret.
   This file is prepared only; it has not been executed against a cloud project.
#>
[CmdletBinding()]
param(
    [ValidatePattern('^[a-z][a-z0-9-]{4,61}[a-z0-9]$')][string]$ProjectId = 'rewind-514904',
    [ValidatePattern('^[a-z]+-[a-z]+[0-9]$')][string]$Region = 'asia-east2',
    [ValidatePattern('^[a-z][a-z0-9-]{0,48}$')][string]$Service = 'rewind-api',
    [Parameter(Mandatory)][ValidatePattern('^[1-9][0-9]*$')][string]$AccessSecretVersion,
    [ValidateSet('gemini', 'openai')][string]$Provider = 'gemini',
    [ValidatePattern('^([1-9][0-9]*)?$')][string]$OpenAISecretVersion = ''
)
$ErrorActionPreference = 'Stop'
Get-Command gcloud -ErrorAction Stop | Out-Null

function Invoke-RewindCloud {
    param([string[]]$Arguments)
    & gcloud @Arguments --project=$ProjectId --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Google Cloud command failed. Deployment stopped; inspect the error above.' }
}

if ($Provider -eq 'openai' -and !$OpenAISecretVersion) { throw 'OpenAISecretVersion is required for the optional OpenAI provider.' }
$runtimeName = 'rewind-runtime'
$buildName = 'rewind-build'
$runtimeAccount = "$runtimeName@$ProjectId.iam.gserviceaccount.com"
$buildAccount = "$buildName@$ProjectId.iam.gserviceaccount.com"
$repository = 'rewind'
$tag = (Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmss')
$imageName = "$Region-docker.pkg.dev/$ProjectId/$repository/${Service}:$tag"

Invoke-RewindCloud -Arguments @('services', 'enable', 'run.googleapis.com', 'cloudbuild.googleapis.com', 'artifactregistry.googleapis.com', 'secretmanager.googleapis.com', 'iam.googleapis.com', 'serviceusage.googleapis.com', 'aiplatform.googleapis.com', 'texttospeech.googleapis.com')
$accounts = @(& gcloud iam service-accounts list --project=$ProjectId --format='value(email)')
if ($LASTEXITCODE -ne 0) { throw 'Cannot list service accounts.' }
foreach ($accountName in @($runtimeName, $buildName)) {
    if ($accounts -notcontains "$accountName@$ProjectId.iam.gserviceaccount.com") {
        Invoke-RewindCloud -Arguments @('iam', 'service-accounts', 'create', $accountName, "--display-name=$accountName")
    }
}

# Runtime access is attached identity (ADC); no downloaded service-account key.
foreach ($role in @('roles/aiplatform.user', 'roles/serviceusage.serviceUsageConsumer')) {
    Invoke-RewindCloud -Arguments @('projects', 'add-iam-policy-binding', $ProjectId, "--member=serviceAccount:$runtimeAccount", "--role=$role", '--condition=None')
}
foreach ($role in @('roles/logging.logWriter', 'roles/storage.objectViewer', 'roles/serviceusage.serviceUsageConsumer')) {
    Invoke-RewindCloud -Arguments @('projects', 'add-iam-policy-binding', $ProjectId, "--member=serviceAccount:$buildAccount", "--role=$role", '--condition=None')
}
$repositories = @(& gcloud artifacts repositories list --location=$Region --project=$ProjectId --format='value(name)')
if ($LASTEXITCODE -ne 0) { throw 'Cannot list Artifact Registry repositories.' }
if (!($repositories | Where-Object { ($_ -split '/')[-1] -eq $repository })) {
    Invoke-RewindCloud -Arguments @('artifacts', 'repositories', 'create', $repository, '--repository-format=docker', "--location=$Region")
}
Invoke-RewindCloud -Arguments @('artifacts', 'repositories', 'add-iam-policy-binding', $repository, "--location=$Region", "--member=serviceAccount:$buildAccount", '--role=roles/artifactregistry.writer')

$secretRefs = "REWIND_ACCESS_CODE=rewind-demo-access:$AccessSecretVersion"
$requiredSecrets = @('rewind-demo-access')
Invoke-RewindCloud -Arguments @('secrets', 'versions', 'describe', $AccessSecretVersion, '--secret=rewind-demo-access', '--format=value(state)')
if ($OpenAISecretVersion) {
    $requiredSecrets += 'rewind-openai-key'
    $secretRefs += ",OPENAI_API_KEY=rewind-openai-key:$OpenAISecretVersion"
    Invoke-RewindCloud -Arguments @('secrets', 'versions', 'describe', $OpenAISecretVersion, '--secret=rewind-openai-key', '--format=value(state)')
}
foreach ($secretName in $requiredSecrets) {
    Invoke-RewindCloud -Arguments @('secrets', 'add-iam-policy-binding', $secretName, "--member=serviceAccount:$runtimeAccount", '--role=roles/secretmanager.secretAccessor')
}

Invoke-RewindCloud -Arguments @('builds', 'submit', $PSScriptRoot, "--config=$PSScriptRoot/cloudbuild.yaml", "--ignore-file=$PSScriptRoot/.gcloudignore", "--region=$Region", "--service-account=projects/$ProjectId/serviceAccounts/$buildAccount", "--substitutions=_IMAGE=$imageName")
Invoke-RewindCloud -Arguments @('run', 'deploy', $Service, "--image=$imageName", "--region=$Region", "--service-account=$runtimeAccount", '--allow-unauthenticated', '--ingress=all', '--cpu=1', '--memory=1Gi', '--concurrency=32', '--timeout=300', '--min=0', '--max=1', '--min-instances=0', '--max-instances=1', '--no-cpu-throttling', '--session-affinity', '--execution-environment=gen2', '--port=8080', '--startup-probe=httpGet.path=/health,httpGet.port=8080,initialDelaySeconds=0,timeoutSeconds=3,periodSeconds=5,failureThreshold=12', "--set-env-vars=REWIND_SPEECH_PROVIDER=$Provider,GOOGLE_CLOUD_PROJECT=$ProjectId,GOOGLE_CLOUD_LOCATION=global", "--set-secrets=$secretRefs")
Invoke-RewindCloud -Arguments @('run', 'services', 'describe', $Service, "--region=$Region", '--format=value(status.url)')
Write-Host 'Backend deployed. Verify the service, then put its HTTPS URL in player/rewind-cloud.json. The frontend is not automatically published by this script.'
