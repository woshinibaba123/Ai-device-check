import tempfile
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch
import execution_memory as memory

class ExecutionMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        db=Path(self.tmp.name)/'memory.sqlite3'
        p=patch.object(memory,'connect',side_effect=lambda:sqlite3.connect(db));p.start();self.addCleanup(p.stop)
    def test_navigation_persists_and_isolated_by_application(self):
        scope=memory.scope('app','Android','goal')
        memory.navigation(scope,'frame',{'action':'tap','label':'清洁记录','center_normalized':[.5,.4]})
        self.assertEqual(memory.navigation(scope,'frame')['label'],'清洁记录')
        self.assertIsNone(memory.navigation(memory.scope('other','Android','goal'),'frame'))
        self.assertIsNone(memory.navigation(scope,'changed-frame'))
    def test_operations_aggregate_failure_without_payload(self):
        memory.record('scope','input',True,2)
        memory.record('scope','input',False,3)
        with memory.connect() as db:
            row=db.execute('SELECT count,failures,total_ms FROM operations').fetchone()
        self.assertEqual(row,(2,1,5))
