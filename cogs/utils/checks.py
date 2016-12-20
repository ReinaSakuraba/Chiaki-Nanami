from discord.ext import commands
import discord.utils

# from RoboDanny.py

def is_owner_check(ctx):
    return ctx.message.author.id == '239110748180054017'

_make_check = commands.check
def is_owner():
    return _make_check(is_owner_check)

def permissions_check(ctx, **perms):
    msg = ctx.message
    if is_owner_check(ctx):
        return True

    ch = msg.channel
    author = msg.author
    resolved = ch.permissions_for(author)
    return all(getattr(resolved, name, None) == value
               for name, value in perms.items())

def roles_check(ctx, *roles):
    ch = ctx.message.channel
    author = ctx.message.author
    if ch.is_private:
        return False

    role = discord.utils.find((lambda r: r.name in roles), author.roles)
    return role is not None

def roles_or_perms_check(ctx, *roles, **perms):
    return roles_check(ctx, *roles) or permissions_check(ctx, **perms)

def has_role(*roles):
    return _make_check(lambda ctx: roles_check(ctx, *roles))

def has_perms(**perms):
    return _make_check(lambda ctx: permissions_check(ctx, **perms))

def has_role_or_perms(*roles, **perms):
    def predicate(ctx):
        return roles_or_perms_check(ctx, *roles, **perms)
    return commands.check(predicate)

def admin_or_permissions(**perms):
    return has_role_or_perms('Bot Admin', **perms)
