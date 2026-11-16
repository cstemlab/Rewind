import subprocess
import sys
import types
import unittest
from unittest.mock import Mock, patch
import creator
from assess import AssessmentError


class PDFResourceTests(unittest.TestCase):
    def test_linux_limit_configuration(self):
        resource = types.SimpleNamespace(RLIMIT_AS=1, RLIMIT_CPU=2, RLIMIT_FSIZE=3, setrlimit=Mock())
        with patch.object(creator.sys, 'platform', 'linux'), patch.dict(sys.modules, {'resource': resource}):
            creator._limit_pdf_worker()
        self.assertEqual(resource.setrlimit.call_args_list[0].args, (1, (268435456, 268435456)))
        self.assertEqual(resource.setrlimit.call_args_list[1].args, (2, (10, 10)))
        self.assertEqual(resource.setrlimit.call_args_list[2].args, (3, (0, 0)))

    def test_resource_kill_returns_safe_pdf_error(self):
        killed = types.SimpleNamespace(returncode=-9, stdout=b'')
        with patch.object(creator.subprocess, 'run', return_value=killed) as run:
            with self.assertRaises(AssessmentError) as caught:
                creator._pdf_worker(b'%PDF-mock')
        self.assertEqual(caught.exception.code, 'invalid_pdf')
        self.assertIn('_limit_pdf_worker()', run.call_args.args[0][2])
        self.assertEqual(run.call_args.kwargs['timeout'], 20)

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Actual RLIMIT_AS check requires Linux container/Cloud Shell.')
    def test_linux_address_space_limit_blocks_oversized_allocation(self):
        code = "from creator import _limit_pdf_worker; _limit_pdf_worker();\ntry: bytearray(300*1024*1024)\nexcept MemoryError: print('bounded')"
        result = subprocess.run([sys.executable, '-c', code], cwd=creator.HERE, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), b'bounded')
