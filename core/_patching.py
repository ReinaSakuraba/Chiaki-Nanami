"""Patching a few things"""
import operator

from discord.ext import commands
from itertools import chain
from more_itertools import iterate


commands.Command.all_names = property(lambda self: [self.name, *self.aliases],
                                      doc='Returns all the possible names for a command')

def walk_parents(command):
    """Walks up a command's parent chain."""
    return iter(iterate(operator.attrgetter('parent'), command).__next__, None)
commands.Command.walk_parents = walk_parents
del walk_parents

def walk_parent_names(command):
    """Yields the qualified name for each parent in the command's parent chain"""
    return (cmd.qualified_name for cmd in command.walk_parents())
commands.Command.walk_parent_names = walk_parent_names
del walk_parent_names

def all_checks(command):
    """Returns a list of all the checks that a command goes through.

    This does not account for global checks.
    """
    # Not sure if this is how the actual command framework does it tbh

    checks = chain.from_iterable(cmd.checks for cmd in command.walk_parents()
                                 if not getattr(cmd, 'invoke_without_command', False))
    checks = chain(command.checks, checks)
    if command.instance is None:
        return list(checks)
    try:
        local_check = getattr(command.instance, f'_{command.cog_name}__local_check')
    except AttributeError:
        pass
    else: 
        checks = chain(checks, (local_check, ))
    return list(checks)
commands.Command.all_checks = property(all_checks)
del all_checks