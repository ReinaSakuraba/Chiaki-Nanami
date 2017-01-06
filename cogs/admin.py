import discord
import traceback

from discord.ext import commands

from .utils import checks
from .utils.database import Database


async def _get_chiaki_roles(server, role):
    role_ids = checks.server_roles[server].get(role)
    if role_ids is None:
        return None
    return [discord.utils.get(server.roles, id=id) for id in role_ids]

class Admin:
    """Admin-only commands"""
    __prefix__ = '=>'

    def __init__(self, bot):
        self.bot = bot
        self.self_roles = Database.from_json("admin/selfroles.json",
                                             factory_not_top_tier=list)

    def __unload(self):
        checks.server_roles.dump()
        self.self_roles.dump()

    @commands.command(name='addadminrole', pass_context=True, aliases=['aar'])
    @checks.admin_or_permissions(manage_server=True)
    async def add_admin_role(self, ctx, *, role: discord.Role):
        """Adds a role for the 'Admins' role

        Admins are a special type of administrator. They have access to most of the permission-related
        or server-related commands.
        More than one role can be considered as "Admin"
        (This might be changed)
        """
        checks.add_admin_role(ctx.message.server, role)
        await self.bot.say(f"Made {role} an **Admin role**!")

    @commands.command(name='addmodrole', pass_context=True, aliases=['amr'])
    @checks.admin_or_permissions()
    async def add_mod_role(self, ctx, *, role: discord.Role):
        """Add a role from the 'Moderators' role

        Moderators mainly have access to most of the mod commands, such as mute, kick, and ban.
        More than one role can be considered as "Moderator"
        (This might be changed)
        """
        checks.add_mod_role(ctx.message.server, role)
        await self.bot.say(f"Made {role} an **Moderator role**!")

    @commands.command(name='admins', pass_context=True)
    async def admin_roles(self, ctx):
        roles = _get_chiaki_roles(ctx.message.server, "admin")

    @commands.command(name='moderators', pass_context=True)
    async def admin_roles(self, ctx):
        roles = _get_chiaki_roles(ctx.message.server, "admin")

    @commands.command(name='removeadminrole', pass_context=True,
                      aliases=['rar', 'remadminrole'])
    @checks.admin_or_permissions()
    async def remove_admin_role(self, ctx, *, role: discord.Role):
        """Removes a role from the 'Admins' role
        
        Admins are a special type of administrator. They have access to most of the permission-related
        or server-related commands.
        More than one role can be considered as "Admin"
        (This might be changed)
        """
        checks.add_admin_role(ctx.message.server, role)
        await self.bot.say(f"Removed **{role}** from Admins!")

    @commands.command(name='removemodrole',
                      pass_context=True, aliases=['rmr', 'remmodrole'])
    @checks.admin_or_permissions()
    async def remove_mod_role(self, ctx, *, role: discord.Role):
        """Removes a role from the 'Moderators' role

        More than one role can be considered as "Moderator"
        (This might be changed)
        """
        checks.add_mod_role(ctx.message.server, role)
        await self.bot.say(f"Made **{role}** an Moderators!")

    @commands.command(name='addselfrole', pass_context=True, aliases=['asar',])
    @checks.admin_or_permissions()
    async def add_self_role(self, ctx, *, role: discord.Role):
        """Adds a self-assignable role to the server

        A self-assignable role is one that you can assign to yourself
        using =>iam or =>selfrole
        """
        self_roles = self.self_roles[ctx.message.server]
        if role.id in self_roles:
            await self.bot.say("That role is already self-assignable... I think")
            return
        self_roles.append(role.id)
        await self.bot.say(f"**{role}** is now a self-assignable role!")

    @commands.command(name='removeselfrole',
                      pass_context=True, aliases=['rsar', 'remselfrole'])
    @checks.admin_or_permissions()
    async def remove_self_role(self, ctx, *, role: discord.Role):
        """Removes a self-assignable role from the server

        A self-assignable role is one that you can assign to yourself
        using =>iam or =>selfrole
        """
        try:
            self.self_roles[ctx.message.server].remove(role.id)
        except ValueError:
            await self.bot.say("That role was never self-assignable... I think")
        else:
            await self.bot.say(f"**{role}** is no longer a self-assignable role!")

    async def _self_role(self, member, role_action):
        server = member.server
        self_roles = self.self_roles[ctx.message.server]
        if role.id not in self_roles:
            await self.bot.say("That role is not self-assignable... :neutral_face:")
            return
        await role_action(member, role)

    @commands.command(pass_context=True, no_pm=True)
    async def iam(self, ctx, *, role: discord.Role):
        """Gives a self-assignable role (and only a self-assignable role) to yourself."""
        await self._self_role(ctx.message.author, self.bot.add_roles)
        await self.bot.say(f"You are now **{role}**... I think.")

    @commands.command(pass_context=True, no_pm=True)
    async def iamnot(self, ctx, *, role: discord.Role):
        """Removes a self-assignable role (and only a self-assignable role) to yourself."""
        await self._self_role(ctx.message.author, self.bot.remove_roles)
        await self.bot.say(f"You are no longer **{role}**... probably.")

    @commands.command(pass_context=True, no_pm=True)
    async def selfrole(self, ctx, *, role: discord.Role):
        """Gives or removes a self-assignable role (and only a self-assignable role)

        This depends on whether or not you have the role already.
        If you don't, it gives you the role. Otherwise it removes it.
        """
        author = ctx.message.author
        if role in author.roles:
            msg = f"You are no longer **{role}**... probably."
            role_action = self.bot.remove_roles
        else:
            msg = f"You are now **{role}**... I think."
            role_action = self.bot.remove_roles
        await self._self_role(author, role_action)
        await self.bot.say(msg)

def setup(bot):
    bot.add_cog(Admin(bot))
