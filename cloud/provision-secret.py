"""Owner-run only: prompt privately and send a secret to gcloud via stdin.

No secret appears in arguments, stdout, a temporary file or a repository.
Run gcloud auth login first. This script does not inspect any existing key.
"""
import argparse
import getpass
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', required=True)
    parser.add_argument('--name', choices=('rewind-demo-access', 'rewind-openai-key'), required=True)
    args = parser.parse_args()
    gcloud = shutil.which('gcloud')
    if not gcloud:
        raise SystemExit('Install Google Cloud CLI and run gcloud auth login first.')
    base = [gcloud, '--project=' + args.project, '--quiet']
    check = subprocess.run(base + ['secrets', 'list', '--filter=name:' + args.name, '--format=value(name)'],
        stdout=subprocess.PIPE, check=True, text=True)
    names = [line.strip().split('/')[-1] for line in check.stdout.splitlines()]
    if args.name not in names:
        subprocess.run(base + ['secrets', 'create', args.name, '--replication-policy=automatic'], check=True)
    value = getpass.getpass('Secret value (hidden): ').strip()
    confirmation = getpass.getpass('Repeat value (hidden): ').strip()
    if value != confirmation:
        raise SystemExit('Values did not match. Nothing was stored.')
    if not value or (args.name == 'rewind-demo-access' and not 20 <= len(value) <= 200):
        raise SystemExit('The demo access code must contain 20 to 200 characters.')
    subprocess.run(base + ['secrets', 'versions', 'add', args.name, '--data-file=-'], input=value.encode('utf-8'), check=True)
    value = confirmation = ''
    print('Stored a new Secret Manager version. Use its numeric version in deploy.ps1.')


if __name__ == '__main__':
    main()
