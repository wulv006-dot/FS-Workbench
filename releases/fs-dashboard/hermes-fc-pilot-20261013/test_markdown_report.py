import copy
import json
import unittest
from html import unescape
from html.parser import HTMLParser
from types import SimpleNamespace

from report_delivery import deliver_output
from report_html import markdown, render_report


class Document(HTMLParser):
    def __init__(self, value):
        super().__init__(convert_charrefs=True)
        self.tags=[]; self.values=[]
        self.feed(value)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag,dict(attrs)))

    def handle_data(self, value):
        self.values.append(value)


class MarkdownReportTests(unittest.TestCase):
    def setUp(self):
        self.ref='ev_'+'a'*24
        self.unknown='ev_'+'f'*24
        self.period={'start':'2026-10-05','end':'2026-10-11'}
        total={'orders':2,'revenue_usd':'10.00','known_revenue_usd':'10.00','average_order_usd':'5.00','unpriced_orders':0}
        self.evidence={self.ref:{'source':'Admin FC支付明细','query':dict(self.period,group_by=[],filters={}),
            'data':{'status':'available','total':total}}}
        self.book=SimpleNamespace(evidence=self.evidence,capture_id='fixture')

    def render(self, source):
        result=deliver_output(source,self.book)
        return result,render_report(result,self.evidence,self.period)

    def test_headings_paragraphs_emphasis_inline_code_and_fences(self):
        source='\n\n'.join('#'*level+' 标题'+str(level) for level in range(1,7))
        source+='\n\n**加粗**、*强调*、__重点__、_斜体_、***同时强调***。\n第二行原文。\n\n`**代码不强调**`\n\n```python\n<script>not_run()</script>\n# 代码内标题\n```'
        html=markdown(source)
        for level in range(1,7): self.assertIn('<h'+str(level)+'>标题'+str(level)+'</h'+str(level)+'>',html)
        for value in ('<strong>加粗</strong>','<em>强调</em>','<strong>重点</strong>','<em>斜体</em>',
                      '<strong><em>同时强调</em></strong>','<br>第二行原文。','<code>**代码不强调**</code>',
                      '<pre><code>&lt;script&gt;not_run()&lt;/script&gt;\n# 代码内标题</code></pre>'):
            self.assertIn(value,html)

    def test_nested_lists_preserve_explicit_ordered_numbers_and_all_items(self):
        html=markdown('- 一级\n  - 二级\n  - 第二个二级\n- 第二个一级\n\n3. 三号\n7. 七号\n2. 二号')
        self.assertEqual(html.count('<ul>'),2)
        for value in ('一级','二级','第二个二级','第二个一级'): self.assertIn('<p>'+value+'</p>',html)
        for number,value in ((3,'三号'),(7,'七号'),(2,'二号')):
            self.assertIn('<li value="'+str(number)+'"><p>'+value+'</p></li>',html)

    def test_tables_support_emphasis_escaped_pipes_and_code_pipes_without_dropping_extra_cells(self):
        html=markdown('| 范围 | 估算 |\n| :--- | ---: |\n| **PS** | 10.00 |\n| a\\|b | `x|y` |\n| 原值 | 20.00 | 额外原文 |')
        self.assertIn('<thead><tr><th>范围</th><th>估算</th></tr></thead>',html)
        self.assertIn('<td><strong>PS</strong></td><td>10.00</td>',html)
        self.assertIn('<td>a|b</td><td><code>x|y</code></td>',html)
        self.assertIn('<td>原值</td><td>20.00</td><td>额外原文</td>',html)

    def test_model_html_links_images_and_code_never_create_executable_or_external_elements(self):
        source='''# 安全原文
<script>alert(1)</script><img src="https://invalid.test/a" onerror="bad()">
</style><style>body{background:url(https://invalid.test)}</style>
<iframe src="https://invalid.test"></iframe><svg onload="bad()"></svg>
[原链接](javascript:bad()) ![图片](https://invalid.test/p.png)
[带引号](https://invalid.test/\" onmouseover=\"bad())
<https://invalid.test/raw>
```html
<script>code()</script>
```
'''
        _,html=self.render(source)
        doc=Document(html)
        self.assertFalse(set(tag for tag,_ in doc.tags)&{'script','img','iframe','object','embed','link'})
        self.assertEqual(sum(tag=='style' for tag,_ in doc.tags),1)
        for tag,attrs in doc.tags:
            self.assertFalse(any(name.startswith('on') for name in attrs))
            self.assertNotIn('src',attrs)
            if 'href' in attrs: self.assertTrue(attrs['href'].startswith('#'))
        visible=''.join(doc.values)
        for value in ('<script>alert(1)</script>','[原链接](javascript:bad())','![图片](https://invalid.test/p.png)',
                      '<iframe src="https://invalid.test"></iframe>','<script>code()</script>'):
            self.assertIn(value,visible)

    def test_known_body_refs_are_clickable_unknown_refs_stay_text_and_do_not_invent_details(self):
        second='ev_'+'b'*24
        self.evidence[second]={'source':'合成公开证据','data':{'status':'available','value':'原值'}}
        result,html=self.render('# 引用\n\n已知 '+second+'；未知 '+self.unknown+'。')
        self.assertIn('<a href="#'+second+'">'+second+'</a>',html)
        self.assertIn('id="'+second+'"',html)
        self.assertIn(self.unknown,html)
        self.assertNotIn('href="#'+self.unknown+'"',html)
        self.assertNotIn('id="'+self.unknown+'"',html)
        self.assertTrue(result['limitations'])
        result['findings'][0]['evidence_ids'].append(self.unknown)
        result['report_evidence_ids'].append(self.unknown)
        self.assertNotIn('id="'+self.unknown+'"',render_report(result,self.evidence,self.period))

    def test_evidence_ids_in_inline_code_and_links_remain_literal(self):
        html=markdown('`'+self.ref+'` ['+self.ref+'](https://invalid.test)',self.evidence)
        self.assertNotIn('<a ',html)
        self.assertIn('<code>'+self.ref+'</code>',html)
        self.assertIn('['+self.ref+'](https://invalid.test)',html)

    def test_markdown_links_can_only_target_known_same_run_evidence(self):
        html=markdown('[来源](#'+self.ref+') [原证据]('+self.ref+') [缺口](#'+self.unknown+') [外部](https://invalid.test/#'+self.ref+')',self.evidence)
        self.assertIn('<a href="#'+self.ref+'">来源</a>',html)
        self.assertIn('<a href="#'+self.ref+'">原证据</a>',html)
        self.assertIn('[缺口](#'+self.unknown+')',html)
        self.assertIn('[外部](https://invalid.test/#'+self.ref+')',html)
        self.assertNotIn('href="#'+self.unknown+'"',html)
        self.assertEqual(html.count('<a '),2)

    def test_natural_report_uses_full_original_once_without_fact_badges_or_empty_action_sections(self):
        source='# 唯一首标题\n\n唯一首段：范围是 PS，金额为估算 $10.00。\n\n'+'\n\n'.join('原文段'+str(i)+'：不改判断与数字。' for i in range(200))
        source+='\n\n## 唯一末标题\n\n唯一结尾：先复核，再决定动作。'
        result,html=self.render(source)
        before=copy.deepcopy(result)
        render_report(result,self.evidence,self.period)
        self.assertEqual(result,before)
        self.assertEqual(result['raw_model_text'],source)
        self.assertEqual(html.count('唯一首段'),1)
        self.assertEqual(html.count('唯一末标题'),1)
        self.assertIn('原文段199：不改判断与数字。',html)
        self.assertIn('唯一结尾：先复核，再决定动作。',html)
        for value in ('证据判断','待证解释','id="actions"','id="history"','id="investigation"','本次没有足够证据形成旧判断修正'):
            self.assertNotIn(value,html)

    def test_fence_spanning_delivery_sections_is_not_broken_by_findings_split(self):
        source='# 正文\n\n```text\n## 代码里的标题\n**原样代码**\n```\n\n## 真正后节\n完整结尾。'
        result,html=self.render(source)
        self.assertGreater(len(result['findings']),1)
        self.assertIn('<pre><code>## 代码里的标题\n**原样代码**</code></pre>',html)
        self.assertNotIn('<h2>代码里的标题</h2>',html)
        self.assertIn('<h2>真正后节</h2>',html)

    def test_same_run_admin_cards_chart_and_evidence_details_survive_natural_delivery(self):
        day='ev_'+'c'*24
        self.evidence[day]=copy.deepcopy(self.evidence[self.ref])
        self.evidence[day]['query']['group_by']=['day']
        self.evidence[day]['data'].update(pagination={'complete':True},groups=[
            {'group':{'day':'2026-10-05'},'revenue_usd':'4.00'},
            {'group':{'day':'2026-10-06'},'revenue_usd':'6.00'}])
        _,html=self.render('# 自然调查\n\n估算先看日期与范围。')
        self.assertEqual(html.count('目标完整期间'),3)
        self.assertIn('$10.00',html)
        self.assertIn('<svg viewBox="0 0 800 250"',html)
        self.assertIn('每日销售曲线',html)
        self.assertIn('id="'+self.ref+'"',html)
        self.assertIn('id="'+day+'"',html)

    def test_raw_json_fallback_is_complete_escaped_code_not_rewritten_as_findings(self):
        source=json.dumps({'text':'<script>原文</script>','number':1234,'tail':'全部保留','evidence':self.ref},ensure_ascii=False)
        result,html=self.render(source)
        self.assertEqual(result['report_format'],'raw_json')
        code=html.split('<section id="decision" class="report"><pre><code>',1)[1].split('</code></pre>',1)[0]
        self.assertEqual(unescape(code),source)
        self.assertNotIn('<script',html)
        self.assertNotIn('id="actions"',html)
        self.assertIn('href="#'+self.ref+'"',html)

    def test_unclosed_fence_and_unmatched_markup_preserve_full_text_without_failure(self):
        source='## 标题\n\n未闭合 **原文\n\n~~~text\n<script>最后原文</script>\n## 不丢尾部'
        html=markdown(source)
        self.assertIn('未闭合 **原文',html)
        self.assertIn('<pre><code>&lt;script&gt;最后原文&lt;/script&gt;\n## 不丢尾部</code></pre>',html)
        long_ticks='`'*10000
        self.assertIn(long_ticks,markdown('原文 '+long_ticks+' 尾部'))

    def test_report_sections_without_raw_text_render_as_report_not_facts(self):
        report={'summary':'不重复摘要','findings':[{'claim_type':'report','statement':'## 原始节\n\n范围与估算原文。','evidence_ids':[self.unknown]}],
            'actions':[],'reviews':[],'limitations':[]}
        html=render_report(report,self.evidence,self.period)
        self.assertIn('<h2>原始节</h2>',html)
        self.assertIn('范围与估算原文。',html)
        self.assertNotIn('不重复摘要',html)
        self.assertNotIn('证据判断',html)


if __name__=='__main__': unittest.main()
