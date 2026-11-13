import os
import tempfile
import time
import unittest
from pathlib import Path
from history_retention import prune

class RetentionTests(unittest.TestCase):
    def test_expired_history_removed_recent_and_active_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);now=time.time()
            for name,age in [('old',4),('new',1),('active',5)]:
                p=root/'reports'/name;p.mkdir(parents=True);(p/'report.json').write_text('{}')
                stamp=now-age*86400;os.utime(p,(stamp,stamp))
            jobs={'active':{'status':'running'},'old':{'status':'review'}}
            result=prune(root,jobs,now,deep=False)
            self.assertEqual(result['reports'],1)
            self.assertNotIn('old',jobs)
            self.assertTrue((root/'reports/new').exists())
            self.assertTrue((root/'reports/active').exists())
    def test_knowledge_and_scripts_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'.runtime/action-knowledge/navigation.sqlite3';p.parent.mkdir(parents=True);p.write_text('keep')
            prune(root,{},time.time()+10*86400)
            self.assertEqual(p.read_text(),'keep')
