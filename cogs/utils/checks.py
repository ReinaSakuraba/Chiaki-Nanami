import discord.utils
import enum

from discord.ext import commands

from .database import Database

DEFAULT = 'Bot Admin'
class ChiakiRole(enum.Enum):
    admin = 'admin'
    mod = 'moderator'
    permissions = 'permissions'

    def __str__(self):
        return self.value.title()

server_role_default = dict.fromkeys(map(str, ChiakiRole), DEFAULT)
server_roles = Database.from_json("admin/adminsandmods.json", default_factory=server_role_default.copy)

def assign_role(server, key, role):
    server_roles[server][str(key)] = getattr(role, 'id', DEFAULT)

def get_role(server, key):
    return server_roles[server][str(key)]

# -----------PREDICATES AND CHECKS------------

def is_owner_predicate(ctx):
    return ctx.message.author.id == '239110748180054017'

def is_owner():
    return commands.check(is_owner_predicate)

def permissions_predicate(ctx, **perms):
    if is_owner_predicate(ctx):
        return True
    msg = ctx.message
    ch = msg.channel
    author = msg.author
    resolved = ch.permissions_for(author)
    return all(getattr(resolved, perm, None) == value
               for perm, value in perms.items())

def role_predicate(ctx, role):
    if is_owner_predicate(ctx):
        return True
    ch = ctx.message.channel
    author = ctx.message.author
    server = ctx.message.server
    if ch.is_private:
        return False
    role_id = get_role(server, role)
    role = discord.utils.get(author.roles, id=role_id)
    role_name = discord.utils.get(author.roles, name=str(DEFAULT))
    return None not in (role, role_name)

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
    return has_role(ChiakiRole.admin)

def is_mod():
    return has_role(ChiakiRole.mod)

def admin_or_permissions(**perms):
    return has_role_or_perms(ChiakiRole.admin, **perms)

def mod_or_permissions(**perms):
    return has_role_or_perms(ChiakiRole.mod, **perms)
