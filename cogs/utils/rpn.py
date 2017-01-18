import math
import operator

from collections import OrderedDict

MATH_OPERATORS = OrderedDict([
    ('+', (2, operator.add)),
    ('-', (2, operator.sub)),
    ('*', (2, operator.mul)),
    ('/', (2, operator.truediv)),
    ('sqrt', (1, math.sqrt)),
    ('**',(2, operator.pow)),
   
    ('sin', (1, math.sin)),
    ('cos', (1, math.cos)),
    ('tan', (1, math.tan)),
    ('cot', (1, lambda x: 1 / math.tan(x))),
    ('sec', (1, lambda x: 1 / math.cos(x))),
    ('csc', (1, lambda x: 1 / math.sin(x))),

    ('~', (1, operator.invert)),
    ('&', (2, operator.and_)),
    ('|', (2, operator.or_)),
    ('^', (2, operator.xor)),
    ('<<', (2, operator.lshift)),
    ('>>', (2, operator.rshift)),
    ])

op_fmts = [
    '{0}({1})',
    '{1} {0} {2}',
    ]

def _num(string):
    try:
        return int(string)
    except ValueError:
        return float(string)

def rpn_to_infix(tokens):
    if isinstance(tokens, str):
        tokens = tokens.split()
    stack = []
    for token in tokens:
        if token in MATH_OPERATORS:
            values_required, op = MATH_OPERATORS[token]
            try:
                operands = [stack.pop() for _ in range(values_required)]
            except IndexError:
                raise SyntaxError("Not enough numbers in expression")
            else:
                op_string = op_fmts[values_required - 1].format(token, *operands)
                stack.append(f"( {op_string} )")
        else:
            try:
                stack.append(_num(token))
            except ValueError:
                raise TypeError(f"Unrecognized token: {token}")
                
    if len(stack) != 1:
        raise SyntaxError("Too many numbers in expression")
    return stack[0].strip('()').strip()

def eval_rpn(tokens):
    if isinstance(tokens, str):
        tokens = tokens.split()
    stack = []
    for token in tokens:
        if token in MATH_OPERATORS:
            values_required, op = MATH_OPERATORS[token]
            try:
                operands = [stack.pop() for _ in range(values_required)]
            except IndexError:
                raise SyntaxError("Not enough numbers in expression")
            else:
                stack.append(op(*operands))

        else:
            try:
                stack.append(_num(token))
            except ValueError:
                raise TypeError(f"Unrecognized token: {token}")

    if len(stack) != 1:
        raise SyntaxError("Too many numbers in expression")
    return stack[0]