from discord.ext import commands

class PrivateMessagesOnly(commands.CommandError):
    """Exception raised when an operation only works in private message contexts."""

class InvalidUserArgument(commands.UserInputError):
    """Exception raised when the user inputs an invalid argument, even though conversion is successful."""

class ResultsNotFound(commands.UserInputError):
    """Exception raised when a search returns some form of "not found" """

def private_message_only(error_msg="This command can only be used in private messages"):
    def predicate(ctx):
        if not ctx.message.channel.is_private:
            raise PrivateMessagesOnly(error_msg)
        return True
    return commands.check(predicate)
