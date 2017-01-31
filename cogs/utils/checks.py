import discord.utils
import functools

from discord.ext import commands

from .database import Database

server_role_default = lambda: {"admin": [], "moderator": []}
server_roles = Database.from_json("admin/adminsandmods.json", default_factory=server_role_default)

def add_admin_role(server, role):
    server_roles[server]["admin"].append(role.id)

def add_mod_role(server, role):
    server_roles[server]["moderator"].append(role.id)

def remove_admin_role(server, role):
    try:
        server_roles[server]["admin"].remove(role.id)
    except ValueError:
        pass

def remove_mod_role(server, role):
    try:
        server_roles[server]["moderator"].remove(role.id)
    except ValueError:
        pass

# -----------PREDICATES AND CHECKS------------

def is_owner_predicate(ctx):
    return ctx.message.author.id == '239110748180054017'

def is_owner():
    return commands.check(is_owner_predicate)

def permissions_predicate(ctx, **perms):
    msg = ctx.message
    if is_owner_predicate(ctx):
        return True
    ch = msg.channel
    author = msg.author
    resolved = ch.permissions_for(author)
    return all(getattr(resolved, perm, None) == value
               for perm, value in perms.items())

def role_predicate(ctx, role):
    ch = ctx.message.channel
    author = ctx.message.author
    if ch.is_private:
        return False
    role_ids = server_roles[ctx.message.server][role]
    role = discord.utils.find((lambda r: r.id in role_ids), author.roles)
    return role is not None

def role_or_perms_predicate(ctx, role, **perms):
    return role_predicate(ctx, role) or permissions_predicate(ctx, **perms)

def has_role(role):
    return commands.check(lambda ctx: role_predicate(ctx, role))

def has_perms(**perms):
    return commands.check(lambda ctx: permissions_predicate(ctx, **perms))

def has_role_or_perms(role, **perms):
    def predicate(ctx):
        return role_or_perms_predicate(ctx, role, **perms)
    return commands.check(predicate)

def is_admin():
    return has_role("admin")

def is_mod():
    return has_role("moderator")

def admin_or_permissions(**perms):
    return has_role_or_perms("admin", **perms)

def mod_or_permissions(**perms):
    return has_role_or_perms("moderator", **perms)
