import os
import unittest
from unittest.mock import Mock

from mycomp_bot_engine.jobs import Shell


@unittest.skipUnless(os.name == "nt", "Windows-only Shell optimization")
class WindowsFastShellCleanupTests(unittest.TestCase):
    def test_finished_process_with_eof_skips_taskkill(self):
        process = Mock()
        process.poll.return_value = 0
        readers = [Mock(), Mock()]
        for reader in readers:
            reader.is_alive.return_value = False
        self.assertTrue(Shell._windows_clean_exit(process, readers))

    def test_running_process_retains_original_cleanup(self):
        process = Mock()
        process.poll.return_value = None
        self.assertFalse(Shell._windows_clean_exit(process, []))

    def test_pipe_holding_descendant_retains_original_cleanup(self):
        process = Mock()
        process.poll.return_value = 0
        reader = Mock()
        reader.is_alive.return_value = True
        self.assertFalse(Shell._windows_clean_exit(process, [reader]))