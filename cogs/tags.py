import asyncpg
import asyncqlio
import datetime
import discord
import itertools

from discord.ext import commands

from .utils.paginator import ListPaginator


class TagError(commands.UserInputError):
    pass


_Table = asyncqlio.table_base()


class Tag(_Table, table_name='tags'):
    name = asyncqlio.Column(asyncqlio.String, index=True, primary_key=True)
    # If this is an alias, this will be repurposed to point to the original tag.
    content = asyncqlio.Column(asyncqlio.String, default='')

    is_alias = asyncqlio.Column(asyncqlio.Boolean)
    # TODO:
    embed = asyncqlio.Column(asyncqlio.String, default='')

    # Some important metadata.
    owner_id = asyncqlio.Column(asyncqlio.BigInt)
    uses = asyncqlio.Column(asyncqlio.Integer, default=0)
    location_id = asyncqlio.Column(asyncqlio.BigInt, index=True, primary_key=True)
    created_at = asyncqlio.Column(asyncqlio.Timestamp)


class MemberTagPaginator(ListPaginator):
    def __init__(self, *args, member, **kwargs):
        super().__init__(*args, **kwargs)
        self.member = member

    def _create_embed(self, idx, page):
        return (super()._create_embed(idx, page)
                       .set_author(name=f'Tags made by {self.member.display_name}', icon_url=self.member.avatar_url)
                )


class ServerTagPaginator(ListPaginator):
    def _create_embed(self, idx, page):
        guild = self.context.guild
        embed = super()._create_embed(idx, page).set_author(name=f'Tags in {guild}')
        if guild.icon:
            return embed.set_author(name=embed.author.name, icon_url=guild.icon_url)
        return embed


class Tags:
    """You're it."""
    def __init__(self, bot):
        self.bot = bot
        self._md = self.bot.db.bind_tables(_Table)

    async def __error(self, ctx, error):
        print('error!', error)
        if isinstance(error, TagError):
            await ctx.send(error)

    async def _get_tag(self, session, name, guild_id):
        query = (session.select.from_(Tag)
                        .where((Tag.name == name.lower())
                               & (Tag.location_id == guild_id)))
        tag = await query.first()
        if tag is None:
            raise TagError(f"Tag {name} not found.")

        return tag

    async def _get_original_tag(self, session, name, guild_id):
        tag = await self._get_tag(session, name, guild_id)
        if tag.is_alias:
            return await self._get_tag(session, tag.content, guild_id)
        return tag

    async def _resolve_tag(self, session, name, guild_id):
        tag = await self._get_original_tag(session, name, guild_id)
        return tag.content

    @commands.group(invoke_without_command=True)
    async def tag(self, ctx, *, tag):
        """Retrieves a tag, if one exists."""
        content = await self._resolve_tag(ctx.session, tag, ctx.guild.id)
        await ctx.send(content)

    @tag.command(name='create', aliases=['add'])
    async def tag_create(self, ctx, name, *, content):
        """Creates a new tag."""
        tag = Tag(
            name=name.lower(),
            content=content,
            is_alias=False,
            owner_id=ctx.author.id,
            location_id=ctx.guild.id,
            created_at=datetime.datetime.utcnow()
        )

        try:
            await ctx.session.add(tag)
        except asyncpg.UniqueViolationError as e:
            raise TagError(f'Tag {name} already exists...') from e
        else:
            await ctx.send(f'Successfully created tag {name}! ^.^')

    @tag.command(name='edit')
    async def tag_edit(self, ctx, name, *, new_content):
        """Edits a tag that *you* own.

        You can only edit actual tags. i.e. you can't edit aliases.
        """
        tag = await self._get_tag(ctx.session, name, ctx.guild.id)
        if tag.is_alias:
            return await ctx.send("This tag is an alias. I can't edit it.")

        tag.content = new_content
        await ctx.session.merge(tag)
        await ctx.send("Successfully edited the tag!")

    @tag.command(name='alias')
    async def tag_alias(self, ctx, alias, original):
        """Creats an alias of a tag.

        You own the alias. However, if the original tag gets deleted,
        so does your alias.

        You also can't edit the alias.
        """
        # Make sure the original tag exists.
        tag = await self._get_original_tag(ctx.session, original, ctx.guild.id)
        new_tag = Tag(
            name=alias.lower(),
            content=tag.name,
            is_alias=True,
            owner_id=ctx.author.id,
            location_id=ctx.guild.id,
            created_at=datetime.datetime.utcnow()
        )

        try:
            await ctx.session.add(new_tag)
        except asyncpg.UniqueViolationError as e:
            raise TagError(f'Alias {alias} already exists...') from e
        else:
            await ctx.send(f'Successfully created alias {alias} that points to {original}! ^.^')

    @tag.command(name='delete', aliases=['remove'])
    async def tag_delete(self, ctx, *, name):
        """Removes a tag or alias.

        Only the owner of the tag or alias can delete it.
        """
        # idk how wasteful this is. Probably very.
        tag = await self._get_tag(ctx.session, name, ctx.guild.id)
        if tag.owner_id != ctx.author.id:
            return await ctx.send("This tag is not yours.")

        await ctx.session.remove(tag)
        if not tag.is_alias:
            # Slow path, we gotta delete all aliases.
            await ctx.session.delete(Tag).where((Tag.location_id == ctx.guild.id)
                                                & (Tag.is_alias == True)
                                                & (Tag.content == name.lower()))

            await ctx.send(f"Tag {name} and all of its aliases have been deleted.")
        else:
            await ctx.send("Alias successfully deleted.")

    @tag.command(name='list', aliases=['all'])
    async def tag_list(self, ctx):
        """Shows all the tags in the server."""
        query = ctx.session.select(Tag).where(Tag.location_id == ctx.guild.id).order_by(Tag.name)
        counter = itertools.count(1)
        tags = [(next(counter), tag.name) async for tag in await query.all()]

        entries = (itertools.starmap('{0}. {1}'.format, tags)
                   if tags else
                   ('There are no tags. Use `{ctx.prefix}tag create` to fix that.', ))

        paginator = ServerTagPaginator(ctx, entries)
        await paginator.interact()

    @tag.command(name='from', aliases=['by'])
    async def tag_by(self, ctx, *, member: discord.Member = None):
        """Shows all the tags in the server."""
        member = member or ctx.author
        query = (ctx.session.select.from_(Tag)
                            .where((Tag.location_id == ctx.guild.id) & (Tag.owner_id == member.id))
                            .order_by(Tag.name)
                 )

        counter = itertools.count(1)
        tags = [(next(counter), tag.name) async for tag in await query.all()]

        entries = (itertools.starmap('{0}. {1}'.format, tags)
                   if tags else
                   (f"{member} didn't make any tags yet. :(",))
        paginator = ListPaginator(ctx, entries)
        await paginator.interact()

    @commands.group(invoke_without_command=True)
    async def tags(self, ctx):
        """Alias for `{prefix}tag list`."""
        await ctx.invoke(self.tag_list)

    @tags.command(name='from', aliases=['by'])
    async def tags_from(self, ctx, *, member: discord.Member = None):
        """Alias for `{prefix}tag from/by`."""
        await ctx.invoke(self.tag_by, member=member)


def setup(bot):
    bot.add_cog(Tags(bot))
