import discord
import inspect
import operator

from collections.abc import Sequence
from discord.ext import commands

from cogs.utils.checks import ChiakiCheck
from cogs.utils.context_managers import temp_attr
from cogs.utils.misc import truncate

# small hacks to make command display all their possible names
commands.Command.all_names = property(lambda self: [self.name, *self.aliases])

class ChiakiFormatter(commands.HelpFormatter):
    def get_ending_note(self):
        return f"Type {self.clean_prefix}help command for more info on a command."

    @property
    def description(self):
        description = (self.command.help if not self.is_cog() else inspect.getdoc(self.command)) or 'No description'
        return description.format(prefix=self.context.prefix)

    @property
    def command_usage(self):
        cmd = self.command
        prefix = self.context.prefix
        qualified_names = [f"{cmd.full_parent_name} {name}" for name in cmd.all_names]
        if cmd.clean_params:
            usage = cmd.usage
            if isinstance(usage, Sequence):
                return '\n'.join([f'`{prefix}{random.choice(qualified_names)} {u}`' for u in always_iterable(usage)])
            # Assume it's invalid; usage must be a sequence (either a tuple, list, or str)
            return 'No example... yet'
        # commands that don't take any arguments don't really need an example generated manually....
        return None

    def command_requirements(self):
        chiaki_checks = [check for check in self.command.checks if isinstance(check, ChiakiCheck)]
        return {key: ', '.join(filter(None, map(operator.attrgetter(key), chiaki_checks))) or 'None' 
                for key in ['roles', 'perms'] }

    def paginate_cog_commands(self, cog_name):
        paginator = commands.Paginator(prefix='', suffix='', max_size=2048)
        paginator.add_line(self.description, empty=True)
        paginator.add_line('**List of commands:**')

        for command in sorted(self.context.bot.get_cog_commands(cog_name), key=operator.attrgetter('name')):
            name, aliases = command.name, ', '.join(command.aliases)
            paginator.add_line(f'`{name}` {f"| `{aliases}`" * bool(aliases)}')

        return paginator

    async def bot_help(self):
        bot, func = self.context.bot, self.apply_function
        default_help = bot.default_help
        result = default_help.format(bot, bot=bot)
        return func(result)

    async def cog_embed(self):
        ctx = self.context
        bot, cog = ctx.bot, self.command
        cog_name = type(cog).__name__
        paginated_commands = self.paginate_cog_commands(cog_name)

        embeds = []
        for i, page in enumerate(paginated_commands.pages):
            module_embed = discord.Embed(description=page, colour=bot.colour)
            if i == 0:
                module_embed.title = f"{cog_name} ({ctx.prefix})"
            embeds.append(module_embed)

        embeds[-1].set_footer(text=self.get_ending_note())
        return embeds

    async def command_embed(self):
        command, ctx, func = self.command, self.context, self.apply_function
        bot = ctx.bot
        usages = self.command_usage

        # if usage is truthy, it will immediately return with that usage. We don't want that.
        with temp_attr(command, 'usage', None):
            signature = command.signature

        requirements = self.command_requirements()
        cmd_name = f"`{ctx.prefix}{command.full_parent_name} {' / '.join(command.all_names)}`"
        footer = '"{0}" is in the module *{0.cog_name}*'.format(command)

        cmd_embed = discord.Embed(title=func(cmd_name), description=func(self.description), colour=bot.colour)

        if self.has_subcommands():
            command_names = sorted(cmd.name for cmd in command.commands)
            children = ', '.join(command_names) or "No commands... yet."
            cmd_embed.add_field(name=func("Child Commands"), value=func(children), inline=False)

        cmd_embed.add_field(name=func("Required Roles"), value=func(requirements['roles']))
        cmd_embed.add_field(name=func("Required Permissions"), value=func(requirements['perms']))
        cmd_embed.add_field(name=func("Structure"), value=f'`{func(signature)}`', inline=False)

        if usages is not None:
            cmd_embed.add_field(name=func("Usage"), value=func(usages), inline=False)
        return cmd_embed.set_footer(text=func(footer))

    async def format_help_for(self, ctx, command, func=lambda s: s):
        self.apply_function = func
        return await super().format_help_for(ctx, command)

    async def format(self):
        if self.is_bot():
            return await self.bot_help()
        elif self.is_cog():
            return await self.cog_embed()
        return await self.command_embed()
