"""Optional explicitly invoked neutral-fixture check; no calls by default."""
import argparse
import json
import os
from pathlib import Path
import server
from assess import AssessmentError

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--audio', type=Path)
parser.add_argument('--text')
parser.add_argument('--provider', choices=server.SUPPORTED_PROVIDERS, default=server.PROVIDER)
parser.add_argument('--run-cloud', action='store_true', help='Send the named recording to the selected provider; may use service allowance.')
args = parser.parse_args()
server.PROVIDER = args.provider
server.API_KEY = os.environ.get('OPENAI_API_KEY' if args.provider == 'openai' else 'AZURE_SPEECH_KEY','').strip()
server.REGION = os.environ.get('AZURE_SPEECH_REGION','').strip().lower() if args.provider == 'azure' else ''
if not args.run_cloud:
    print(json.dumps({**server.status(), 'cloud_called':False},ensure_ascii=True))
elif args.audio is None or not args.text:
    parser.error('--audio and --text are required with --run-cloud')
else:
    try:
        if args.audio.stat().st_size > 820000:
            raise AssessmentError('audio_size','The selected WAV is too large.')
        result = server.assess_recording(args.audio.read_bytes(),args.text)
        print(json.dumps(result,ensure_ascii=True,allow_nan=False))
    except AssessmentError as exc:
        print(json.dumps({'error':exc.message,'code':exc.code},ensure_ascii=True))
        raise SystemExit(1)
    except OSError:
        print(json.dumps({'error':'The selected audio file could not be read.','code':'audio_unreadable'}))
        raise SystemExit(1)
