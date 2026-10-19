"""Parse model HTML as data. No script, browser, network, or file execution."""
from html.parser import HTMLParser
import re


class Document(HTMLParser):
    def __init__(self):
        super().__init__(); self.parents=[]; self.spans=[]; self.styles=[]; self.in_style=False

    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag=='span':self.spans.append((attrs,self.parents[-1] if self.parents else None,self.getpos()[0]))
        if tag=='style':self.in_style=True
        if tag not in {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}:
            self.parents.append((tag,attrs))

    def handle_endtag(self, tag):
        if tag=='style':self.in_style=False
        for index in range(len(self.parents)-1,-1,-1):
            if self.parents[index][0]==tag:
                del self.parents[index:];break

    def handle_data(self, data):
        if self.in_style:self.styles.append(data)


def check_html(args):
    if not isinstance(args,dict) or set(args)!={'html'} or not isinstance(args['html'],str) or len(args['html'].encode())>1000000:
        raise ValueError('html_check_input')
    raw=args['html'];doc=Document();doc.feed(raw);css='\n'.join(doc.styles)
    rules=re.findall(r'([^{}]+)\{([^{}]*)\}',css)
    def declarations(tag,attrs):
        text=''
        classes=set(attrs.get('class','').split())
        for selectors,body in rules:
            for selector in selectors.split(','):
                selector=selector.strip()
                if selector==tag or re.fullmatch(r'(?:'+re.escape(tag)+r')?(?:\.[\w-]+)+',selector) and set(re.findall(r'\.([\w-]+)',selector))<=classes:
                    text+=';'+body
        text+=';'+attrs.get('style','')
        return {k.strip().lower():v.strip().lower() for k,v in re.findall(r'([\w-]+)\s*:\s*([^;{}]+)',text)}
    issues=[]
    if not re.search(r'<!doctype\s+html',raw,re.I) or not re.search(r'</html\s*>',raw,re.I):
        issues.append({'code':'incomplete_html','message':'Return one complete HTML document.'})
    for attrs,parent,line in doc.spans:
        style=declarations('span',attrs)
        if 'width' not in style or 'height' not in style:continue
        if style.get('display','inline')!='inline' or style.get('position') in ('absolute','fixed') or style.get('float','none')!='none':continue
        parent_style=declarations(*parent) if parent else {}
        if parent_style.get('display') in ('flex','inline-flex','grid','inline-grid'):continue
        issues.append({'code':'inline_span_bar_has_no_box','line':line,'class':attrs.get('class','')[:120],
                       'message':'This span has width/height but stays inline; an empty bar may have zero visible width. Use display:block/inline-block or an intentional positioned/flex layout, then verify in a browser.'})
    return {'status':'needs_review' if issues else 'structural_checks_passed','issues':issues[:30],
            'issue_count':len(issues),'execution':'HTML/CSS text parsed only; scripts not executed',
            'limits':'Static structural checks do not prove visual layout, data accuracy, or interaction correctness.'}
