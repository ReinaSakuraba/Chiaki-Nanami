from .prefixes import Prefixes
from .permissions import Permissions
from .welcome import WelcomeMessages


class Config(Prefixes, Permissions, WelcomeMessages):
    """Commands related to any sort of configuration for Chiaki, i.e. me."""

    # TODO: Make a mixin-class for this
    async def __global_check(self, ctx):
        return await self._Permissions__global_check(ctx)

    async def __global_check_once(self, ctx):
        return await self._Permissions__global_check_once(ctx)

def setup(bot):
    bot.add_cog(Config(bot))
