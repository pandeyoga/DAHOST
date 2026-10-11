"""Tambal mongomock agar mengenal $round (dipakai pipeline-update core/stock_service)."""
import mongomock.aggregate as A

def install():
    P = A._Parser
    orig = P._handle_arithmetic_operator
    def patched(self, operator, values):
        if operator == '$round':
            if not isinstance(values, (list, tuple)):
                values = [values, 0]
            num = self.parse(values[0]) if isinstance(values[0], (dict, str)) else values[0]
            places = 0
            if len(values) > 1:
                places = self.parse(values[1]) if isinstance(values[1], (dict, str)) else values[1]
            try:
                return round(float(num or 0), int(places or 0))
            except (TypeError, ValueError):
                return 0
        return orig(self, operator, values)
    P._handle_arithmetic_operator = patched
    try: A.arithmetic_operators = set(A.arithmetic_operators) | {'$round'}
    except Exception: pass
