"""Explicit paid live smoke: one Cantonese TTS clip and one live connection.

Uses attached Cloud ADC. No human audio, files, keys or request headers logged.
This checks interim recognition while sending synthetic audio, not pronunciation.
"""
import argparse
import json
import time
from assess import AssessmentError
from google_provider import GoogleProvider
from google_live import GoogleLiveManager


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', default='rewind-514904')
    parser.add_argument('--location', default='global')
    args = parser.parse_args()
    report = {'provider': 'gemini', 'test': 'synthetic-live-transcription',
              'pronunciation_assessed': False, 'progress_before_stop': 0}
    manager = GoogleLiveManager(args.project, location=args.location)
    cursor = 0
    events = []
    protocol = []
    session = None
    try:
        clip = GoogleProvider(project=args.project).narrate('早晨，我今日想同大家一齊練習廣東話。我會慢慢講，聽完再試一次。')
        if clip['rate'] != 24000:
            raise AssessmentError('test_rate', '測試聲音不是 24 kHz。')
        info = manager.start(None, 0)
        session = manager.get(info['session_id'], 0)
        original_handler = session.handle_event
        def observe(event):
            content = event.get('serverContent', event.get('server_content', {}))
            if isinstance(content, dict) and len(protocol) < 80:
                brief = {'keys': sorted(content), 'state_before': session.state}
                for key in ('inputTranscription', 'input_transcription', 'interimInputTranscription', 'interim_input_transcription'):
                    part = content.get(key)
                    if isinstance(part, dict):
                        brief[key] = {'text_chars': len(part.get('text', '')), 'finished': part.get('finished', 'absent')}
                for key in ('turnComplete', 'turn_complete', 'interactionStatus', 'interaction_status'):
                    if key in content:
                        brief[key] = content[key]
                protocol.append(brief)
            original_handler(event)
        session.handle_event = observe
        report['model'] = info['model']
        report['audio_seconds'] = round(len(clip['pcm']) / 48000, 3)
        started = time.monotonic()
        for seq, offset in enumerate(range(0, len(clip['pcm']), 9600)):
            session.append(seq, clip['pcm'][offset:offset+9600])
            due = started + min(offset + 9600, len(clip['pcm'])) / 48000
            time.sleep(max(0, due - time.monotonic()))
            snapshot = session.events(cursor)
            cursor = snapshot['last_seq']
            for event in snapshot['events']:
                if event['type'] == 'transcript':
                    report['progress_before_stop'] += 1
                    events.append({'text': event['text'], 'final': event['final'], 'before_stop': True})
                elif event['type'] == 'error':
                    raise AssessmentError(event['code'], event['message'])
        session.stop(True)
        deadline = time.monotonic() + 14
        while time.monotonic() < deadline:
            snapshot = session.events(cursor)
            cursor = snapshot['last_seq']
            for event in snapshot['events']:
                if event['type'] == 'transcript':
                    events.append({'text': event['text'], 'final': event['final'], 'before_stop': False})
                elif event['type'] == 'error':
                    raise AssessmentError(event['code'], event['message'])
            if snapshot['state'] in ('closed', 'error'):
                break
            time.sleep(.2)
        report['events'] = events
        report['final_text'] = events[-1]['text'] if events else ''
        report['status'] = 'passed' if report['progress_before_stop'] and any(e['final'] for e in events) else 'incomplete'
    except AssessmentError as exc:
        report.update(status='failed', error={'code': exc.code, 'message': exc.message})
    finally:
        report['events'] = events
        report['protocol'] = protocol
        if session:
            report['state'] = session.state
            report['last_recognized_text'] = session._text
        manager.cancel()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
