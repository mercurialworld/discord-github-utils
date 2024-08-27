from discord import Interaction, app_commands
from discord.ext.commands import GroupCog

from ghutils.core.cog import GHUtilsCog
from ghutils.utils.discord.config import ConfigAction
from ghutils.utils.discord.transformers import RepositoryParam


@app_commands.guild_only()
class LocalConfigCog(GHUtilsCog, GroupCog, group_name="gh-config-local"):
    """Configure settings for your account in this server."""

    @app_commands.command()
    async def default_repo(
        self,
        interaction: Interaction,
        action: ConfigAction,
        value: RepositoryParam | None = None,
    ):
        # TODO: function-ize
        match action:
            case ConfigAction.get:
                await interaction.response.send_message("get")
            case ConfigAction.set:
                await interaction.response.send_message("set")
            case ConfigAction.reset:
                await interaction.response.send_message("reset")
