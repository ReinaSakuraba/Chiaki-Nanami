import math
import re

from discord.ext import commands

MATH_CONTEXT = {a: getattr(math, a, None) for a in dir(math) if not a.startswith('_')}
sec = lambda x: 1 / math.cos(x)
csc = lambda x: 1 / math.sin(x)
cot = lambda x: 1 / math.tan(x)
sign = lambda x: (x > 0) - (x < 0)
MATH_CONTEXT.update(ln=math.log, arcsin=math.asin, arccos=math.acos, arctan=math.atan,
                    sec=sec, secant=sec, csc=csc, cosecant=csc, cot=cot, cotangent=cot,
                    abs=abs, min=min, max=max, divmod=divmod, round=round, sign=sign
                    )
del sec, csc, cot, sign
OTHER_OPS = ['and', 'or', 'not', ]

def _is_sane(token):
    if not token:
        return True
    return token in MATH_CONTEXT or token in OTHER_OPS
    
def sanitize(fn_str):
    words = re.split(r"[0-9.+\-*/^&|<> ()=]+", fn_str)
    for token in words:
        if not _is_sane(token):
            raise ValueError(f"Unrecognized token: {token}")

    return eval("lambda: " + fn_str, MATH_CONTEXT)
        
class Math:
    __prefix__ = ['+', '-', '*', '/']
    def __init__(self, bot):
        self.bot = bot
        
    @commands.command(aliases=['calcfuncs'])
    async def calcops(self):
        ops = set(key for key, val in MATH_CONTEXT.items() if callable(val))
        await self.bot.say(f"Available functions: \n```\n{', '.join(ops)}```")
        
    @commands.command(aliases=['calc'])
    async def calculate(self, *, expr: str): 
        """Calculates a mathematical expression
        
        """
        
        try:
            fn = sanitize(expr)
        except (ValueError, SyntaxError) as e: 
            output = f"{type(e).__name__}: {e}"
        else:
            try:
                output = fn()
            except Exception as e:
                output = f"{type(e).__name__}: {e}"
            
        await self.bot.say(f"```css\nInput: \n{expr}\n\nOutput:\n{output}```")
            
def setup(bot):
    bot.add_cog(Math(bot))