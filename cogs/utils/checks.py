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

def chiaki_check(predicate, *, role=None, perms=None):
    def decorator(func):
        func = getattr(func, 'callback', func)
        if not hasattr(func, '__requirements__'):
            func.__requirements__ = {}
        if role is not None:
            func.__requirements__.setdefault('roles', []).append(role)
        if perms is not None:
            func.__requirements__.setdefault('perms', []).extend(perms)
        return commands.check(predicate)(func)
    return decorator

def _nice_perms(**perms):
    return [f"{'Not' * (not v)} {k.replace('_', ' ').title()}" for k, v in perms.items()]

def is_owner_predicate(msg):
    return msg.author.id == 239110748180054017

def is_owner():
    return chiaki_check(lambda ctx: is_owner_predicate(ctx.message), role="Bot Owner")

def permissions_predicate(msg, **perms):
    if is_owner_predicate(msg):
        return True
    resolved = msg.channel.permissions_for(msg.author)
    return all(getattr(resolved, perm, None) == value
               for perm, value in perms.items())

def role_predicate(msg, role):
    if is_owner_predicate(msg):
        return True
    author, server = msg.author, msg.guild
    if not server:
        return False
    role_id = get_role(server, role)
    role = discord.utils.get(author.roles, id=role_id)
    role_name = discord.utils.get(author.roles, name=DEFAULT)
    return role is not None or role_name is not None

def role_or_perms_predicate(msg, role, **perms):
    return role_predicate(msg, role) or permissions_predicate(msg, **perms)

def has_role(role):
    return chiaki_check(lambda ctx: role_predicate(ctx.message, role), role=str(role))

def has_perms(**perms):
    return chiaki_check(lambda ctx: permissions_predicate(ctx.message, **perms), perms=_nice_perms(**perms))

def has_role_or_perms(role, **perms):
    return chiaki_check(lambda ctx: role_or_perms_predicate(ctx.message, role, **perms),
                        role=str(role), perms=_nice_perms(**perms))

def is_admin():
    return has_role(ChiakiRole.admin)

def is_mod():
    return has_role(ChiakiRole.mod)

def admin_or_permissions(**perms):
    return has_role_or_perms(ChiakiRole.admin, **perms)

def mod_or_permissions(**perms):
    return has_role_or_perms(ChiakiRole.mod, **perms)
