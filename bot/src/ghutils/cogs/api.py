from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse
from githubkit import GitHub
from pydantic import ValidationError
from sqlmodel import Session
from uvicorn import Config, Server

from ghutils.core.bot import GHUtilsBot
from ghutils.core.cog import GHUtilsCog
from ghutils.core.env import GHUtilsEnv
from ghutils.db.models import UserGitHubTokens, UserLogin
from ghutils.resources import load_resource

SUCCESS_PAGE = load_resource("web/success.html")


logger = logging.getLogger(__name__)

app = FastAPI(root_path="/api")


def get_bot():
    bot = app.state.bot
    assert isinstance(bot, GHUtilsBot), f"Invalid state.bot, expected GHUtilsBot: {bot}"
    return bot


def get_env(bot: BotDependency):
    return bot.env


def get_session(bot: BotDependency):
    with bot.db_session() as session:
        yield session


BotDependency = Annotated[GHUtilsBot, Depends(get_bot)]
EnvDependency = Annotated[GHUtilsEnv, Depends(get_env)]
SessionDependency = Annotated[Session, Depends(get_session)]


@app.get("/login")
async def get_login(
    code: str,
    state: str,
    env: EnvDependency,
    session: SessionDependency,
):
    # parse state to UserLogin
    try:
        login = UserLogin.model_validate_json(state)
    except (ValueError, ValidationError) as e:
        logger.debug(f"Failed to parse login state: {e}")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Failed to parse login state")

    # make sure the login id matches the one generated by the login command
    match db_login := session.get(UserLogin, login.user_id):
        case UserLogin(login_id=login.login_id):
            session.delete(db_login)
        case UserLogin() | None:
            logger.debug(f"Invalid login state: {db_login}")
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid login state")

    # get the access/refresh tokens from GitHub
    github = GitHub(env.gh.get_oauth_app_auth())
    auth = await github.auth.as_web_user(
        code=code,
        redirect_uri=env.gh.redirect_uri,
    ).async_exchange_token(github)  # pyright: ignore[reportUnknownMemberType]

    # insert the tokens into the database
    match session.get(UserGitHubTokens, login.user_id):
        case UserGitHubTokens() as user_tokens:
            user_tokens.refresh(auth)
        case None:
            user_tokens = UserGitHubTokens.from_auth(login.user_id, auth)
    session.add(user_tokens)

    # commit the delete and insert
    session.commit()

    return HTMLResponse(SUCCESS_PAGE)


@dataclass
class APICog(GHUtilsCog):
    server: Server | None = field(default=None, init=False)

    async def cog_load(self):
        app.state.bot = self.bot
        self.server = Server(
            Config(
                app,
                host="0.0.0.0",
                port=self.env.api_port,
            )
        )
        self.bot.loop.create_task(self.server.serve())

    async def cog_unload(self):
        if self.server:
            await self.server.shutdown()
            self.server = None
