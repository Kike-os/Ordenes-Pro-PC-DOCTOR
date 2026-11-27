"""Short-term repair intake estimate with a chronological holdout."""
from datetime import timedelta
from math import ceil
from statistics import mean

TRAIN_DAYS = 28
VALIDATION_DAYS = 14
HORIZON = 7
MIN_ORDERS = 14

METHOD_NAMES = {'weekday': 'Promedio del mismo día de la semana',
                'mean': 'Promedio de las últimas cuatro semanas'}


def _estimate(history, offset, method):
    if method == 'weekday':
        return mean(history[-7 + offset - span] for span in range(0, TRAIN_DAYS, 7))
    return mean(history)


def estimate(series, today):
    start = today - timedelta(days=TRAIN_DAYS + VALIDATION_DAYS)
    window = {
        'from': start.isoformat(), 'through': (today - timedelta(days=1)).isoformat(),
        'validation_days': VALIDATION_DAYS, 'training_days': TRAIN_DAYS,
    }
    if len(series) != TRAIN_DAYS + VALIDATION_DAYS or sum(series[:TRAIN_DAYS]) < MIN_ORDERS:
        return dict(window, status='insufficient', days=[],
                    note='Se necesitan 42 días completos y al menos 14 órdenes en los primeros 28 días.')
    methods = ('mean', 'weekday')
    errors = {}
    for key in methods:
        errors[key] = [
            abs(series[index] - _estimate(series[index-TRAIN_DAYS:index], 0, key))
            for index in range(TRAIN_DAYS, len(series))
        ]
    method = min(methods, key=lambda key: mean(errors[key]))
    observed = sorted(errors[method])
    error = observed[ceil(.9 * len(observed)) - 1]
    recent = series[-TRAIN_DAYS:]
    days = []
    for offset in range(HORIZON):
        value = _estimate(recent, offset, method)
        days.append({'date': (today + timedelta(days=offset)).isoformat(), 'estimate': round(value, 1),
                     'low': round(max(0, value-error), 1), 'high': round(value+error, 1)})
    return dict(window, status='ready', days=days, method=METHOD_NAMES[method],
                mae=round(mean(observed), 1), historical_error=round(error, 1),
                validation=[{'method': METHOD_NAMES[key], 'mae': round(mean(errors[key]), 1)} for key in methods],
                note='El rango usa el error de la validación histórica. La estimación no modifica órdenes ni fechas.')


def intake(c, now):
    today = now.date()
    start = today - timedelta(days=TRAIN_DAYS + VALIDATION_DAYS)
    start_date, end_date = start.isoformat(), today.isoformat()
    root_orders = "(group_id IS NULL OR group_id=id) AND received_at<>''"
    covered = c.execute('SELECT 1 FROM orders WHERE ' + root_orders + ' AND received_at<? LIMIT 1',
                        (start_date,)).fetchone()
    series = []
    if covered:
        counts = dict(c.execute(
            "SELECT substr(received_at,1,10),COUNT(*) FROM orders WHERE " + root_orders +
            " AND received_at>=? AND received_at<? GROUP BY substr(received_at,1,10)",
            (start_date, end_date)
        ))
        series = [counts.get((start + timedelta(days=i)).isoformat(), 0)
                  for i in range(TRAIN_DAYS + VALIDATION_DAYS)]
    return estimate(series, today)
