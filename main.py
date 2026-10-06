# main.py — discord.py v2
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os
import dotenv

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("NC_bot")
load_dotenv()

# ---------------- CONFIG ----------------
GUILD_ID = 1308168064918884473

TRANSACTIONS_ID = 1556440700093079572
MATCH_TIMES_CHANNEL_ID = 1556440787947094076
ASSIGNMENTS_CHANNEL_ID = 1556869225501564999
SCRIM_CATEGORY_ID = 0
MATCH_SCORES_CHANNEL_ID = 1556440758783840347

CAPTAIN_ROLE_ID = 1556869856018694244
CO_CAPTAIN_ROLE_ID = 1556869877409521685
EXECUTIVE_ROLE_ID = 1556869919163814018
TEAM_PLAYER_ROLE_ID = 1556869903468990495

HEAD_REF_ROLE_ID = 1556870113917935757
REF_ROLE_ID = 1556426315538763806
HEAD_CASTER_ROLE_ID = 1556870090501259304
CASTER_ROLE_ID = 1556405382119690250

FAQ_CHANNEL_ID = 1508547674780209203
STREAM_WATCHER_ROLE_ID = 1508548137894023349
UNBORN_CAPTAIN_ROLE_ID = 1508548191753343177
EVENT_PING_ROLE_ID = 1508548173864505404

GUILD_OBJ = discord.Object(id=GUILD_ID)
# --------------------- FILES --------------------
data_dir = Path(os.getenv("data_file", "/data"))
data_dir.mkdir(parents=True, exist_ok=True)

TEAMS_FILE = data_dir / "teams.json"
PLAYER_HISTORY_FILE = data_dir / "player_history.json"
INVITES_FILE = data_dir / "invites.json"
ROSTER_LOCK_FILE = data_dir / "roster_lock.json"


# ---------------- HELPERS ----------------
def is_staff(user: discord.Member) -> bool:
    perms = user.guild_permissions
    return perms.administrator or perms.manage_guild


EASTERN = ZoneInfo("America/New_York")

def parse_match_time(value: str) -> datetime:
    """Parse a match time and return a timezone-aware datetime in Eastern time."""
    text = value.strip()

    # Remove an optional Eastern timezone suffix.
    text = re.sub(r"\s*(?:EST|EDT|ET)\s*$", "", text, flags=re.IGNORECASE)

    # Accept "at" or just whitespace between the date and time.
    text = re.sub(r"\s+at\s+", " ", text, flags=re.IGNORECASE)

    formats = (
        "%m/%d/%y %I%p",       # 10/6/26 1AM
        "%m/%d/%y %I %p",      # 10/6/26 1 AM
        "%m/%d/%y %I:%M%p",    # 10/6/26 1:00AM
        "%m/%d/%y %I:%M %p",   # 10/6/26 1:00 AM
        "%m/%d/%Y %I%p",
        "%m/%d/%Y %I %p",
        "%m/%d/%Y %I:%M%p",
        "%m/%d/%Y %I:%M %p",
        "%Y-%m-%d %H:%M",      # 2026-10-06 13:00
    )

    parsed = None
    for fmt in formats:
        try:
            parsed = datetime.strptime(text, fmt)
            break
        except ValueError:
            continue

    if parsed is None:
        raise ValueError(
            "Invalid date/time. Try `10/6/26 at 1:00 PM EST` "
            "or `2026-10-06 13:00`."
        )

    match_time = parsed.replace(tzinfo=EASTERN)

    if match_time <= datetime.now(EASTERN):
        raise ValueError("The match time must be in the future.")

    return match_time



def _safe_load_json(path: Path, default):
    if not path.exists():
        return default
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, OSError) as exc:
        log.error("%s invalid: %s. Resetting.", path.name, exc)
        path.write_text(json.dumps(default, indent=4), encoding="utf-8")
        return default


def _save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=4), encoding="utf-8")


def load_teams() -> list:
    return _safe_load_json(TEAMS_FILE, [])


def save_teams(data: list) -> None:
    _save_json(TEAMS_FILE, data)


def load_player_history() -> dict:
    return _safe_load_json(PLAYER_HISTORY_FILE, {})


def save_player_history(data: dict) -> None:
    _save_json(PLAYER_HISTORY_FILE, data)


def load_invites() -> dict:
    return _safe_load_json(INVITES_FILE, {})


def save_invites(data: dict) -> None:
    _save_json(INVITES_FILE, data)


def load_roster_locks() -> dict:
    data = _safe_load_json(ROSTER_LOCK_FILE, {"ALL": False})
    if not isinstance(data, dict):
        data = {"ALL": False}
    data.setdefault("ALL", False)
    return data


def save_roster_locks(data: dict) -> None:
    data.setdefault("ALL", False)
    _save_json(ROSTER_LOCK_FILE, data)


def is_roster_locked(guild: discord.Guild, team_role: discord.Role) -> bool:
    locks = load_roster_locks()
    return bool(locks.get("ALL", False) or locks.get(str(team_role.id), False))


def role_in(member: discord.Member, role: discord.Role | None) -> bool:
    return role is not None and role in member.roles


def get_team_roles_from_file(guild: discord.Guild) -> list[discord.Role]:
    roles = []
    for team in load_teams():
        role_id = team.get("role_id")
        if role_id:
            role = guild.get_role(int(role_id))
            if role:
                roles.append(role)
    return roles


def find_single_team_for_member(
    guild: discord.Guild, member: discord.Member
) -> discord.Role | None:
    owned = [role for role in get_team_roles_from_file(guild) if role in member.roles]
    return owned[0] if len(owned) == 1 else None


def add_pending_invite(team_role_id: int, user_id: int) -> None:
    invites = load_invites()
    key, uid = str(team_role_id), str(user_id)
    invites.setdefault(key, [])
    if uid not in invites[key]:
        invites[key].append(uid)
    save_invites(invites)


def remove_pending_invite(team_role_id: int, user_id: int) -> None:
    invites = load_invites()
    key, uid = str(team_role_id), str(user_id)
    if key in invites and uid in invites[key]:
        invites[key].remove(uid)
        if not invites[key]:
            del invites[key]
    save_invites(invites)


def safe_channel_name(text: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9-]+", "-", text.lower())
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:100] or "scrim"


# ---------------- BOT SETUP ----------------
intents = discord.Intents.default()
intents.members = True


class MyBot(commands.Bot):
    async def setup_hook(self) -> None:
        await self.add_cog(TeamManager(self))
        synced = await self.tree.sync(guild=GUILD_OBJ)
        log.info("Synced guild commands: %s", [command.name for command in synced])


bot = MyBot(command_prefix="!", intents=intents)


# ---------------- INVITE UI ----------------
class InviteDMView(discord.ui.View):
    def __init__(
        self,
        guild_id: int,
        team_role_id: int,
        inviter_id: int,
        invited_id: int,
        timeout: float = 86400,
    ):
        super().__init__(timeout=timeout)
        self.guild_id = guild_id
        self.team_role_id = team_role_id
        self.inviter_id = inviter_id
        self.invited_id = invited_id

    async def _finish(self, interaction: discord.Interaction) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        try:
            await interaction.message.edit(view=self)
        except (discord.HTTPException, AttributeError):
            pass

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.green)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.invited_id:
            await interaction.response.send_message("This invite is not for you.", ephemeral=True)
            return

        guild = interaction.client.get_guild(self.guild_id)
        member = guild.get_member(self.invited_id) if guild else None
        team_role = guild.get_role(self.team_role_id) if guild else None
        player_role = guild.get_role(TEAM_PLAYER_ROLE_ID) if guild else None

        if not guild or not member or not team_role or not player_role:
            await interaction.response.send_message("Invite is no longer valid.", ephemeral=True)
            return

        if find_single_team_for_member(guild, member) is not None:
            await interaction.response.send_message(
                "You already have a team. Leave your current team before accepting another invite.",
                ephemeral=True,
            )
            return

        try:
            await member.add_roles(team_role, player_role, reason="Accepted team invite")
        except discord.HTTPException as exc:
            await interaction.response.send_message(f"Failed to add roles: {exc}", ephemeral=True)
            return

        remove_pending_invite(team_role.id, member.id)
        await interaction.response.send_message("You have accepted this invite.", ephemeral=True)
        await self._finish(interaction)

        tx_channel = guild.get_channel(TRANSACTIONS_ID)
        if tx_channel:
            await tx_channel.send(f"{member.mention} has joined **{team_role.name}**.")

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.red)
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.invited_id:
            await interaction.response.send_message("This invite is not for you.", ephemeral=True)
            return

        remove_pending_invite(self.team_role_id, self.invited_id)
        await interaction.response.send_message("You have denied this invite.", ephemeral=True)
        await self._finish(interaction)


class InviteUserSelectView(discord.ui.View):
    def __init__(self, requester_id: int, team_role_id: int, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.requester_id = requester_id
        self.team_role_id = team_role_id

        selector = discord.ui.UserSelect(
            placeholder="Select a player to invite...",
            min_values=1,
            max_values=1,
        )
        selector.callback = self.on_select
        self.add_item(selector)
        self.user_select = selector

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("You can’t use this menu.", ephemeral=True)
            return False
        return True

    async def on_select(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("Guild not found.", ephemeral=True)
            return

        team_role = guild.get_role(self.team_role_id)
        if not team_role:
            await interaction.response.send_message("Team role not found.", ephemeral=True)
            return

        target = self.user_select.values[0]
        if not isinstance(target, discord.Member):
            target = guild.get_member(target.id)
        if not target:
            await interaction.response.send_message("Could not find that member.", ephemeral=True)
            return

        if team_role in target.roles:
            await interaction.response.send_message(
                f"{target.mention} is already on {team_role.mention}.",
                ephemeral=True,
            )
            return

        if find_single_team_for_member(guild, target):
            await interaction.response.send_message(
                f"{target.mention} is already on a team.",
                ephemeral=True,
            )
            return

        add_pending_invite(team_role.id, target.id)
        view = InviteDMView(guild.id, team_role.id, interaction.user.id, target.id)
        text = (
            f"# You have been invited to {team_role.name}\n"
            f"{interaction.user.mention} invited you to join {team_role.name}."
        )

        try:
            await target.send(text, view=view)
        except discord.Forbidden:
            remove_pending_invite(team_role.id, target.id)
            await interaction.response.send_message(
                f"Could not DM {target.mention}; their DMs may be closed.",
                ephemeral=True,
            )
            return

        await interaction.response.edit_message(
            content=f"Invite sent to {target.mention}. Ask them to check their DMs.",
            view=None,
        )


# ---------------- ROSTER UI ----------------
class TeamRosterView(discord.ui.View):
    def __init__(
        self,
        options: list[discord.SelectOption],
        requester_id: int,
        timeout: float = 60,
    ):
        super().__init__(timeout=timeout)
        self.requester_id = requester_id
        self.select = discord.ui.Select(
            placeholder="Choose a team...",
            min_values=1,
            max_values=1,
            options=options,
        )
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "You are not allowed to use this menu.",
                ephemeral=True,
            )
            return False
        return True

    async def select_callback(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("Guild not found.", ephemeral=True)
            return

        team_role = guild.get_role(int(self.select.values[0]))
        if not team_role:
            await interaction.response.send_message("Team role not found.", ephemeral=True)
            return

        captain_role = guild.get_role(CAPTAIN_ROLE_ID)
        cocap_role = guild.get_role(CO_CAPTAIN_ROLE_ID)
        player_role = guild.get_role(TEAM_PLAYER_ROLE_ID)

        members = list(team_role.members)
        captains = [m for m in members if role_in(m, captain_role)][:1]
        cocaptains = [m for m in members if role_in(m, cocap_role)][:2]
        players = [
            m for m in members
            if role_in(m, player_role)
            and not role_in(m, captain_role)
            and not role_in(m, cocap_role)
        ]
        shown_players = players[:10]

        invites = load_invites().get(str(team_role.id), [])
        pending = [
            member.mention
            for uid in invites
            if (member := guild.get_member(int(uid))) is not None
        ]

        def block(title: str, people: list[discord.Member]) -> str:
            if not people:
                return f"{title}:\n> • None\n\n"
            return f"{title}:\n" + "".join(f"> • {m.mention}\n" for m in people) + "\n"

        text = (
            f"# ROSTER OF {team_role.name}\n\n"
            + block("Captain", captains)
            + block("Co-Captains", cocaptains)
            + "Players:\n"
        )
        text += "".join(f"> • {m.mention}\n" for m in shown_players) if shown_players else "> • None\n"
        text += f"\n{len(shown_players)}/10\n\nPending Invites:\n"
        text += ", ".join(pending) if pending else "None"

        await interaction.response.edit_message(content=text, view=None)


# ---------------- FAQ ROLE UI ----------------
class FAQRoleView(discord.ui.View):
    def __init__(self, timeout: float = 0):
        super().__init__(timeout=timeout)

    async def _toggle_role(
        self,
        interaction: discord.Interaction,
        role_id: int,
        role_name: str,
    ) -> None:
        guild = interaction.guild
        member = guild.get_member(interaction.user.id) if guild else None
        role = guild.get_role(role_id) if guild else None

        if not guild or not member:
            await interaction.response.send_message("Guild error.", ephemeral=True)
            return
        if not role:
            await interaction.response.send_message(
                f"{role_name} role is not configured correctly.",
                ephemeral=True,
            )
            return

        try:
            if role in member.roles:
                await member.remove_roles(role, reason="FAQ role toggle")
                response = f"Removed **{role_name}**."
            else:
                await member.add_roles(role, reason="FAQ role toggle")
                response = f"Added **{role_name}**."
        except discord.HTTPException as exc:
            response = f"Role update failed: {exc}"

        await interaction.response.send_message(response, ephemeral=True)

    @discord.ui.button(label="🎥 Stream Watcher", style=discord.ButtonStyle.blurple)
    async def stream_watcher(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._toggle_role(interaction, STREAM_WATCHER_ROLE_ID, "Stream Watcher")

    @discord.ui.button(label="🚀 Unborn Captain", style=discord.ButtonStyle.blurple)
    async def unborn_captain(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._toggle_role(interaction, UNBORN_CAPTAIN_ROLE_ID, "Unborn Captain")

    @discord.ui.button(label="🎉 Event Ping", style=discord.ButtonStyle.blurple)
    async def event_ping(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._toggle_role(interaction, EVENT_PING_ROLE_ID, "Event Ping")


# ---------------- MATCH ACCEPTANCE / ASSIGNMENTS ----------------
class AssignmentView(discord.ui.View):
    def __init__(
        self,
        week: str,
        time_str: str,
        match_times_msg_id: int | None,
        ping_line: str,
        team1_name: str,
        team2_name: str,
        timeout: float | None = None,
    ):
        super().__init__(timeout=timeout)
        self.week = week
        self.time_str = time_str
        self.match_times_msg_id = match_times_msg_id
        self.ping_line = ping_line
        self.team1_name = team1_name
        self.team2_name = team2_name
        self.caster_id: int | None = None
        self.ref_id: int | None = None


        for label, custom_id, callback, style in (
            ("Claim Caster", "claim_caster", self.claim_caster, discord.ButtonStyle.blurple),
            ("Claim Referee", "claim_ref", self.claim_ref, discord.ButtonStyle.blurple),
            ("Unclaim", "unclaim", self.unclaim, discord.ButtonStyle.red),
        ):
            button = discord.ui.Button(label=label, custom_id=custom_id, style=style)
            button.callback = callback
            self.add_item(button)

    def _is_caster(self, member: discord.Member) -> bool:
        return role_in(member, member.guild.get_role(HEAD_CASTER_ROLE_ID)) or role_in(
            member, member.guild.get_role(CASTER_ROLE_ID)
        )

    def _is_ref(self, member: discord.Member) -> bool:
        return role_in(member, member.guild.get_role(HEAD_REF_ROLE_ID)) or role_in(
            member, member.guild.get_role(REF_ROLE_ID)
        )

    async def claim_caster(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        member = guild.get_member(interaction.user.id) if guild else None
        if not member:
            await interaction.response.send_message("Guild error.", ephemeral=True)
            return
        if not self._is_caster(member):
            await interaction.response.send_message("You need a Caster role to claim this.", ephemeral=True)
            return
        if self.caster_id not in (None, member.id):
            await interaction.response.send_message("Caster has already been claimed.", ephemeral=True)
            return

        self.caster_id = member.id
        await interaction.response.send_message("You have claimed Caster.", ephemeral=True)
        await self._update_messages(guild, interaction.message)

    async def claim_ref(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        member = guild.get_member(interaction.user.id) if guild else None
        if not member:
            await interaction.response.send_message("Guild error.", ephemeral=True)
            return
        if not self._is_ref(member):
            await interaction.response.send_message("You need a Referee role to claim this.", ephemeral=True)
            return
        if self.ref_id not in (None, member.id):
            await interaction.response.send_message("Referee has already been claimed.", ephemeral=True)
            return

        self.ref_id = member.id
        await interaction.response.send_message("You have claimed Referee.", ephemeral=True)
        await self._update_messages(guild, interaction.message)

    async def unclaim(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("Guild error.", ephemeral=True)
            return

        changed = False
        if self.caster_id == interaction.user.id:
            self.caster_id = None
            changed = True
        if self.ref_id == interaction.user.id:
            self.ref_id = None
            changed = True

        if not changed:
            await interaction.response.send_message(
                "You don't currently hold an assignment on this match.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message("Your assignment has been unclaimed.", ephemeral=True)
        await self._update_messages(guild, interaction.message)

    async def _update_messages(
        self,
        guild: discord.Guild,
        assignments_msg: discord.Message,
    ) -> None:
        def mention(uid: int | None) -> str:
            member = guild.get_member(uid) if uid else None
            return member.mention if member else "Unassigned"

        assignment = (
            f"**{self.team1_name} vs {self.team2_name}**\n"
            f"> **{self.week}**\n"
            f"> Time: {self.time_str}\n"
            f"> Referee: {mention(self.ref_id)}\n"
            f"> Caster: {mention(self.caster_id)}"
        )
        await assignments_msg.edit(
            content=(self.ping_line + "\n" if self.ping_line else "") + assignment,
            view=self,
        )

        if self.match_times_msg_id:
            channel = guild.get_channel(MATCH_TIMES_CHANNEL_ID)
            if channel:
                try:
                    message = await channel.fetch_message(self.match_times_msg_id)
                    await message.edit(content=assignment)
                except discord.NotFound:
                    pass
                except discord.HTTPException:
                    log.exception("Could not update match-time message.")


async def schedule_match_reminders(
    bot: commands.Bot,
    guild: discord.Guild,
    channel_id: int,
    match_at: datetime,
    team1_mention: str,
    team2_mention: str,
    assignment_view: AssignmentView,
) -> None:
    channel = guild.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        return

    now = datetime.now(EASTERN)
    reminder_at = match_at - timedelta(minutes=15)
    code_at = match_at - timedelta(minutes=5)

    if reminder_at > now:
        await asyncio.sleep((reminder_at - now).total_seconds())
        await channel.send(
            f"{team1_mention} {team2_mention}\n"
            "# Scrim Reminder\n"
            f"The scrim starts <t:{int(match_at.timestamp())}:F>."
        )

    now = datetime.now(EASTERN)
    if code_at > now:
        await asyncio.sleep((code_at - now).total_seconds())

    code = f"NC{random.randint(1000, 9999)}"
    await channel.send(
        f"# Match code: `{code}`\n"
        "You have 15 minutes to join."
    )

    for user_id in (assignment_view.ref_id, assignment_view.caster_id):
        if not user_id:
            continue
        user = bot.get_user(user_id)
        if user is None:
            try:
                user = await bot.fetch_user(user_id)
            except discord.HTTPException:
                log.exception("Could not fetch assigned match staff member.")
                continue

        try:
            await user.send(
                f"Your scrim code is `{code}`. "
                f"Match starts <t:{int(match_at.timestamp())}:F>."
            )
        except discord.Forbidden:
            log.warning("Could not DM match code to user %s.", user_id)



class MatchAcceptView(discord.ui.View):
    def __init__(
        self,
        bot_: commands.Bot,
        week: str,
        time_str: str,
        header: str,
        team1_id: int,
        team2_id: int,
        match_at: datetime,
        team1_mention: str,
        team2_mention: str,
        timeout: float = 900,
    ):
        super().__init__(timeout=timeout)
        self.bot = bot_
        self.week = week
        self.time_str = time_str
        self.header = header
        self.team1_id = team1_id
        self.team2_id = team2_id
        self.match_at = match_at
        self.team1_mention = team1_mention
        self.team2_mention = team2_mention

        self.team1_accepted = False
        self.team2_accepted = False
        self.accept_channel_id: int | None = None
        self.accept_message_id: int | None = None

        first = discord.ui.Button(
            label="Accept for Team 1",
            style=discord.ButtonStyle.green,
        )
        second = discord.ui.Button(
            label="Accept for Team 2",
            style=discord.ButtonStyle.green,
        )
        first.callback = self.accept_team1
        second.callback = self.accept_team2
        self.add_item(first)
        self.add_item(second)

    def _is_team_staff(self, member: discord.Member, team_role_id: int) -> bool:
        team = member.guild.get_role(team_role_id)
        return bool(
            team
            and team in member.roles
            and (
                role_in(member, member.guild.get_role(CAPTAIN_ROLE_ID))
                or role_in(member, member.guild.get_role(CO_CAPTAIN_ROLE_ID))
                or role_in(member, member.guild.get_role(EXECUTIVE_ROLE_ID))
            )
        )

    async def _handle_accept(
        self,
        interaction: discord.Interaction,
        team_index: int,
    ) -> None:
        guild = interaction.guild
        member = guild.get_member(interaction.user.id) if guild else None

        if not guild or not member:
            await interaction.response.send_message("Guild error.", ephemeral=True)
            return

        team_id = self.team1_id if team_index == 1 else self.team2_id
        if not self._is_team_staff(member, team_id):
            await interaction.response.send_message(
                "Only that team's captain, co-captain, or an executive can accept.",
                ephemeral=True,
            )
            return

        if team_index == 1:
            if self.team1_accepted:
                await interaction.response.send_message(
                    "Team 1 has already accepted.",
                    ephemeral=True,
                )
                return
            self.team1_accepted = True
        else:
            if self.team2_accepted:
                await interaction.response.send_message(
                    "Team 2 has already accepted.",
                    ephemeral=True,
                )
                return
            self.team2_accepted = True

        await interaction.response.send_message(
            f"Team {team_index} has accepted.",
            ephemeral=True,
        )

        if self.team1_accepted and self.team2_accepted:
            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True
            await self._finalize_and_post(guild)

    async def accept_team1(self, interaction: discord.Interaction) -> None:
        await self._handle_accept(interaction, 1)

    async def accept_team2(self, interaction: discord.Interaction) -> None:
        await self._handle_accept(interaction, 2)

    async def _finalize_and_post(self, guild: discord.Guild) -> None:
        if self.accept_channel_id and self.accept_message_id:
            channel = guild.get_channel(self.accept_channel_id)
            if isinstance(channel, discord.TextChannel):
                try:
                    message = await channel.fetch_message(self.accept_message_id)
                    await message.edit(view=self)
                except discord.HTTPException:
                    log.exception("Could not disable match acceptance buttons.")

        initial = (
            f"{self.header}\n" if self.header else ""
        ) + (
            f"> **{self.week}**\n"
            f"> Time: {self.time_str}\n"
            "> Referee: Unassigned\n"
            "> Caster: Unassigned"
        )

        match_times_id = None
        match_times_channel = guild.get_channel(MATCH_TIMES_CHANNEL_ID)
        if isinstance(match_times_channel, discord.TextChannel):
            match_times_message = await match_times_channel.send(initial)
            match_times_id = match_times_message.id

        assignments_channel = guild.get_channel(ASSIGNMENTS_CHANNEL_ID)
        if not isinstance(assignments_channel, discord.TextChannel):
            log.error("Assignments channel %s was not found.", ASSIGNMENTS_CHANNEL_ID)
            return

        roles = [
            guild.get_role(HEAD_REF_ROLE_ID),
            guild.get_role(REF_ROLE_ID),
            guild.get_role(HEAD_CASTER_ROLE_ID),
            guild.get_role(CASTER_ROLE_ID),
        ]
        ping_line = " ".join(role.mention for role in roles if role)

        assignment_content = (
            f"{self.header}\n" if self.header else ""
        ) + initial.split("\n", 1)[-1]

        if ping_line:
            assignment_content = f"{ping_line}\n{assignment_content}"

        assignment_view = AssignmentView(
            week=self.week,
            time_str=self.time_str,
            match_times_msg_id=match_times_id,
            ping_line=ping_line,
            team1_name=self.team1_mention,
            team2_name=self.team2_mention,
        )
        await assignments_channel.send(
            assignment_content,
            view=assignment_view,
        )

        # Reminders go to the channel where /submit-time was used.
        if self.accept_channel_id:
            self.bot.loop.create_task(
                schedule_match_reminders(
                    bot=self.bot,
                    guild=guild,
                    channel_id=self.accept_channel_id,
                    match_at=self.match_at,
                    team1_mention=self.team1_mention,
                    team2_mention=self.team2_mention,
                    assignment_view=assignment_view,
                )
            )


# ---------------- TEAM MANAGER COG ----------------
class TeamManager(commands.Cog):
    def __init__(self, bot_: commands.Bot):
        self.bot = bot_

    async def _roster_lock_block(
        self,
        interaction: discord.Interaction,
        team: discord.Role,
    ) -> bool:
        if interaction.guild and is_roster_locked(interaction.guild, team):
            message = "Roster lock has been enabled."
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
            return True
        return False

    async def _admin_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "You must be an administrator to use this command.",
                ephemeral=True,
            )
            return False
        return True

    # /create-team
    @app_commands.guilds(GUILD_OBJ)
    @app_commands.command(name="create-team", description="Create a team role and assign its captain.")
    @app_commands.describe(team_name="Team name", captain="Captain member", color_code="Hex color, e.g. FF00FF")
    async def create_team(
        self,
        interaction: discord.Interaction,
        team_name: str,
        captain: discord.Member,
        color_code: str,
    ):
        if not await self._admin_check(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if not guild:
            await interaction.followup.send("Must be used in a server.", ephemeral=True)
            return

        code = color_code.strip().lstrip("#")
        if len(code) != 6 or any(c not in "0123456789abcdefABCDEF" for c in code):
            await interaction.followup.send("Hex color must be 6 digits, such as FF00FF.", ephemeral=True)
            return

        try:
            team = await guild.create_role(
                name=team_name,
                colour=discord.Color(int(code, 16)),
                reason=f"Team created by {interaction.user}",
            )
            roles = [team]
            captain_role = guild.get_role(CAPTAIN_ROLE_ID)
            if captain_role:
                roles.append(captain_role)
            await captain.add_roles(*roles, reason=f"Assigned captain of {team_name}")
        except discord.HTTPException as exc:
            await interaction.followup.send(f"Could not create team: {exc}", ephemeral=True)
            return

        teams = load_teams()
        teams.append({"role_id": team.id, "name": team_name})
        save_teams(teams)

        channel = guild.get_channel(TRANSACTIONS_ID)
        if channel:
            await channel.send(f"**New team created:** {team.mention}\nCaptain: {captain.mention}")
        await interaction.followup.send("Team created.", ephemeral=True)

    # /change-color-code
    @app_commands.guilds(GUILD_OBJ)
    @app_commands.command(name="change-color-code", description="Change a team's role color.")
    @app_commands.describe(team="Team role", color_code="New hex color, e.g. 00FF00")
    async def change_color_code(
        self,
        interaction: discord.Interaction,
        team: discord.Role,
        color_code: str,
    ):
        if not await self._admin_check(interaction):
            return
        code = color_code.strip().lstrip("#")
        if len(code) != 6 or any(c not in "0123456789abcdefABCDEF" for c in code):
            await interaction.response.send_message("Hex color must be 6 digits.", ephemeral=True)
            return

        old_code = f"{team.colour.value:06X}"
        new_code = code.upper()
        try:
            await team.edit(colour=discord.Color(int(code, 16)), reason=f"Color changed by {interaction.user}")
        except discord.HTTPException as exc:
            await interaction.response.send_message(f"Could not change color: {exc}", ephemeral=True)
            return

        if interaction.guild:
            channel = interaction.guild.get_channel(TRANSACTIONS_ID)
            if channel:
                await channel.send(
                    f"{team.mention} changed color from `{old_code}` to `{new_code}`."
                )
        await interaction.response.send_message(
            f"Color changed from `{old_code}` to `{new_code}`.",
            ephemeral=True,
        )

    # /change-captain
    @app_commands.guilds(GUILD_OBJ)
    @app_commands.command(name="change-captain", description="Change your team's captain.")
    @app_commands.describe(member="New captain; must already be on your team")
    async def change_captain(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        me = guild.get_member(interaction.user.id) if guild else None
        captain_role = guild.get_role(CAPTAIN_ROLE_ID) if guild else None
        if not guild or not me or not role_in(me, captain_role):
            await interaction.followup.send("Only a team captain can use this command.", ephemeral=True)
            return

        team = find_single_team_for_member(guild, me)
        if not team:
            await interaction.followup.send("You must be on exactly one team.", ephemeral=True)
            return
        if await self._roster_lock_block(interaction, team):
            return
        if team not in member.roles:
            await interaction.followup.send(f"{member.mention} must already be on {team.mention}.", ephemeral=True)
            return

        try:
            for old in list(team.members):
                if old.id != member.id and role_in(old, captain_role):
                    await old.remove_roles(captain_role, reason=f"Captain changed by {interaction.user}")
            if captain_role not in member.roles:
                await member.add_roles(captain_role, reason=f"Promoted by {interaction.user}")
        except discord.HTTPException as exc:
            await interaction.followup.send(f"Could not change captain: {exc}", ephemeral=True)
            return

        channel = guild.get_channel(TRANSACTIONS_ID)
        if channel:
            await channel.send(f"{team.mention} captain changed to {member.mention}.")
        await interaction.followup.send(f"Captain changed to {member.mention}.", ephemeral=True)

    # /invite
    @app_commands.guilds(GUILD_OBJ)
    @app_commands.command(name="invite", description="Invite a player to your team.")
    async def invite_player(self, interaction: discord.Interaction):
        guild = interaction.guild
        me = guild.get_member(interaction.user.id) if guild else None
        if not guild or not me:
            await interaction.response.send_message("Must be used in a server.", ephemeral=True)
            return

        if not (
            role_in(me, guild.get_role(CAPTAIN_ROLE_ID))
            or role_in(me, guild.get_role(CO_CAPTAIN_ROLE_ID))
        ):
            await interaction.response.send_message("Only captains and co-captains can invite.", ephemeral=True)
            return

        team = find_single_team_for_member(guild, me)
        if not team:
            await interaction.response.send_message("You must be on exactly one team.", ephemeral=True)
            return
        if await self._roster_lock_block(interaction, team):
            return

        await interaction.response.send_message(
            "Select a player to invite:",
            view=InviteUserSelectView(interaction.user.id, team.id),
            ephemeral=True,
        )

    # /leave
    @app_commands.guilds(GUILD_OBJ)
    @app_commands.command(name="leave", description="Leave your current team.")
    async def leave(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        member = guild.get_member(interaction.user.id) if guild else None
        if not guild or not member:
            await interaction.followup.send("Must be used in a server.", ephemeral=True)
            return

        team = find_single_team_for_member(guild, member)
        if not team:
            await interaction.followup.send("You are not on exactly one team.", ephemeral=True)
            return
        if is_roster_locked(guild, team):
            await interaction.followup.send("Roster lock has been enabled.", ephemeral=True)
            return

        roles = [
            team,
            guild.get_role(CAPTAIN_ROLE_ID),
            guild.get_role(CO_CAPTAIN_ROLE_ID),
            guild.get_role(EXECUTIVE_ROLE_ID),
            guild.get_role(TEAM_PLAYER_ROLE_ID),
        ]
        try:
            await member.remove_roles(
                *(role for role in roles if role and role in member.roles),
                reason="Left team via /leave",
            )
        except discord.HTTPException as exc:
            await interaction.followup.send(f"Could not remove team roles: {exc}", ephemeral=True)
            return

        channel = guild.get_channel(TRANSACTIONS_ID)
        if channel:
            await channel.send(f"{member.mention} has left **{team.name}**.")
        await interaction.followup.send("You have left your team.", ephemeral=True)

    # /list-teams
    @app_commands.guilds(GUILD_OBJ)
    @app_commands.command(name="list-teams", description="List all teams.")
    async def list_teams(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if not guild:
            await interaction.followup.send("Must be used in a server.", ephemeral=True)
            return

        entries = load_teams()
        if not entries:
            await interaction.followup.send("No teams found.", ephemeral=True)
            return

        lines = ["Below is a list of teams:"]
        for entry in entries:
            role_id = entry.get("role_id")
            role = guild.get_role(int(role_id)) if role_id else None
            lines.append(f"> {role.mention}" if role else f"> {entry.get('name', 'Unknown Team')} (role not found)")
        await interaction.followup.send("\n".join(lines), ephemeral=True)

    # /roster
    @app_commands.guilds(GUILD_OBJ)
    @app_commands.command(name="roster", description="View a team's roster.")
    async def roster(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if not guild:
            await interaction.followup.send("Must be used in a server.", ephemeral=True)
            return

        options = []
        for entry in load_teams():
            role_id = entry.get("role_id")
            role = guild.get_role(int(role_id)) if role_id else None
            if role:
                label = entry.get("name", role.name)[:100]
                options.append(discord.SelectOption(
                    label=label,
                    value=str(role.id),
                    description=f"View roster for {label}"[:100],
                ))

        if not options:
            await interaction.followup.send("No valid team roles found.", ephemeral=True)
            return

        await interaction.followup.send(
            "Select a team to view its roster:",
            view=TeamRosterView(options[:25], interaction.user.id),
            ephemeral=True,
        )

    # /player-info
    @app_commands.guilds(GUILD_OBJ)
    @app_commands.command(name="player-info", description="View a player's league information.")
    @app_commands.describe(member="Player to look up; leave empty to view yourself")
    async def player_info(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if not guild:
            await interaction.followup.send("Must be used in a server.", ephemeral=True)
            return
        member = member or guild.get_member(interaction.user.id)
        if not member:
            await interaction.followup.send("Could not find that member.", ephemeral=True)
            return

        current = find_single_team_for_member(guild, member)
        entry = load_player_history().get(str(member.id), {})
        past = entry.get("past_teams", [])
        if not current and not past:
            await interaction.followup.send(
                f"{member.mention} does not have league information.",
                ephemeral=True,
            )
            return

        lines = [
            f"# League Information for {member.mention}",
            f"Current Team: {current.mention if current else 'None'}",
            "Past Teams:",
        ]
        lines.extend(f"> {name}" for name in past) if past else lines.append("> None")
        await interaction.followup.send("\n".join(lines), ephemeral=True)

    # /add-executive
    @app_commands.guilds(GUILD_OBJ)
    @app_commands.command(name="add-executive", description="Promote a roster member to executive.")
    @app_commands.describe(executive="Member to promote; must already be on your team")
    async def add_executive(self, interaction: discord.Interaction, executive: discord.Member):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        me = guild.get_member(interaction.user.id) if guild else None
        captain = guild.get_role(CAPTAIN_ROLE_ID) if guild else None
        exec_role = guild.get_role(EXECUTIVE_ROLE_ID) if guild else None
        if not guild or not me or not role_in(me, captain):
            await interaction.followup.send("Only captains can use this command.", ephemeral=True)
            return
        if not exec_role:
            await interaction.followup.send("Executive role is not configured.", ephemeral=True)
            return

        team = find_single_team_for_member(guild, me)
        if not team or team not in executive.roles:
            await interaction.followup.send("The member must be on your team.", ephemeral=True)
            return
        if await self._roster_lock_block(interaction, team):
            return
        if exec_role in executive.roles:
            await interaction.followup.send("That member is already an executive.", ephemeral=True)
            return

        try:
            await executive.add_roles(exec_role, reason=f"Promoted by {interaction.user}")
        except discord.HTTPException as exc:
            await interaction.followup.send(f"Could not promote member: {exc}", ephemeral=True)
            return
        channel = guild.get_channel(TRANSACTIONS_ID)
        if channel:
            await channel.send(f"{executive.mention} was promoted to executive by {interaction.user.mention}.")
        await interaction.followup.send("Executive added.", ephemeral=True)

    # /remove-executive
    @app_commands.guilds(GUILD_OBJ)
    @app_commands.command(name="remove-executive", description="Demote your team's executive.")
    async def remove_executive(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        me = guild.get_member(interaction.user.id) if guild else None
        captain = guild.get_role(CAPTAIN_ROLE_ID) if guild else None
        exec_role = guild.get_role(EXECUTIVE_ROLE_ID) if guild else None
        player_role = guild.get_role(TEAM_PLAYER_ROLE_ID) if guild else None
        if not guild or not me or not role_in(me, captain):
            await interaction.followup.send("Only captains can use this command.", ephemeral=True)
            return
        team = find_single_team_for_member(guild, me)
        if not team or not exec_role or not player_role:
            await interaction.followup.send("Team or roles are not configured correctly.", ephemeral=True)
            return
        if await self._roster_lock_block(interaction, team):
            return

        target = next((m for m in team.members if exec_role in m.roles), None)
        if not target:
            await interaction.followup.send("No executive found on your team.", ephemeral=True)
            return
        try:
            await target.remove_roles(exec_role, reason=f"Demoted by {interaction.user}")
            if player_role not in target.roles:
                await target.add_roles(player_role, reason=f"Demoted by {interaction.user}")
        except discord.HTTPException as exc:
            await interaction.followup.send(f"Could not demote executive: {exc}", ephemeral=True)
            return

        channel = guild.get_channel(TRANSACTIONS_ID)
        if channel:
            await channel.send(f"{target.mention} was demoted from executive by {interaction.user.mention}.")
        await interaction.followup.send("Executive demoted.", ephemeral=True)

    # /add-co-captain
    @app_commands.guilds(GUILD_OBJ)
    @app_commands.command(name="add-co-captain", description="Promote a roster member to co-captain (max 2).")
    @app_commands.describe(member="Member to promote")
    async def add_co_captain(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        me = guild.get_member(interaction.user.id) if guild else None
        captain = guild.get_role(CAPTAIN_ROLE_ID) if guild else None
        cocap = guild.get_role(CO_CAPTAIN_ROLE_ID) if guild else None
        if not guild or not me or not role_in(me, captain):
            await interaction.followup.send("Only captains can use this command.", ephemeral=True)
            return
        team = find_single_team_for_member(guild, me)
        if not team or not cocap:
            await interaction.followup.send("Team or Co-Captain role is not configured.", ephemeral=True)
            return
        if await self._roster_lock_block(interaction, team):
            return
        if team not in member.roles:
            await interaction.followup.send("That member must already be on your team.", ephemeral=True)
            return
        current = [m for m in team.members if cocap in m.roles]
        if cocap in member.roles:
            await interaction.followup.send("That member is already a Co-Captain.", ephemeral=True)
            return
        if len(current) >= 2:
            await interaction.followup.send("Your team already has 2 Co-Captains.", ephemeral=True)
            return

        try:
            await member.add_roles(cocap, reason=f"Promoted by {interaction.user}")
        except discord.HTTPException as exc:
            await interaction.followup.send(f"Could not promote member: {exc}", ephemeral=True)
            return
        channel = guild.get_channel(TRANSACTIONS_ID)
        if channel:
            await channel.send(f"{member.mention} was promoted to Co-Captain by {interaction.user.mention}.")
        await interaction.followup.send("Co-Captain added.", ephemeral=True)

    # /remove-co-captain
    @app_commands.guilds(GUILD_OBJ)
    @app_commands.command(name="remove-co-captain", description="Demote a Co-Captain.")
    @app_commands.describe(member="Co-Captain to demote")
    async def remove_co_captain(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        me = guild.get_member(interaction.user.id) if guild else None
        captain = guild.get_role(CAPTAIN_ROLE_ID) if guild else None
        cocap = guild.get_role(CO_CAPTAIN_ROLE_ID) if guild else None
        player = guild.get_role(TEAM_PLAYER_ROLE_ID) if guild else None
        if not guild or not me or not role_in(me, captain):
            await interaction.followup.send("Only captains can use this command.", ephemeral=True)
            return
        team = find_single_team_for_member(guild, me)
        if not team or not cocap or not player:
            await interaction.followup.send("Team or roles are not configured.", ephemeral=True)
            return
        if await self._roster_lock_block(interaction, team):
            return
        if team not in member.roles or cocap not in member.roles:
            await interaction.followup.send("That member is not a Co-Captain on your team.", ephemeral=True)
            return

        try:
            await member.remove_roles(cocap, reason=f"Demoted by {interaction.user}")
            if player not in member.roles:
                await member.add_roles(player, reason=f"Demoted by {interaction.user}")
        except discord.HTTPException as exc:
            await interaction.followup.send(f"Could not demote member: {exc}", ephemeral=True)
            return
        channel = guild.get_channel(TRANSACTIONS_ID)
        if channel:
            await channel.send(f"{member.mention} was demoted from Co-Captain by {interaction.user.mention}.")
        await interaction.followup.send("Co-Captain demoted.", ephemeral=True)

    # /disband
    @app_commands.guilds(GUILD_OBJ)
    @app_commands.command(name="disband", description="Disband a team.")
    @app_commands.describe(team="Team role to disband")
    async def disband(self, interaction: discord.Interaction, team: discord.Role):
        if not await self._admin_check(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if not guild:
            await interaction.followup.send("Must be used in a server.", ephemeral=True)
            return

        roles = [
            team,
            guild.get_role(CAPTAIN_ROLE_ID),
            guild.get_role(CO_CAPTAIN_ROLE_ID),
            guild.get_role(EXECUTIVE_ROLE_ID),
            guild.get_role(TEAM_PLAYER_ROLE_ID),
        ]
        members = list(team.members)
        for member in members:
            try:
                await member.remove_roles(
                    *(role for role in roles if role and role in member.roles),
                    reason=f"Team {team.name} disbanded",
                )
            except discord.HTTPException:
                log.exception("Could not remove roles from %s", member)

        history = load_player_history()
        for member in members:
            entry = history.setdefault(str(member.id), {})
            past = entry.setdefault("past_teams", [])
            if team.name not in past:
                past.append(team.name)
        save_player_history(history)

        try:
            await team.delete(reason="Team disbanded")
        except discord.HTTPException as exc:
            await interaction.followup.send(f"Roles removed, but team role could not be deleted: {exc}", ephemeral=True)
            return

        save_teams([t for t in load_teams() if str(t.get("role_id")) != str(team.id)])
        channel = guild.get_channel(TRANSACTIONS_ID)
        if channel:
            await channel.send(f"**{team.name}** has been disbanded.")
        await interaction.followup.send("Team disbanded.", ephemeral=True)

    # /disband-all
    @app_commands.guilds(GUILD_OBJ)
    @app_commands.command(name="disband-all", description="Disband all teams.")
    async def disband_all(self, interaction: discord.Interaction):
        if not await self._admin_check(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if not guild:
            await interaction.followup.send("Must be used in a server.", ephemeral=True)
            return

        team_roles = get_team_roles_from_file(guild)
        affected = {member for role in team_roles for member in role.members}
        shared_roles = [
            guild.get_role(CAPTAIN_ROLE_ID),
            guild.get_role(CO_CAPTAIN_ROLE_ID),
            guild.get_role(EXECUTIVE_ROLE_ID),
            guild.get_role(TEAM_PLAYER_ROLE_ID),
        ]

        history = load_player_history()
        for member in affected:
            entry = history.setdefault(str(member.id), {})
            past = entry.setdefault("past_teams", [])
            for role in team_roles:
                if role.name not in past:
                    past.append(role.name)
            remove = [role for role in team_roles if role in member.roles]
            remove += [role for role in shared_roles if role and role in member.roles]
            try:
                if remove:
                    await member.remove_roles(*remove, reason="All teams disbanded")
            except discord.HTTPException:
                log.exception("Could not remove roles from %s", member)
        save_player_history(history)

        for role in team_roles:
            try:
                await role.delete(reason="All teams disbanded")
            except discord.HTTPException:
                log.exception("Could not delete team role %s", role)

        save_teams([])
        channel = guild.get_channel(TRANSACTIONS_ID)
        if channel:
            await channel.send("All teams have been disbanded.")
        await interaction.followup.send("All teams disbanded.", ephemeral=True)

    # Roster locks
    @app_commands.guilds(GUILD_OBJ)
    @app_commands.command(name="roster-lock", description="Lock roster changes for one team.")
    @app_commands.describe(team="Team role")
    async def roster_lock(self, interaction: discord.Interaction, team: discord.Role):
        if not await self._admin_check(interaction):
            return
        locks = load_roster_locks()
        locks[str(team.id)] = True
        save_roster_locks(locks)
        channel = interaction.guild.get_channel(TRANSACTIONS_ID) if interaction.guild else None
        if channel:
            await channel.send(f"Roster lock enabled for {team.mention}.")
        await interaction.response.send_message("Roster lock enabled.", ephemeral=True)

    @app_commands.guilds(GUILD_OBJ)
    @app_commands.command(name="roster-lock-all", description="Lock roster changes for all teams.")
    async def roster_lock_all(self, interaction: discord.Interaction):
        if not await self._admin_check(interaction):
            return
        locks = load_roster_locks()
        locks["ALL"] = True
        save_roster_locks(locks)
        channel = interaction.guild.get_channel(TRANSACTIONS_ID) if interaction.guild else None
        if channel:
            await channel.send("Roster lock enabled for all teams.")
        await interaction.response.send_message("Roster lock enabled for all teams.", ephemeral=True)

    @app_commands.guilds(GUILD_OBJ)
    @app_commands.command(name="unlock-roster", description="Unlock roster changes for one team.")
    @app_commands.describe(team="Team role")
    async def unlock_roster(self, interaction: discord.Interaction, team: discord.Role):
        if not await self._admin_check(interaction):
            return
        locks = load_roster_locks()
        locks[str(team.id)] = False
        save_roster_locks(locks)
        channel = interaction.guild.get_channel(TRANSACTIONS_ID) if interaction.guild else None
        if channel:
            await channel.send(f"Roster lock disabled for {team.mention}.")
        await interaction.response.send_message("Roster unlocked for that team.", ephemeral=True)

    @app_commands.guilds(GUILD_OBJ)
    @app_commands.command(name="unlock-roster-all", description="Unlock roster changes for all teams.")
    async def unlock_roster_all(self, interaction: discord.Interaction):
        if not await self._admin_check(interaction):
            return
        locks = load_roster_locks()
        locks["ALL"] = False
        for key in list(locks):
            if key != "ALL":
                locks[key] = False
        save_roster_locks(locks)
        channel = interaction.guild.get_channel(TRANSACTIONS_ID) if interaction.guild else None
        if channel:
            await channel.send("Roster locks disabled for all teams.")
        await interaction.response.send_message("Roster unlocked for all teams.", ephemeral=True)

    # /kick-player
    @app_commands.guilds(GUILD_OBJ)
    @app_commands.command(name="kick-player", description="Kick a player from your team.")
    @app_commands.describe(member="Player to kick")
    async def kick_player(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        me = guild.get_member(interaction.user.id) if guild else None
        if not guild or not me:
            await interaction.followup.send("Must be used in a server.", ephemeral=True)
            return
        if not (
            role_in(me, guild.get_role(CAPTAIN_ROLE_ID))
            or role_in(me, guild.get_role(CO_CAPTAIN_ROLE_ID))
        ):
            await interaction.followup.send("Only captains and co-captains can use this.", ephemeral=True)
            return
        team = find_single_team_for_member(guild, me)
        if not team:
            await interaction.followup.send("You must be on exactly one team.", ephemeral=True)
            return
        if await self._roster_lock_block(interaction, team):
            return
        if team not in member.roles:
            await interaction.followup.send(f"{member.mention} is not on your team.", ephemeral=True)
            return

        remove = [team]
        player_role = guild.get_role(TEAM_PLAYER_ROLE_ID)
        if player_role and player_role in member.roles:
            remove.append(player_role)
        try:
            await member.remove_roles(*remove, reason=f"Kicked by {interaction.user}")
        except discord.HTTPException as exc:
            await interaction.followup.send(f"Could not kick player: {exc}", ephemeral=True)
            return
        channel = guild.get_channel(TRANSACTIONS_ID)
        if channel:
            await channel.send(f"{member.mention} was kicked from **{team.name}** by {interaction.user.mention}.")
        await interaction.followup.send(f"{member.mention} has been kicked from {team.mention}.", ephemeral=True)

    # /admin-add
    @app_commands.guilds(GUILD_OBJ)
    @app_commands.command(name="admin-add", description="Add a member to a team (admin only).")
    @app_commands.describe(member="Member to add", team="Team role")
    async def admin_add(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        team: discord.Role,
    ):
        if not await self._admin_check(interaction):
            return
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("Must be used in a server.", ephemeral=True)
            return
        player_role = guild.get_role(TEAM_PLAYER_ROLE_ID)
        if not player_role:
            await interaction.response.send_message("Team Player role is not configured.", ephemeral=True)
            return
        try:
            await member.add_roles(team, player_role, reason=f"Admin added by {interaction.user}")
        except discord.HTTPException as exc:
            await interaction.response.send_message(f"Could not add member: {exc}", ephemeral=True)
            return
        channel = guild.get_channel(TRANSACTIONS_ID)
        if channel:
            await channel.send(f"{interaction.user.mention} added {member.mention} to {team.mention}.")
        await interaction.response.send_message(f"Added {member.mention} to {team.mention}.", ephemeral=True)

    # /admin-kick
    @app_commands.guilds(GUILD_OBJ)
    @app_commands.command(name="admin-kick", description="Remove a member from a team (admin only).")
    @app_commands.describe(member="Member to remove", team="Team role")
    async def admin_kick(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        team: discord.Role,
    ):
        if not await self._admin_check(interaction):
            return
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("Must be used in a server.", ephemeral=True)
            return

        remove = [role for role in (
            team,
            guild.get_role(CAPTAIN_ROLE_ID),
            guild.get_role(CO_CAPTAIN_ROLE_ID),
            guild.get_role(TEAM_PLAYER_ROLE_ID),
        ) if role and role in member.roles]
        try:
            if remove:
                await member.remove_roles(*remove, reason=f"Admin kick by {interaction.user}")
        except discord.HTTPException as exc:
            await interaction.response.send_message(f"Could not remove member: {exc}", ephemeral=True)
            return
        channel = guild.get_channel(TRANSACTIONS_ID)
        if channel:
            await channel.send(f"{interaction.user.mention} removed {member.mention} from {team.mention}.")
        await interaction.response.send_message(f"Removed {member.mention} from {team.mention}.", ephemeral=True)


# ---------------- PUBLIC COMMANDS ----------------
@bot.tree.command(guild=GUILD_OBJ, name="info", description="Show information about the bot.")
async def info(interaction: discord.Interaction):
    embed = discord.Embed(
        title="CTA Transactions Bot – Command Guide",
        description="Public and team commands.",
        colour=discord.Colour.blurple(),
    )
    fields = [
        ("/info", "Show this command guide."),
        ("/player-info", "View a player's current and past league information."),
        ("/list-teams", "List registered teams."),
        ("/roster", "View a team's roster."),
        ("/standing", "View league standings."),
        ("/leave", "Leave your current team."),
        ("/invite", "Invite a player to your team."),
        ("/add-co-captain", "Promote a roster member to Co-Captain (max 2)."),
        ("/remove-co-captain", "Demote a Co-Captain."),
        ("/change-captain", "Change your team's captain."),
        ("/add-executive", "Promote a roster member to executive."),
        ("/remove-executive", "Demote your team's executive."),
        ("/kick-player", "Kick a player from your team."),
    ]
    for name, value in fields:
        embed.add_field(name=name, value=value, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(guild=GUILD_OBJ, name="admin-info", description="Show admin command guide.")
async def admin_info(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Only admins can use this.", ephemeral=True)
        return
    embed = discord.Embed(
        title="CTA Transactions Bot – Admin Commands",
        colour=discord.Colour.red(),
    )
    fields = [
        ("/create-team", "Create a team and assign its captain."),
        ("/change-color-code", "Change a team role's color."),
        ("/disband", "Disband one team."),
        ("/disband-all", "Disband all teams."),
        ("/admin-add", "Add a member to a team."),
        ("/admin-kick", "Remove a member and team-related roles."),
        ("/submit-time", "Post a match proposal and collect team acceptance."),
        ("/submit-score", "Submit a match result."),
        ("/addscrim", "Create a scrim channel."),
        ("/rescrim", "Reopen a scrim channel for a rematch."),
        ("/done", "Mark a match complete and lock the channel."),
        ("/roster-lock", "Lock roster changes for a team."),
        ("/roster-lock-all", "Lock roster changes for all teams."),
        ("/unlock-roster", "Unlock roster changes for a team."),
        ("/unlock-roster-all", "Unlock roster changes for all teams."),
    ]
    for name, value in fields:
        embed.add_field(name=name, value=value, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(guild=GUILD_OBJ, name="faq", description="Post FAQ and auto-role buttons.")
async def faq(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Only admins can use this.", ephemeral=True)
        return
    guild = interaction.guild
    channel = guild.get_channel(FAQ_CHANNEL_ID) if guild else None
    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        await interaction.response.send_message("FAQ channel is not configured correctly.", ephemeral=True)
        return

    text = (
        "# Competitive Tagging Association Frequently Asked Questions\n\n"
        "## • How can I make a team/How do I get it official?\n\n"
        "> **Making a team is quite easy,**\n"
        "> - Make a Discord server for your team and use recruitment-center.\n"
        "> - Getting your team official is another challenge.\n"
        "> **The first step is getting the Unborn Captain role.**\n"
        "> - We use <#1338475858532237312> to update you on team applications.\n"
        "> - Teams are normally selected at the start of a new season or during seeding.\n\n"
        "## • Moderation Support\n\n"
        "> - Open a ticket to report players or request moderation support.\n"
        "> - Tickets are not for general discussion or questions.\n\n"
        "## • Application Forms\n\n"
        "> - Applications are reviewed when positions are needed.\n"
        "> <#1361085463317971094>\n\n"
        "# Role Assign\n"
        "> 🎥 **Stream Watcher** — Live match notifications\n"
        "> 🚀 **Unborn Captain** — Apply for your team to participate\n"
        "> 🎉 **Event Ping** — Event notifications\n"
    )
    await interaction.response.defer(ephemeral=True)
    await channel.send(text, view=FAQRoleView())
    await interaction.followup.send(f"FAQ posted in {channel.mention}.", ephemeral=True)


@bot.tree.command(guild=GUILD_OBJ, name="standing", description="View league standings.")
async def standing(interaction: discord.Interaction):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("Must be used in a server.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)

    stats = {}
    for entry in load_teams():
        role_id = entry.get("role_id")
        role = guild.get_role(int(role_id)) if role_id else None
        if role:
            stats[role.name] = {"W": 0, "L": 0, "TC": 0, "PT": 0}
    if not stats:
        await interaction.followup.send("There are no teams in the system.", ephemeral=True)
        return

    score_channel = guild.get_channel(MATCH_SCORES_CHANNEL_ID)
    if not isinstance(score_channel, discord.TextChannel):
        await interaction.followup.send("Match scores channel is not configured correctly.", ephemeral=True)
        return

    async for message in score_channel.history(limit=500):
        parsed = {}
        for line in message.content.splitlines():
            cleaned = line.lstrip(">").strip()
            if ":" in cleaned:
                key, value = cleaned.split(":", 1)
                parsed[key.strip().lower()] = value.strip()

        winner = parsed.get("winner")
        loser = parsed.get("loser")
        timecap = parsed.get("timecap", "no")
        if winner not in stats or loser not in stats:
            continue
        stats[winner]["W"] += 1
        stats[loser]["L"] += 1
        if timecap.lower() != "no":
            stats[winner]["TC"] += 1

    for record in stats.values():
        record["PT"] = 3 * record["W"] + record["L"] + 3 * record["TC"]

    ordered = sorted(stats.items(), key=lambda item: (-item[1]["PT"], item[0].lower()))
    lines = ["Monke Monke Monke League SEEDING"]
    for rank, (name, record) in enumerate(ordered, start=1):
        lines.append(f"> {rank}. {name} {record['W']} W - {record['L']} L - {record['PT']} PT")
    await interaction.followup.send("\n".join(lines), ephemeral=True)


# ---------------- MATCH / SCRIM COMMANDS ----------------
@bot.tree.command(guild=GUILD_OBJ, name="submit-time", description="Propose a match time.")
@app_commands.describe(
    week="Example: WEEK 1",
    time="Eastern time as YYYY-MM-DD HH:MM, e.g. 2026-10-20 19:30",
    team1="Team 1 role",
    team2="Team 2 role",
    finals="Set True if this match is Finals",
    semi_finals="Set True if this match is Semi Finals",
)
async def submit_time(
    interaction: discord.Interaction,
    week: str,
    time: str,
    team1: discord.Role,
    team2: discord.Role,
    finals: bool = False,
    semi_finals: bool = False,
):
    if not is_staff(interaction.user):
        await interaction.response.send_message(
            "Only staff can use this.",
            ephemeral=True,
        )
        return

    if team1.id == team2.id:
        await interaction.response.send_message(
            "Choose two different teams.",
            ephemeral=True,
        )
        return

    guild = interaction.guild
    channel = interaction.channel
    if not guild or not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message(
            "Use this command in a server text channel.",
            ephemeral=True,
        )
        return

    try:
        match_at = parse_match_time(time)
    except ValueError as exc:
        await interaction.response.send_message(str(exc), ephemeral=True)
        return

    if match_at <= datetime.now(EASTERN):
        await interaction.response.send_message(
            "The match time must be in the future.",
            ephemeral=True,
        )
        return

    header = (
        "# FINALS!!"
        if finals
        else "# SEMI FINALS!"
        if semi_finals
        else ""
    )
    displayed_time = match_at.strftime("%A, %B %d, %Y at %I:%M %p ET")

    content = (
        f"{team1.mention} {team2.mention}\n"
        "Team staff must accept this match.\n\n"
        f"{header + chr(10) if header else ''}"
        f"> **{week}**\n"
        f"> Time: {displayed_time}\n"
        "> Referee: Unassigned\n"
        "> Caster: Unassigned"
    )

    view = MatchAcceptView(
        bot_=bot,
        week=week,
        time_str=displayed_time,
        header=header,
        team1_id=team1.id,
        team2_id=team2.id,
        match_at=match_at,
        team1_mention=team1.mention,
        team2_mention=team2.mention,
    )

    message = await channel.send(content, view=view)
    view.accept_message_id = message.id
    view.accept_channel_id = channel.id

    await interaction.response.send_message(
        "Match posted. Waiting for both teams to accept.",
        ephemeral=True,
    )


@bot.tree.command(guild=GUILD_OBJ, name="addscrim", description="Create a scrim channel for two teams.")
@app_commands.describe(team1="First team role", team2="Second team role")
async def addscrim(
    interaction: discord.Interaction,
    team1: discord.Role,
    team2: discord.Role,
):
    if not is_staff(interaction.user):
        await interaction.response.send_message("Only administrators or managers can use this.", ephemeral=True)
        return
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
        return
    if team1.id == team2.id:
        await interaction.response.send_message("Choose two different teams.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    name = safe_channel_name(f"scrim-{team1.name}-vs-{team2.name}")
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        team1: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        team2: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
    }

    bot_member = guild.me
    if bot_member:
        overwrites[bot_member] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_channels=True,
        )

    category = guild.get_channel(SCRIM_CATEGORY_ID) if SCRIM_CATEGORY_ID else None
    if not isinstance(category, discord.CategoryChannel):
        category = None

    try:
        channel = await guild.create_text_channel(
            name=name,
            overwrites=overwrites,
            category=category,
            reason=f"Scrim created by {interaction.user}",
        )
    except discord.HTTPException as exc:
        await interaction.followup.send(f"Could not create scrim channel: {exc}", ephemeral=True)
        return

    message = (
        f"{team1.mention} vs {team2.mention}\n\n"
        "# Welcome to NC Bracket.\n"
        "> 📅 You have 1 week to schedule.\n"
        "> ⚔️ You have 9 days to play.\n"
        "> Ping a staff member when you're ready to schedule or have questions!\n\n"
        "🔥 GET YOUR MATCH SCHEDULED, BE READY TO PLAY, AND GOOD LUCK! 🔥"
    )
    await channel.send(message)
    await interaction.followup.send(f"Created {channel.mention}.", ephemeral=True)


@bot.tree.command(guild=GUILD_OBJ, name="rescrim", description="Reopen a scrim channel for a rematch.")
@app_commands.describe(team1="First team role", team2="Second team role")
async def rescrim(
    interaction: discord.Interaction,
    team1: discord.Role,
    team2: discord.Role,
):
    if not is_staff(interaction.user):
        await interaction.response.send_message("Only staff can use this.", ephemeral=True)
        return
    guild = interaction.guild
    channel = interaction.channel
    if not guild or not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message("Use this in a scrim text channel.", ephemeral=True)
        return

    overwrites = channel.overwrites
    overwrites[team1] = discord.PermissionOverwrite(
        view_channel=True,
        send_messages=True,
        read_message_history=True,
    )
    overwrites[team2] = discord.PermissionOverwrite(
        view_channel=True,
        send_messages=True,
        read_message_history=True,
    )
    try:
        await channel.edit(overwrites=overwrites)
        new_name = channel.name.removeprefix("✅").lstrip("-")
        if new_name != channel.name:
            await channel.edit(name=new_name)
    except discord.HTTPException as exc:
        await interaction.response.send_message(f"Could not reopen the channel: {exc}", ephemeral=True)
        return

    await channel.send(
        f"{team1.mention} {team2.mention}\n"
        "# REMATCH\n"
        "> Confirm your team abbreviations and Discord display names before playing."
    )
    await interaction.response.send_message("Scrim channel reopened for a rematch.", ephemeral=True)


@bot.tree.command(guild=GUILD_OBJ, name="done", description="Mark a match complete and lock its channel.")
@app_commands.describe(winner="Winning team role")
async def done(interaction: discord.Interaction, winner: discord.Role):
    if not is_staff(interaction.user):
        await interaction.response.send_message("Only staff can use this.", ephemeral=True)
        return
    guild = interaction.guild
    channel = interaction.channel
    if not guild or not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message("Use this in a scrim text channel.", ephemeral=True)
        return

    team_roles = [
        role for role in get_team_roles_from_file(guild)
        if role in channel.overwrites
    ]
    overwrites = channel.overwrites
    for role in team_roles:
        overwrites[role] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=False,
            read_message_history=True,
        )

    try:
        await channel.edit(
            overwrites=overwrites,
            name=channel.name if channel.name.startswith("✅") else f"✅-{channel.name}",
        )
    except discord.HTTPException as exc:
        await interaction.response.send_message(f"Could not lock the channel: {exc}", ephemeral=True)
        return

    await channel.send(f"# {winner.mention} WON!")
    await interaction.response.send_message("Match marked complete and channel locked.", ephemeral=True)


@bot.tree.command(guild=GUILD_OBJ, name="submit-score", description="Submit a match score.")
@app_commands.describe(
    teams_team1="First team role",
    teams_team2="Second team role",
    timecap="Timecap result, e.g. yes/no",
    winner="Winning team role",
    loser="Losing team role",
    finals="Set True if this match is Finals",
    semi_finals="Set True if this match is Semi Finals",
    score="Final score, e.g. 5-0",
)
async def submit_score(
    interaction: discord.Interaction,
    teams_team1: discord.Role,
    teams_team2: discord.Role,
    timecap: str,
    winner: discord.Role,
    loser: discord.Role,
    finals: bool = False,
    semi_finals: bool = False,
    score: str = "",
):
    if not is_staff(interaction.user):
        await interaction.response.send_message("Only staff can use this.", ephemeral=True)
        return
    guild = interaction.guild
    channel = guild.get_channel(MATCH_SCORES_CHANNEL_ID) if guild else None
    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message("Match scores channel is not configured correctly.", ephemeral=True)
        return
    if winner.id == loser.id or {winner.id, loser.id} != {teams_team1.id, teams_team2.id}:
        await interaction.response.send_message("Winner and loser must be the two selected teams.", ephemeral=True)
        return

    stage = "# FINALS\n" if finals else "# SEMI FINALS\n" if semi_finals else ""
    score_text = score.strip() or "N/A"
    content = (
        f"# {teams_team1.mention} vs {teams_team2.mention}\n"
        f"{stage}"
        f"> Winner: {winner.name}\n"
        f"> Score: {score_text}\n"
        f"> Timecap: {timecap}\n"
        f"> Loser: {loser.name}"
    )
    await channel.send(content)
    await interaction.response.send_message(f"Score submitted in {channel.mention}.", ephemeral=True)


# ---------------- READY / RUN ----------------
@bot.event
async def on_ready():
    log.info("Logged in as %s (ID: %s)", bot.user, bot.user.id if bot.user else "unknown")
    log.info("Guild commands: %s", [command.name for command in bot.tree.get_commands(guild=GUILD_OBJ)])


async def main():
    if TOKEN == "TOKEN":
        raise RuntimeError("Replace TOKEN with your Discord bot token before starting.")
    await bot.start(os.getenv("TOKEN"))


if __name__ == "__main__":
    asyncio.run(main())
