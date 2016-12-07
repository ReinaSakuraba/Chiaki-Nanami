from discord.ext import commands
import discord.utils

# from RoboDanny.py

def is_owner_check(ctx):
    return ctx.message.author.id == '239110748180054017'

def is_owner():
    return commands.check(is_owner_check)

def check_permissions(ctx, perms):
    msg = ctx.message
    if is_owner_check(msg):
        return True

    ch = msg.channel
    author = msg.author
    resolved = ch.permissions_for(author)
    return all(getattr(resolved, name, None) == value
               for name, value in perms.items())

def role_or_permissions(ctx, check, **perms):
    if check_permissions(ctx, perms):
        return True

    ch = ctx.message.channel
    author = ctx.message.author
    if ch.is_private:
        return False

    role = discord.utils.find(check, author.roles)
    return role is not None

def roles_check(*roles, **perms):
    def predicate(ctx):
        return has_role_or_perms(ctx, lambda r: r.name in roles, **perms)
    return commands.check(predicate)

def admin_or_permissions(**perms):
    return roles_check('Bot Admin', **perms)
