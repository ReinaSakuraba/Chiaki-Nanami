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