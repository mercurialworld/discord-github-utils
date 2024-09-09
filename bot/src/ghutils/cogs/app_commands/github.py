from __future__ import annotations

import logging
import uuid
from datetime import datetime

from discord import Embed, Interaction, app_commands
from discord.ext.commands import GroupCog
from discord.ui import Button, View
from githubkit.exception import GitHubException
from githubkit.rest import Issue, PullRequest, SimpleUser

from ghutils.core.cog import GHUtilsCog
from ghutils.db.models import (
    UserGitHubTokens,
    UserLogin,
)
from ghutils.utils.discord.embeds import set_embed_author
from ghutils.utils.discord.references import (
    CommitReference,
    IssueReference,
    PRReference,
)
from ghutils.utils.discord.visibility import MessageVisibility, respond_with_visibility
from ghutils.utils.github import (
    CommitStatusState,
    IssueState,
    PullRequestState,
    Repository,
    gh_request,
    short_sha,
)
from ghutils.utils.strings import truncate_str

logger = logging.getLogger(__name__)


class GitHubCog(GHUtilsCog, GroupCog, group_name="gh"):
    """GitHub-related commands."""

    # /gh

    @app_commands.command()
    @app_commands.rename(reference="issue")
    async def issue(
        self,
        interaction: Interaction,
        reference: IssueReference,
        visibility: MessageVisibility = "private",
    ):
        """Get a link to a GitHub issue."""

        await respond_with_visibility(
            interaction,
            visibility,
            embed=_create_issue_embed(*reference),
        )

    @app_commands.command()
    @app_commands.rename(reference="pr")
    async def pr(
        self,
        interaction: Interaction,
        reference: PRReference,
        visibility: MessageVisibility = "private",
    ):
        """Get a link to a GitHub pull request."""

        await respond_with_visibility(
            interaction,
            visibility,
            embed=_create_issue_embed(*reference),
        )

    @app_commands.command()
    @app_commands.rename(reference="commit")
    async def commit(
        self,
        interaction: Interaction,
        reference: CommitReference,
        visibility: MessageVisibility = "private",
    ):
        """Get a link to a GitHub commit."""

        repo, commit = reference

        # TODO: this doesn't include Actions????????
        async with self.bot.github_app(interaction) as (github, _):
            try:
                status = await gh_request(
                    github.rest.repos.async_get_combined_status_for_ref(
                        owner=repo.owner,
                        repo=repo.repo,
                        ref=commit.sha,
                    )
                )
                match status.state:
                    case "success":
                        state = CommitStatusState.SUCCESS
                    case "failure":
                        state = CommitStatusState.FAILURE
                    case _:
                        state = CommitStatusState.PENDING
            except GitHubException:
                state = CommitStatusState.PENDING

        sha = short_sha(commit.sha)

        message = commit.commit.message
        description = None
        if "\n" in message:
            message, description = message.split("\n", maxsplit=1)
            description = truncate_str(description.strip(), 200)

        embed = Embed(
            title=truncate_str(f"Commit {sha}: {message}", 256),
            description=description,
            url=commit.html_url,
            color=state.color,
        ).set_footer(
            text=f"{repo}@{sha}",
        )

        if (author := commit.commit.author) and author.date:
            try:
                embed.timestamp = datetime.fromisoformat(author.date)
            except ValueError:
                pass

        if isinstance(commit.author, SimpleUser):
            set_embed_author(embed, commit.author)

        await respond_with_visibility(interaction, visibility, embed=embed)

    @app_commands.command()
    async def login(self, interaction: Interaction):
        """Authorize GitHub Utils to make requests on behalf of your GitHub account."""

        user_id = interaction.user.id
        login_id = str(uuid.uuid4())

        with self.bot.db_session() as session:
            match session.get(UserLogin, user_id):
                case UserLogin() as login:
                    login.login_id = login_id
                case None:
                    login = UserLogin(user_id=user_id, login_id=login_id)

            session.add(login)
            session.commit()

        auth_url = self.env.gh.get_login_url(state=login.model_dump_json())

        await interaction.response.send_message(
            view=View().add_item(Button(label="Login with GitHub", url=str(auth_url))),
            ephemeral=True,
        )

    @app_commands.command()
    async def logout(self, interaction: Interaction):
        """Remove your GitHub account from GitHub Utils."""

        with self.bot.db_session() as session:
            # TODO: this should delete the authorization too, but idk how
            # https://docs.github.com/en/rest/apps/oauth-applications?apiVersion=2022-11-28#delete-an-app-authorization
            if user_tokens := session.get(UserGitHubTokens, interaction.user.id):
                session.delete(user_tokens)
                session.commit()

                await interaction.response.send_message(
                    "✅ Successfully logged out.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "❌ Already logged out.",
                    ephemeral=True,
                )


def _create_issue_embed(repo: Repository, issue: Issue | PullRequest):
    match issue:
        case Issue():
            issue_type = "Issue"
            state = IssueState.of(issue)
        case PullRequest():
            issue_type = "PR"
            state = PullRequestState.of(issue)

    embed = Embed(
        title=truncate_str(f"{issue_type} #{issue.number}: {issue.title}", 256),
        url=issue.html_url,
        timestamp=issue.created_at,
        color=state.color,
    ).set_footer(
        text=f"{repo}#{issue.number}",
    )

    if issue.body:
        embed.description = truncate_str(issue.body, 200)

    if issue.user:
        set_embed_author(embed, issue.user)

    return embed
