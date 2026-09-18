"""One merged binary outcome per question; never silently shrink the denominator."""

from .backends import validate_judgment


def summarize(rows, predictions, judgments):
    results = []
    for row in rows:
        qid = row['id']
        judgment = judgments.get(qid, {}).get('judgment')
        if judgment is not None:
            validate_judgment(judgment)
        results.append({'id': qid, 'correct': None if judgment is None else int(judgment['correct'] == 'yes')})
    complete = all(row['correct'] is not None for row in results)
    correct = sum(row['correct'] or 0 for row in results)
    return {'complete': complete, 'questions': len(rows), 'predictions': len(predictions),
            'judgments': len(judgments), 'correct': correct,
            'missing_predictions': len(rows) - len(predictions),
            'missing_judgments': len(rows) - len(judgments),
            'accuracy': correct / len(rows) if complete else None,
            'accuracy_percent': 100 * correct / len(rows) if complete else None,
            'per_question': results}
