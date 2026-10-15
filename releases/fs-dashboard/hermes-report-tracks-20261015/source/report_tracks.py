"""Select an analysis method; this adds no data or execution authority."""
PRICING_MARKER = '【竞品与定价研究】'


def track_for_question(question, mode=None):
    if not isinstance(question, str):
        raise ValueError('report_question_required')
    return 'pricing' if mode == 'pricing' or question.lstrip().startswith(PRICING_MARKER) else 'operations'
