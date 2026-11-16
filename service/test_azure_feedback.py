import io
import unittest
import wave
from unittest.mock import patch
from assess import AssessmentError, assess_azure_bytes, recognize_azure_bytes
from azure_feedback import build_feedback, validate_wav


def wav(seconds=.5, silent=False, rate=16000):
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(rate)
        out.writeframes((b'\0\0' if silent else b'\x80\x00') * int(rate*seconds))
    return buffer.getvalue()


def pa(words, accuracy=90):
    return {'RecognitionStatus': 'Success', 'NBest': [{
        'PronunciationAssessment': {'AccuracyScore': accuracy, 'FluencyScore': 80, 'CompletenessScore': 100},
        'Words': [{'Word': text, 'Offset': i*1000000, 'Duration': 1000000,
                   'PronunciationAssessment': {'AccuracyScore': score, 'ErrorType': error}}
                  for i, (text, score, error) in enumerate(words)]}]}


def asr(text):
    return {'RecognitionStatus': 'Success', 'NBest': [{'Display': text}]}


class FeedbackTests(unittest.TestCase):
    def test_documented_rest_flat_shape(self):
        raw={'RecognitionStatus':'Success','NBest':[{'AccuracyScore':83,'FluencyScore':78,'CompletenessScore':100,
             'Words':[{'Word':'聽日','AccuracyScore':83,'ErrorType':'None','Offset':1000000,'Duration':2000000}]}]}
        result=build_feedback('聽日',raw,asr('聽日'))
        self.assertEqual(result['overall']['accuracy'],83)
        self.assertEqual(result['groups'][0]['score'],83)
        self.assertEqual(result['groups'][0]['state'],'pass')
        self.assertEqual(result['groups'][0]['offset_seconds'],.1)

    def test_rest_flat_omission_recovers(self):
        raw={'RecognitionStatus':'Success','NBest':[{'AccuracyScore':55,'Words':[
            {'Word':'聽','AccuracyScore':0,'ErrorType':'Omission'},
            {'Word':'日','AccuracyScore':88,'ErrorType':'None'}]}]}
        result=build_feedback('聽日',raw,asr('日'))
        self.assertEqual([g['state'] for g in result['groups']],['omitted','pass'])

    def test_group_score_remains_one_group(self):
        result = build_feedback('我今日買書，聽日再睇。', pa([('我', 90, 'None'), ('今日', 95, 'None'), ('買書', 89, 'None'), ('聽日', 96, 'None'), ('再睇', 90, 'None')]), asr('我今日買書聽日再睇'))
        buy = result['groups'][2]
        self.assertEqual((buy['text'], buy['start'], buy['end'], buy['state']), ('買書', 3, 5, 'pass'))
        self.assertEqual(result['groups'][3]['start'], 6)
        self.assertFalse(result['lexical_tone_validated'])

    def test_wrong_word_blocks_pass_even_at_one_hundred(self):
        result = build_feedback('聽日再睇', pa([('聽', 100, 'None'), ('日', 100, 'None'), ('再', 100, 'None'), ('睇', 100, 'None')]), asr('明日再看'))
        self.assertEqual([g['state'] for g in result['groups']], ['retry','pass','pass','retry'])
        self.assertEqual(result['groups'][0]['reason'], 'different_or_unmatched_words')

    def test_low_score_requires_retry_despite_text_match(self):
        result = build_feedback('聽', pa([('聽',59,'None')]), asr('聽'))
        self.assertEqual(result['groups'][0]['state'], 'retry')

    def test_close_requires_correct_word_and_middle_score(self):
        for score, expected in [(59,'retry'),(60,'close'),(79,'close'),(80,'pass')]:
            with self.subTest(score=score):
                result=build_feedback('聽',pa([('聽',score,'None')]),asr('聽'))
                self.assertEqual(result['groups'][0]['state'],expected)

    def test_middle_score_wrong_word_or_explicit_error_is_not_close(self):
        cases=[(asr('明'),'None','retry'),(asr('聽'),'Mispronunciation','retry'),(None,'None','uncertain')]
        for recognition,error,expected in cases:
            with self.subTest(error=error,recognition=recognition):
                result=build_feedback('聽',pa([('聽',73,error)]),recognition)
                self.assertEqual(result['groups'][0]['state'],expected)

    def test_omissions_do_not_block_later_words(self):
        result = build_feedback('我買書再睇', pa([('我',100,'None'),('買',0,'Omission'),('書',0,'Omission'),('再睇',91,'None')]), asr('我再睇'))
        self.assertEqual([g['state'] for g in result['groups']], ['pass','omitted','omitted','pass'])

    def test_repeated_word_does_not_shift_following_feedback(self):
        result = build_feedback('我買書再睇', pa([('我',100,'None'),('買書',95,'None'),('買書',91,'Insertion'),('再睇',91,'None')]), asr('我買書買書再睇'))
        self.assertEqual([g['text'] for g in result['groups']], ['我','買書','再睇'])
        self.assertTrue(all(g['state'] == 'pass' for g in result['groups']))
        self.assertEqual(result['crosscheck']['insertion_count'], 2)

    def test_unavailable_crosscheck_never_passes(self):
        result = build_feedback('買書',pa([('買書',100,'None')]),None,'network_error')
        self.assertEqual(result['groups'][0]['state'], 'uncertain')
        self.assertEqual(result['crosscheck']['reason'], 'network_error')

    def test_no_asr_speech_is_neutral(self):
        result = build_feedback('我', pa([('我',100,'None')]), {'RecognitionStatus':'NoMatch'})
        self.assertEqual(result['groups'][0]['state'], 'uncertain')

    def test_assessment_no_match_has_no_scores(self):
        result=build_feedback('我', {'RecognitionStatus':'NoMatch'}, asr('我'))
        self.assertEqual(result['status'],'no_match'); self.assertEqual(result['groups'],[])
        self.assertIsNone(result['overall']['accuracy'])

    def test_missing_pa_group_has_neutral_unmapped_span(self):
        result=build_feedback('我買書',pa([('我',100,'None')]),asr('我買書'))
        self.assertEqual(result['groups'][1]['text'],'買書')
        self.assertEqual(result['groups'][1]['state'],'uncertain')
        self.assertIsNone(result['groups'][1]['score'])

    def test_codepoint_offsets_do_not_use_utf16_units(self):
        result=build_feedback('𠮷，你好',pa([('𠮷',90,'None'),('你好',90,'None')]),asr('𠮷你好'))
        self.assertEqual((result['groups'][1]['start'],result['groups'][1]['end']),(2,4))

    def test_no_guessed_simplified_conversion(self):
        result=build_feedback('買書',pa([('買書',100,'None')]),asr('买书'))
        self.assertNotEqual(result['groups'][0]['state'],'pass')

    def test_unmapped_provider_word_is_not_assigned_false_position(self):
        result=build_feedback('聽日',pa([('明天',100,'None')]),asr('聽日'))
        self.assertEqual(result['groups'],[{'start':0,'end':2,'text':'聽日','score':None,'state':'uncertain','reason':'mapping_unavailable','error_type':None,'word_group':True}])

    def test_nan_score_does_not_pass(self):
        result=build_feedback('我',pa([('我',float('nan'),'None')]),asr('我'))
        self.assertEqual(result['groups'][0]['state'],'uncertain')

    def test_provider_mispronunciation_never_passes(self):
        result=build_feedback('我',pa([('我',99,'Mispronunciation')]),asr('我'))
        self.assertEqual(result['groups'][0]['state'],'retry')


class WavTests(unittest.TestCase):
    def test_zero_audio_stays_neutral(self):
        self.assertTrue(validate_wav(wav(silent=True))['no_speech'])

    def test_short_audio_is_not_graded(self):
        self.assertTrue(validate_wav(wav(.1))['no_speech'])

    def test_valid_audio_and_duration(self):
        self.assertEqual(validate_wav(wav())['duration_seconds'],.5)
        self.assertFalse(validate_wav(wav())['no_speech'])

    def test_wrong_rate_rejected(self):
        with self.assertRaises(AssessmentError): validate_wav(wav(rate=8000))

    def test_truncated_rejected(self):
        with self.assertRaises(AssessmentError): validate_wav(wav()[:-300])

    def test_overlong_rejected(self):
        with self.assertRaises(AssessmentError): validate_wav(wav(25.1))


class TransportTests(unittest.TestCase):
    def test_two_distinct_requests_only_pa_has_reference(self):
        with patch('assess._post_json',return_value={}) as post:
            assess_azure_bytes(wav(),'聽','test-private-key','eastasia')
            recognize_azure_bytes(wav(),'test-private-key','eastasia')
        first,second=[c.args[0] for c in post.call_args_list]
        self.assertTrue(first.get_header('Pronunciation-assessment'))
        self.assertIsNone(second.get_header('Pronunciation-assessment'))
        self.assertEqual(first.data,second.data)
        self.assertIn('https://eastasia.stt.speech.microsoft.com/',first.full_url)
        self.assertNotIn('test-private-key',first.full_url)

    def test_region_cannot_be_arbitrary_url_or_inject_hostname(self):
        for value in ['https://example.com','eastasia.example.com','../eastasia','eastasia?x=1','eastasia/evil']:
            with self.subTest(value=value), self.assertRaises(AssessmentError):
                recognize_azure_bytes(wav(),'test-private-key',value)


if __name__ == '__main__': unittest.main()
