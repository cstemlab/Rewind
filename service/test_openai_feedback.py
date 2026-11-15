import base64
import io
import json
import unittest
import urllib.error
from unittest.mock import patch
import openai_feedback as module
from assess import AssessmentError
from test_azure_feedback import wav


def model_reply(groups=None,language='cantonese',heard='聽日'):
    payload={'heard_language':language,'heard_text':heard,'groups':groups if groups is not None else [
        {'text':'聽日','start':0,'end':2,'state':'pass','reason':'讀音聽起來接近。'}]}
    return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(payload,ensure_ascii=False)}}]}


class OpenAIValidationTests(unittest.TestCase):
    def test_valid_direct_audio_coaching_has_no_numeric_score(self):
        result=module.normalize_openai(model_reply(),'聽日')
        self.assertEqual(result['provider'],'openai')
        self.assertEqual(result['assessment_kind'],'audio-coaching')
        self.assertTrue(result['experimental'])
        self.assertEqual(result['groups'][0]['state'],'pass')
        self.assertIsNone(result['groups'][0]['score'])
        self.assertIsNone(result['overall']['accuracy'])
        self.assertEqual(result['cloud_requests'],1)
        self.assertEqual(result['crosscheck']['status'],'unavailable')
        self.assertFalse(result['lexical_tone_validated'])

    def test_mandarin_language_cannot_receive_cantonese_pass(self):
        result=module.normalize_openai(model_reply(language='mandarin',heard='明日'),'聽日')
        self.assertEqual(result['groups'][0]['state'],'retry')

    def test_unknown_language_is_neutral(self):
        result=module.normalize_openai(model_reply(language='unknown'),'聽日')
        self.assertEqual(result['groups'][0]['state'],'uncertain')

    def test_empty_heard_text_cannot_pass(self):
        result=module.normalize_openai(model_reply(heard=''),'聽日')
        self.assertEqual(result['groups'][0]['state'],'uncertain')

    def test_no_speech_has_no_groups(self):
        result=module.normalize_openai(model_reply(language='no_speech',heard=''),'聽日')
        self.assertEqual(result['status'],'no_speech'); self.assertEqual(result['groups'],[])

    def test_bad_mapping_is_whole_reference_neutral(self):
        for group in [
            {'text':'明日','start':0,'end':2,'state':'pass','reason':''},
            {'text':'聽日','start':True,'end':2,'state':'pass','reason':''},
            {'text':'聽日','start':0,'end':5,'state':'pass','reason':''},
        ]:
            with self.subTest(group=group):
                result=module.normalize_openai(model_reply([group]),'聽日')
                self.assertEqual(result['groups'][0]['state'],'uncertain')
                self.assertEqual(result['mapping_status'],'unavailable')

    def test_overlapping_groups_cannot_pass(self):
        groups=[{'text':'聽日','start':0,'end':2,'state':'pass','reason':''},
                {'text':'日','start':1,'end':2,'state':'pass','reason':''}]
        result=module.normalize_openai(model_reply(groups),'聽日')
        self.assertEqual(len(result['groups']),1)
        self.assertEqual(result['groups'][0]['state'],'uncertain')

    def test_uncovered_span_is_neutral(self):
        group={'text':'日','start':1,'end':2,'state':'pass','reason':''}
        result=module.normalize_openai(model_reply([group]),'聽日')
        self.assertEqual([g['state'] for g in result['groups']],['uncertain','pass'])
        self.assertEqual(result['groups'][0]['text'],'聽')

    def test_punctuation_gaps_and_groups_do_not_count_as_practice_words(self):
        groups=[{'text':'我','start':0,'end':1,'state':'pass','reason':''},
                {'text':'買書','start':2,'end':4,'state':'pass','reason':''},
                {'text':'。','start':4,'end':5,'state':'pass','reason':''}]
        result=module.normalize_openai(model_reply(groups,heard='我買書'),'我，買書。')
        self.assertEqual([g['text'] for g in result['groups']],['我','買書'])

    def test_unicode_codepoint_offsets(self):
        group={'text':'聽日','start':2,'end':4,'state':'retry','reason':'再練一次。'}
        result=module.normalize_openai(model_reply([group]),'𠮷，聽日')
        self.assertEqual((result['groups'][1]['start'],result['groups'][1]['end']),(2,4))

    def test_scores_and_unknown_fields_are_rejected(self):
        group={'text':'聽日','start':0,'end':2,'state':'pass','reason':'','score':98}
        with self.assertRaises(AssessmentError): module.normalize_openai(model_reply([group]),'聽日')

    def test_fenced_json_or_code_is_not_evaluated(self):
        raw=model_reply()
        raw['choices'][0]['message']['content']='```json\n'+raw['choices'][0]['message']['content']+'\n```'
        with self.assertRaises(AssessmentError): module.normalize_openai(raw,'聽日')

    def test_truncation_refusal_and_tool_calls_are_not_assessments(self):
        for mutation in ['length','refusal','tool_calls']:
            raw=model_reply()
            if mutation=='length': raw['choices'][0]['finish_reason']='length'
            else: raw['choices'][0]['message'][mutation]='untrusted'
            with self.subTest(mutation=mutation),self.assertRaises(AssessmentError): module.normalize_openai(raw,'聽日')

    def test_oversized_reason_rejected(self):
        group={'text':'聽日','start':0,'end':2,'state':'pass','reason':'x'*81}
        with self.assertRaises(AssessmentError): module.normalize_openai(model_reply([group]),'聽日')


class OpenAITransportTests(unittest.TestCase):
    def test_audio_directly_supplied_fixed_model_no_store_or_prompt_key(self):
        data=wav()
        with patch('openai_feedback._request_json',return_value=model_reply()) as post:
            module.coach_openai_bytes(data,'聽日','private-test-key')
        request=post.call_args.args[0]
        body=json.loads(request.data)
        self.assertEqual(request.full_url,'https://api.openai.com/v1/chat/completions')
        self.assertEqual(body['model'],'gpt-audio-1.5')
        self.assertEqual(body['modalities'],['text']); self.assertFalse(body['store'])
        self.assertNotIn('response_format',body)
        self.assertEqual(body['messages'][1]['content'][1]['type'],'input_audio')
        self.assertEqual(base64.b64decode(body['messages'][1]['content'][1]['input_audio']['data']),data)
        self.assertNotIn('private-test-key',request.data.decode())
        self.assertEqual(request.get_header('Authorization'),'Bearer private-test-key')
        self.assertEqual(post.call_count,1)

    def test_error_does_not_expose_body_or_key_and_no_retry(self):
        error=urllib.error.HTTPError(module.ENDPOINT,401,'private-test-key',{},io.BytesIO(b'private-test-key'))
        with patch('urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect=error
            with self.assertRaises(AssessmentError) as raised:
                module._request_json(object())
        self.assertEqual(raised.exception.code,'http_401')
        self.assertNotIn('private-test-key',str(raised.exception))
        self.assertEqual(opener.return_value.open.call_count,1)


if __name__=='__main__': unittest.main()
