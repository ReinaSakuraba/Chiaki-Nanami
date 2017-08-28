import asyncio
import discord


NO_MESSAGES = object()


# TODO: Improve docs for this
async def prompt(prompt, context, emojis=(), *, timeout=None, 
                 check=NO_MESSAGES, delete_message=True):
    """A way to allow user input in Discord.

    If check is either None or callable, the user may type a message for input.
    If emojis is not empty, the user may react.
    Specifiying neither a check or emojis will raise a RuntimeError.
    """

    if isinstance(prompt, discord.Embed):
        message = await context.send(embed=prompt)
    else:
        message = await context.send(prompt)

    waiters = []
    future = None
    if emojis:
        def reaction_check(reaction, user):
            return (reaction.message.id == message.id
                    and user.id == context.author.id
                    and reaction.emoji in emojis)

        async def adder():
            for e in emojis:
                await message.add_reaction(e)

        future = asyncio.ensure_future(adder())
        waiters.append(context.bot.wait_for('reaction_add', check=reaction_check))

    if check is not NO_MESSAGES:
        def message_check(m):
            return (m.channel.id == context.channel.id
                    and m.author.id == context.author.id
                    and (check is None or check(m)))

        waiters.append(context.bot.wait_for('message', check=message_check))

    if not waiters:
        raise RuntimeError("No form of input specified.")

    try:
        done, pending = await asyncio.wait(waiters, timeout=timeout,
                                           return_when=asyncio.FIRST_COMPLETED)
        # asyncio.wait doesn't raise TimeoutError, so we have to raise it for it
        if not done:
            raise asyncio.TimeoutError

        # We can guarantee that exactly one future will be done. Because we put
        # at most two futures and it will only return one due to the return_when
        assert len(done) == 1, "both futures are done for some reason"
        # Unfortunately, reaction_add returns a tuple of reaction, user
        # You can't easily take these two different return types. Perhaps
        # if I don't need any other metadata except for the actual content
        # we can do the isinstance check here.
        return await done.pop()

    finally:
        if future and not future.done():
            future.cancel()

        if delete_message:
            await message.delete()

        for fut in pending:
            if not fut.done():
                fut.cancel()
