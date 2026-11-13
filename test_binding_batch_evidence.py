# -*- coding: utf-8 -*-
"""Batch evidence selection must precede summaries and preserve sibling results."""
import json
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import codebuddy_bridge as bridge
import flow_planner
import excel_plan_cache


class BindingEvidenceTests(unittest.TestCase):
    def config(self, count=10):
        rows=[{'title':'目标'+str(i),'expected':'显示完成',
               'business_steps':[{'action':'打开/page'+str(i),'expected':'显示完成'}]} for i in range(count)]
        return {'outline':'按原始用例匹配','document':{'cases':rows},'binding_only':True,
                'strict_excel':True,'_excel_fast':True,'include_source':True,'source':'/fixture'}

    def index(self):
        return {'project':'/tmp','pages':[{'name':'page'+str(i),'path':'/page'+str(i),
                'labels':[{'key':'field'+str(i),'labels':['字段'+str(i)+'x'*1200]}],
                'entry_candidates':[{'steps':['首页','目标'+str(i)]}],
                'api_candidates':[{'http_method':'POST','path':'/api/save'+str(i)}]} for i in range(10)]}

    @staticmethod
    def answer(prompt,*args,**kwargs):
        document=json.loads(prompt.split('业务计划：\n',1)[1].split('\n测试大纲：\n',1)[0])
        return {'bindings':[{'case_id':i,'start_state':'home','steps':[
            {'business_step':n,'operations':[{'action':'assert','value':'完成'}]}
            for n,_ in enumerate(row['business_steps'],1)]} for i,row in enumerate(document['cases'],1)]}

    def test_ten_cases_are_split_before_any_source_summary(self):
        selected=[];original=flow_planner.ai_summary
        def summary(index,outline,**kwargs):
            selected.append(set(re.findall(r'/page\d+',outline)))
            self.assertLessEqual(len(selected[-1]),2)
            return original(index,outline,**kwargs)
        with patch.object(flow_planner,'source_index',return_value=self.index()) as scan, \
             patch.object(flow_planner,'ai_summary',side_effect=summary), \
             patch.object(bridge,'ask',side_effect=self.answer) as ask:
            result=bridge.generate(self.config())
        self.assertEqual(len(result['cases']),10)
        self.assertTrue(all(row['plan'] for row in result['cases']))
        self.assertEqual(ask.call_count,5);self.assertEqual(scan.call_count,1)
        self.assertEqual(set.union(*selected),{'/page'+str(i) for i in range(10)})

    def test_pair_budget_failure_recovers_as_singles_before_model_call(self):
        selected=[];events=[]
        def summary(index,outline,**kwargs):
            pages=set(re.findall(r'/page\d+',outline));selected.append(pages)
            if len(pages)>1:raise flow_planner.EvidenceBudgetExceeded('目标页面证据超过摘要大小')
            return {'pages':[]}
        with patch.object(flow_planner,'source_index',return_value=self.index()), \
             patch.object(flow_planner,'ai_summary',side_effect=summary), \
             patch.object(bridge,'ask',side_effect=self.answer) as ask:
            result=bridge.generate(self.config(2),lambda *event:events.append(event))
        self.assertTrue(all(row['plan'] for row in result['cases']))
        self.assertEqual([len(pages) for pages in selected],[2,1,1])
        self.assertEqual(ask.call_count,2)
        self.assertTrue(any(stage=='binding_evidence_split' for stage,_ in events))

    def test_single_overflow_preserves_other_nine_and_their_checkpoints(self):
        saved=[];snapshots=[]
        def progress(*event):pass
        progress.publish_draft=lambda draft:snapshots.append(json.loads(json.dumps(draft)))
        def summary(index,outline,**kwargs):
            if '/page0' in outline:raise flow_planner.EvidenceBudgetExceeded('目标页面证据超过摘要大小')
            return {'pages':[]}
        cfg=self.config();cfg['_excel_on_candidate']=lambda rows:saved.extend(row['title'] for row in rows)
        with patch.object(flow_planner,'source_index',return_value=self.index()), \
             patch.object(flow_planner,'ai_summary',side_effect=summary), \
             patch.object(bridge,'ask',side_effect=self.answer):
            result=bridge.generate(cfg,progress)
        self.assertIsNone(result['cases'][0]['plan'])
        self.assertIn('摘要处理失败',result['cases'][0]['blocked_reason'])
        self.assertTrue(all(row['plan'] for row in result['cases'][1:]))
        self.assertEqual(set(saved),{'目标'+str(i) for i in range(1,10)})
        self.assertTrue(snapshots)
        self.assertTrue(all(len(draft['cases'])==10 for draft in snapshots))

    def test_budget_failure_is_not_written_or_reused_from_legacy_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            entry={'plan':None,'blocked_reason':'目标页面入口、字段与接口证据超过摘要大小，请逐条匹配；未丢弃关键证据'}
            excel_plan_cache.save_blocked(tmp,'scope','case',entry)
            path=Path(tmp)/'blocked'/(excel_plan_cache.cache_key('scope','case')+'.json')
            self.assertFalse(path.exists())
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps({'version':excel_plan_cache.VERSION,'scope':'scope','case':'case',
                                        'expires':time.time()+3600,'entry':entry}))
            self.assertIsNone(excel_plan_cache.load_blocked(tmp,'scope','case'))
            semantic={'plan':None,'blocked_reason':'缺少测试门店数据'}
            excel_plan_cache.save_blocked(tmp,'scope','case',semantic)
            self.assertEqual(excel_plan_cache.load_blocked(tmp,'scope','case'),semantic)


if __name__=='__main__':unittest.main()
