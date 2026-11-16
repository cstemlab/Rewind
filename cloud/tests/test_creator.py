import base64, io, json, struct, threading, time, unittest, wave
from unittest.mock import patch
import creator
from assess import AssessmentError

DRAFT={'title':'問候','text':'我今日去學校。','mode':'beginner'}
RAW={'sentences':[{'section':'問候','text':'我今日去學校。','readings':['ngo5','gam1','jat6','heoi3','hok6','haau6'],'parts':['我今日','去學校。']}]}

def wav(seconds=1,rate=24000):
    out=io.BytesIO()
    with wave.open(out,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(rate);w.writeframes(b'\0\0'*int(seconds*rate))
    return out.getvalue()

def reading_reply(text):
    return {'readings':{str(i):'zi6' for i,u in enumerate(creator.tokenize(text)) if creator.HAN.fullmatch(u['text'])}}

def raw_wav(payload,channels=1,rate=24000,bits=16,tag=1,riff_size=None,data_size=None,extra=b'',fmt_extra=b''):
    align=channels*bits//8;fmt=struct.pack('<HHIIHH',tag,channels,rate,rate*align,align,bits)+fmt_extra
    chunks=b'fmt '+struct.pack('<I',len(fmt))+fmt+extra+b'data'+struct.pack('<I',len(payload) if data_size is None else data_size)+payload
    if len(payload)%2:chunks+=b'\0'
    return b'RIFF'+struct.pack('<I',4+len(chunks) if riff_size is None else riff_size)+b'WAVE'+chunks

def wait_terminal(m,ident,generation=1):
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        r=m.status(ident,generation)
        if r['state'] not in ('queued','running'):return r
        time.sleep(.005)
    raise AssertionError('Job did not end')

class PlanTests(unittest.TestCase):
    def test_valid_partition_and_pinyin(self):
        plan=creator.validate_plan(RAW,DRAFT['text'])
        self.assertEqual(plan[0]['parts'],[(0,3),(3,7)])
        self.assertFalse(plan[0]['units'][-1]['spoken'])
    def test_wrong_tone_digit_rejected(self):
        raw=json.loads(json.dumps(RAW));raw['sentences'][0]['readings'][0]='ngo9'
        with self.assertRaises(AssessmentError):creator.validate_plan(raw,DRAFT['text'])
    def test_no_punctuation_only_phrase(self):
        raw=json.loads(json.dumps(RAW));raw['sentences'][0]['parts']=['我今日去學校','。']
        with self.assertRaises(AssessmentError):creator.validate_plan(raw,DRAFT['text'])
    def test_oversized_model_phrase_splits_at_clause_and_preserves_readings(self):
        text='我哋一齊學粵語，今日先練習簡單句子。'
        readings=['ngo5','dei6','jat1','cai4','hok6','jyut6','jyu5','gam1','jat6','sin1','lin6','zaap6','gaan2','daan1','geoi3','zi2']
        raw={'sentences':[{'section':'練習','text':text,'readings':readings,'parts':[text]}]}
        row=creator.validate_plan(raw,text)[0]
        self.assertEqual([''.join(u['text'] for u in row['units'][a:b]) for a,b in row['parts']],['我哋一齊學粵語，','今日先練習簡單句子。'])
        self.assertEqual([u['jyutping'] for u in row['units'] if u['jyutping']],readings)
        self.assertEqual([i for a,b in row['parts'] for i in range(a,b)],list(range(len(row['units']))))
    def test_oversized_unpunctuated_phrase_preserves_complete_latin_tokens(self):
        text='我今日同 New York 學校嘅老師一齊學習點樣使用 AI。'
        readings=['zi6']*sum(bool(creator.HAN.fullmatch(c)) for c in text)
        raw={'sentences':[{'section':'練習','text':text,'readings':readings,'parts':[text]}]}
        row=creator.validate_plan(raw,text)[0]
        self.assertGreater(len(row['parts']),1)
        self.assertEqual(''.join(u['text'] for a,b in row['parts'] for u in row['units'][a:b]),text)
        self.assertTrue(all(1<=sum(u['spoken'] for u in row['units'][a:b])<=10 for a,b in row['parts']))
        self.assertEqual([u['text'] for u in row['units'] if u['text'].isascii() and u['spoken']],['New','York','AI'])
    def test_model_phrase_boundary_inside_latin_word_still_rejected(self):
        raw={'sentences':[{'section':'Travel','text':'New York。','readings':[],'parts':['Ne','w York。']}]}
        with self.assertRaises(AssessmentError):creator.validate_plan(raw,'New York。')
    def test_latin_word_space_preserved(self):
        raw={'sentences':[{'section':'Travel','text':'NewYork。','readings':[],'parts':['NewYork。']}]}
        with self.assertRaises(AssessmentError):creator.validate_plan(raw,'New York。')
    def test_paragraph_space_can_change(self):
        self.assertEqual(creator.norm('我今日\n去學校。'),creator.norm(DRAFT['text']))
    def test_word_and_punctuation_changes_rejected(self):
        for text in ('我聽日去學校。','我今日去學校！'):
            with self.assertRaises(AssessmentError):creator.validate_plan(RAW,text)
    def test_strict_source_lengths(self):
        with self.assertRaises(AssessmentError):creator.clean_text('字'*12001)
        with self.assertRaises(AssessmentError):creator.validate_draft({**DRAFT,'text':'字'*6001})
    def test_session_metadata_and_times(self):
        plan=creator.validate_plan(RAW,DRAFT['text']);pcm,rate=creator.read_wav(wav(1))
        s=creator.assemble_session(DRAFT,plan,[{'pcm':pcm,'rate':rate}])
        self.assertEqual(s['title'],'問候');self.assertTrue(s['source']['ai_voice'])
        self.assertEqual(s['sentences'][0]['start'],0);self.assertEqual(s['sentences'][0]['end'],1)
        self.assertEqual(s['source']['reviewed_text'],DRAFT['text'])
        self.assertTrue(all(u['timing_precision']=='estimated-within-sentence' for u in s['units']))
        with wave.open(io.BytesIO(base64.b64decode(s['audio']['base64'])),'rb') as f:self.assertEqual(f.getnframes(),24000)
    def test_audio_transcript_mismatch_rejected(self):
        raw={'choices':[{'finish_reason':'stop','message':{'audio':{'transcript':'我聽日去學校。','data':base64.b64encode(wav()).decode()}}}]}
        with patch('creator._request',return_value=raw), self.assertRaises(AssessmentError):creator.narration(DRAFT['text'],'test-key')
    def test_audio_request_is_fixed_and_no_store(self):
        raw={'choices':[{'finish_reason':'stop','message':{'audio':{'transcript':DRAFT['text'],'data':base64.b64encode(wav()).decode()}}}]}
        with patch('creator._request',return_value=raw) as request:
            result=creator.narration(DRAFT['text'],'test-key')
            payload=request.call_args.args[0]
            self.assertEqual(payload['model'],'gpt-audio-1.5');self.assertFalse(payload['store']);self.assertEqual(result['rate'],24000)
    def test_authoritative_source_keeps_spaces_numbers_paragraphs_and_punctuation(self):
        text='早晨。\n\n我哋同 New York 嘅12間學校合作。工作坊暫定喺12月3日，但日期仲未確認。'
        with patch('creator._json_completion',return_value=reading_reply(text)) as cloud:
            rows=creator.plan_script({**DRAFT,'text':text},'test-key')
        self.assertEqual(''.join(row['text'] for row in rows),text)
        self.assertEqual(cloud.call_count,1)
        self.assertTrue(all(1<=sum(u['spoken'] for u in row['units'][a:b])<=10 for row in rows for a,b in row['parts']))
        self.assertEqual(''.join(u['text'] for row in rows for u in row['units']),text)
    def test_model_rewritten_text_cannot_become_practice_text(self):
        with patch('creator._json_completion',side_effect=[{'text':'我明日去學校。'},reading_reply(DRAFT['text'])]) as cloud:
            rows=creator.plan_script(DRAFT,'test-key')
        self.assertEqual(''.join(row['text'] for row in rows),DRAFT['text']);self.assertEqual(cloud.call_count,2)
        self.assertEqual(cloud.call_args.args[1]['invalid_ids'],['format'])
    def test_reading_repair_is_bounded_and_preserves_no_invalid_annotation(self):
        for reply in ({'readings':{}},{'readings':{'0':'ngo9'}},{'readings':{**reading_reply(DRAFT['text'])['readings'],'999':'ngo5'}}):
            with self.subTest(reply=reply),patch('creator._json_completion',return_value=reply) as cloud:
                with self.assertRaises(AssessmentError):creator.plan_script(DRAFT,'test-key')
                self.assertEqual(cloud.call_count,2)
    def test_id_only_sense_hints_preserve_source_and_ignore_invalid_hints(self):
        reply=reading_reply(DRAFT['text']);reply['break_after']=['2','999','not an id']
        with patch('creator._json_completion',return_value=reply):rows=creator.plan_script(DRAFT,'test-key')
        self.assertEqual(rows[0]['parts'],[(0,3),(3,7)])
        self.assertEqual(''.join(u['text'] for a,b in rows[0]['parts'] for u in rows[0]['units'][a:b]),DRAFT['text'])
    def test_cancel_before_repair_prevents_second_request(self):
        checks=[]
        def check():
            checks.append(1)
            if len(checks)==2:raise AssessmentError('creator_cancelled','cancelled')
        with patch('creator._json_completion',return_value={'readings':{}}) as cloud:
            with self.assertRaises(AssessmentError):creator.plan_script(DRAFT,'test-key',check)
            self.assertEqual(cloud.call_count,1)
    def test_no_han_draft_needs_no_reading_request(self):
        with patch('creator._json_completion') as cloud:
            rows=creator.plan_script({**DRAFT,'text':'AI 12.5. New York.'},'test-key')
        cloud.assert_not_called();self.assertEqual(''.join(r['text'] for r in rows),'AI 12.5. New York.')
        self.assertIn('12.5',[u['text'] for row in rows for u in row['units']])
    def test_long_source_is_partitioned_locally_with_sentence_and_phrase_caps(self):
        text='學'*350+'。'
        with patch('creator._json_completion',return_value=reading_reply(text)):
            rows=creator.plan_script({**DRAFT,'text':text},'test-key')
        self.assertEqual(len(rows),3);self.assertEqual(''.join(r['text'] for r in rows),text)
        self.assertTrue(all(sum(u['spoken'] for u in row['units'])<=150 for row in rows))
    def test_sentence_limit_is_checked_before_cloud(self):
        with patch('creator._json_completion') as cloud:
            with self.assertRaises(AssessmentError):creator.plan_script({**DRAFT,'text':'學。'*101},'test-key')
        cloud.assert_not_called()
    def test_numeric_transcript_equivalence_is_narrow(self):
        for expected,actual in [('12間學校','十二間學校'),('12月3日','十二月三日'),('2027年','二零二七年'),('1,203個','一千二百零三個'),('-12.5','負十二點五'),('001號','零零一號')]:
            with self.subTest(expected=expected):self.assertEqual(creator.transcript_tokens(expected),creator.transcript_tokens(actual))
        for expected,actual in [('12間學校','十三間學校'),('12月3日','十二月四日'),('-12','12'),('1.5','15'),('001','1'),('12/3','123'),('12/3','12 3'),('3.5%','3.5'),('$12','12'),('12+3','12 3'),('New York','NewYork'),('我今日去','我聽日去'),('120','一百二')]:
            with self.subTest(expected=expected):self.assertNotEqual(creator.transcript_tokens(expected),creator.transcript_tokens(actual))

class AudioDecodeTests(unittest.TestCase):
    def test_streaming_unknown_lengths_use_actual_pcm_duration(self):
        payload=struct.pack('<h',1024)*6000
        for sentinel in (0,0xffffffff,0x7fffffff):
            with self.subTest(sentinel=sentinel):
                pcm,rate=creator.read_wav(raw_wav(payload,riff_size=sentinel,data_size=sentinel))
                self.assertEqual(pcm,payload);self.assertEqual(len(pcm)/2/rate,.25)
    def test_stereo_integer_downmix_is_measured_and_bounded(self):
        pcm,rate=creator.read_wav(raw_wav(struct.pack('<hh',1000,3000)*6000,channels=2))
        self.assertEqual(rate,24000);self.assertEqual(pcm,struct.pack('<h',2000)*6000)
    def test_24_bit_pcm_and_unsigned8_convert_to_pcm16(self):
        value=(1<<22).to_bytes(3,'little',signed=True)
        pcm,_=creator.read_wav(raw_wav(value*6000,bits=24))
        self.assertEqual(pcm,struct.pack('<h',16384)*6000)
        pcm,_=creator.read_wav(raw_wav(bytes([128,192])*3000,bits=8))
        self.assertEqual(pcm,struct.pack('<hh',0,16384)*3000)
    def test_float_stereo_and_extensible_pcm(self):
        pcm,_=creator.read_wav(raw_wav(struct.pack('<ff',.25,.75)*6000,channels=2,bits=32,tag=3))
        self.assertEqual(pcm,struct.pack('<h',16384)*6000)
        extension=struct.pack('<HHI',22,16,1)+struct.pack('<I',1)+bytes.fromhex('00001000800000aa00389b71')
        payload=struct.pack('<h',1234)*6000
        self.assertEqual(creator.read_wav(raw_wav(payload,tag=0xfffe,fmt_extra=extension))[0],payload)
    def test_ancillary_chunk_padding_is_not_audio(self):
        extra=b'JUNK'+struct.pack('<I',3)+b'abc\0';payload=b'\0\0'*6000
        self.assertEqual(creator.read_wav(raw_wav(payload,extra=extra))[0],payload)
    def test_ordinary_truncation_understatement_and_partial_frames_rejected(self):
        payload=b'\0\0'*6000
        for data in (raw_wav(payload,data_size=len(payload)+100),raw_wav(payload,data_size=len(payload)-100),raw_wav(payload,riff_size=100),raw_wav(payload+b'\0')):
            with self.assertRaises(AssessmentError):creator.read_wav(data)
    def test_unsupported_format_empty_nonfinite_and_duration_rejected(self):
        cases=[raw_wav(b'\0'*24000,channels=4),raw_wav(b'\0\0'*6000,rate=33333),raw_wav(b'\0\0'*6000,tag=6),raw_wav(b''),raw_wav(struct.pack('<f',float('nan'))*6000,bits=32,tag=3),raw_wav(b'\0\0'*(24000*91))]
        for data in cases:
            with self.assertRaises(AssessmentError):creator.read_wav(data)
    def test_diagnostic_contains_safe_format_fields_only(self):
        with self.assertRaises(AssessmentError) as error:creator.read_wav(raw_wav(b'\0\0'*6000,rate=33333))
        message=error.exception.message
        self.assertIn('channels=1',message);self.assertIn('rate=33333',message);self.assertIn('bits=16',message)

class JobTests(unittest.TestCase):
    def test_render_recovers_oversized_model_parts_without_rewriting_or_extra_audio_calls(self):
        text='我哋一齊學粵語，今日先練習簡單句子。'
        raw=reading_reply(text)
        draft={**DRAFT,'text':text};calls=[]
        def synth(spoken,key):calls.append(spoken);return {'pcm':b'\0\0'*48000,'rate':24000}
        with patch('creator._json_completion',return_value=raw):
            m=creator.CreatorManager(synthesizer=synth)
            start=m.start('render',{'draft':draft,'consent':True},'test-key',1)
            end=wait_terminal(m,start['job_id'])
        self.assertEqual(end['state'],'completed')
        s=end['result']['session'];self.assertEqual(calls,[text]);self.assertEqual(len(s['phrases']),2)
        self.assertEqual(s['sentences'][0]['end'],2);self.assertEqual(s['source']['reviewed_text'],text)
        self.assertEqual(''.join(p['text'] for p in s['phrases']),text)
    def test_completed_translation(self):
        m=creator.CreatorManager(translator=lambda *args:DRAFT)
        start=m.start('translate',{'text':'I go to school today.','title':'Hello','mode':'beginner','consent':True},'test-key',1)
        end=wait_terminal(m,start['job_id']);self.assertEqual(end['result']['draft'],DRAFT)
        self.assertNotIn('key',json.dumps(end));self.assertNotIn('test-key',json.dumps(end))
    def test_missing_consent_does_not_call(self):
        calls=[];m=creator.CreatorManager(translator=lambda *a:calls.append(a))
        with self.assertRaises(AssessmentError):m.start('translate',{'text':'Hello','mode':'faithful'},'test-key',1)
        self.assertEqual(calls,[])
    def test_cancel_inflight_discards_and_blocks_followups(self):
        entered=threading.Event();release=threading.Event();calls=[]
        plan=creator.validate_plan(RAW,DRAFT['text'])*2
        def synth(*a):entered.set();release.wait(2);calls.append(1);return {'pcm':b'\0\0'*24000,'rate':24000}
        m=creator.CreatorManager(planner=lambda *a:plan,synthesizer=synth)
        start=m.start('render',{'draft':DRAFT,'consent':True},'test-key',1)
        self.assertTrue(entered.wait(2));m.cancel(start['job_id'],1);release.set()
        time.sleep(.03);end=m.status(start['job_id'],1)
        self.assertEqual(end['state'],'cancelled');self.assertNotIn('result',end);self.assertEqual(calls,[1])
    def test_one_active_job(self):
        entered=threading.Event();release=threading.Event()
        def translate(*a):entered.set();release.wait(2);return DRAFT
        m=creator.CreatorManager(translator=translate)
        body={'text':'Hello','mode':'faithful','consent':True}
        first=m.start('translate',body,'test-key',1);self.assertTrue(entered.wait(2))
        try:
            with self.assertRaises(AssessmentError):m.start('translate',body,'test-key',1)
        finally:m.cancel(first['job_id'],1);release.set()
    def test_generation_boundaries(self):
        m=creator.CreatorManager(translator=lambda *a:DRAFT)
        start=m.start('translate',{'text':'Hello','mode':'faithful','consent':True},'test-key',2)
        with self.assertRaises(AssessmentError):m.status(start['job_id'],3)
        with self.assertRaises(AssessmentError):m.cancel(start['job_id'],3)
    def test_failed_provider_does_not_leak_exception(self):
        def broken(*a):raise RuntimeError('SECRET provider raw failure')
        m=creator.CreatorManager(translator=broken)
        start=m.start('translate',{'text':'Hello','mode':'faithful','consent':True},'test-key',1)
        end=wait_terminal(m,start['job_id']);self.assertEqual(end['state'],'failed');self.assertNotIn('SECRET',json.dumps(end))
    def test_unknown_job_rejected(self):
        with self.assertRaises(AssessmentError):creator.CreatorManager().status('missing',1)

if __name__=='__main__':unittest.main()
