import discord
from typing import Union, Optional
import aiosqlite

import logging
from json import load

from . import globals

# I wish python supported enums...
ID_IND, CLASS_IND, LEVEL_IND, UNITS_IND, MARCH_IND, ALLIANCE_IND, MMTRAPS_IND, SKINS_IND, STATUS_IND, LOTTERY_IND, INTERACTED_IND = range(11)


async def add_entry(values: Union[list, tuple]) -> None:
    """
    param [list] entry: INT, STR, INT, STR, STR, STR, STR, STR, STR, INT, INT
        # this documentation is out of date as of profession_info.json
        # gonna create a custom datatype (class) for entries anyways, so just leave it for now
    Status defaults to 0
    Lottery defaults to 1
    interacted_with_event defaults to 0
    Profession must be provided by User via calls of ProfessionMenuView()
    """
    sql = "INSERT INTO USERS (discord_ID, class, level, unit, march_size, alliance, mm_traps, skins, status, lottery, interacted_with_event) "\
          "values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    async with aiosqlite.connect(globals.USER_DATABASE_NAME) as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(sql, values)
            await conn.commit()


async def get_entry(discord_id: int) -> Optional[tuple]:
    """
    Returns entry (list) associated with unique discord ID. If no entry exists, returns None
    """
    sql = "SELECT * FROM USERS WHERE DISCORD_ID = ?"
    val = [discord_id]
    async with aiosqlite.connect(globals.USER_DATABASE_NAME) as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(sql, val)
            entry = await cursor.fetchone()

    if not entry:
        return None
    else:
        return entry


async def update_event(title: str, time: str, message_id: discord.Message.id, channel_id: discord.TextChannel.id) -> None:
    sql = "UPDATE EVENT SET TITLE = ?, TIME = ?, MESSAGE_ID = ?, CHANNEL_ID = ?"
    values = [title, time, message_id, channel_id]
    async with aiosqlite.connect(globals.EVENT_DATABASE_NAME) as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(sql, values)
            await conn.commit()


async def get_event() -> tuple[str, str, int, int]:
    sql = "SELECT * FROM EVENT"
    async with aiosqlite.connect(globals.EVENT_DATABASE_NAME) as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(sql)
            entry = await cursor.fetchone()

    return entry


def get_profession_abbreviation_dict(category: str) -> dict:
    # return a dictionary that converts long-form profession info to shortened versions
    with open(globals.PROFESSION_INFO_JSON, 'r') as f:
        obj = load(f)
    dat = obj[category]
    return dat['convert_long_to_short']


def info_embed(entry: Union[list, tuple], descr='', first_entry=False) -> discord.Embed:
    # extract values from entry
    class_, level, units, march_size, alliance, mm_traps, skins, status, lottery = entry[1:10]

    # format values for display
    # unitDict = get_profession_abbreviation_dict('units')
    # unitDictInverted = {val: key for key, val in unitDict.items()}
    # units = list(map(lambda unit: unitDictInverted[unit], units))
    # units = [unitDict[char] for char in units]
    units = units.split(', ')
    # if march_size.startswith('>'):
    #     # need to escape the ">" quote char
    #     march_size = '\\' + march_size
    traps = mm_traps.split(', ')
    skins = skins.split(', ')
    lottery = 'YES' if lottery == 1 else 'NO'

    # fields accept a string, so build a '\n'-separated string from lists
    units = '\n'.join(units)
    traps = '\n'.join(traps)
    skins = '\n'.join(skins)

    unitTitle = 'Unit' if '\n' not in units else 'Units'
    # trapsTitle = 'Trap' if '\n' not in traps else 'Traps'
    # skinsTitle = 'Skin' if '\n' not in skins else 'Skins'

    # initialize arg dictionaries to be used in field creation
    class_args = {'name': 'Class', 'value': class_}
    level_args = {'name': 'Level', 'value': level}
    unit_args = {'name': unitTitle, 'value': units}
    march_args = {'name': 'March Size', 'value': march_size}
    alliance_args = {'name': 'Alliance', 'value': alliance}
    traps_args = {'name': 'Traps', 'value': traps}
    skins_args = {'name': 'Skins', 'value': skins}
    lottery_args = {'name': 'Lottery', 'value': lottery}
    whitespace_args = {'name': '\u200b', 'value': '\u200b'}     # used to make an empty field for alignment

    if not first_entry:
        # to avoid confusion, only show the user's status if this was a successful signup.
        # first_entry status will always be "NO"
        if globals.eventChannel:
            # if there is an active event, put the event and the user's status in the description field of the embed
            descr += f'You are **{status}** for {globals.eventInfo}\n' \
                     f'[Event Message]({globals.eventMessage.jump_url})'
        else:
            descr += 'There is no event open for signups.'
    else:
        if globals.eventChannel:
            descr += f'[Event Message]({globals.eventMessage.jump_url})'
        else:
            descr += 'There is no event open for signups.'

    embed = discord.Embed(title='Database Info', description=descr, color=discord.Color.dark_red())

    # add fields to the embed for various entry parameters
    # there are a maximum of 3 fields in a row, stretched to fill a fixed width. Add whitespace fields for alignment
    # row 1: Class, Level, Unit(s)
    embed.add_field(**class_args)
    embed.add_field(**level_args)
    embed.add_field(**unit_args)

    # row 2-3: MarchSize, Alliance, Trap(s), Skin(s), Lottery
    embed.add_field(**march_args)
    embed.add_field(**alliance_args)
    count = 0
    for argDict in [traps_args, skins_args]:
        if argDict['value']:    # if traps or skins is not empty
            embed.add_field(**argDict)
            count += 1
    embed.add_field(**lottery_args)

    # add whitespace fields to align 3rd row with 2nd row, if 3rd row has skins & lottery
    # this happens if the entry has a value for both traps and skins
    if count == 2:
        embed.add_field(**whitespace_args)

    # set thumbnail image
    if globals.LOGO_URL:
        embed.set_thumbnail(url=globals.LOGO_URL)

    # DM command information
    _ = globals.COMMAND_PREFIX
    # embed.set_footer(text=f"{_}info <change/show>   |   {_}lottery   |   {_}help")
    embed.set_footer(text=f"{_}info <change/show>,   {_}lottery,   {_}help")
    embed.timestamp = discord.utils.utcnow()

    # return embed
    return embed


async def update_profession(discord_id: discord.Member.id, prof_array: list) -> None:
    """
    updates an existing database entry indexed by "discord_id" to new profession data
    """

    sql = "UPDATE USERS SET CLASS = ?, LEVEL = ?, UNIT = ?, MARCH_SIZE = ?, ALLIANCE = ?, " \
          "MM_TRAPS = ?, SKINS = ? WHERE DISCORD_ID = ?"
    values = [*prof_array, discord_id]

    async with aiosqlite.connect(globals.USER_DATABASE_NAME) as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(sql, values)
            await conn.commit()


async def update_lotto(discord_id: discord.Member.id, lotto: int) -> None:
    sql = "UPDATE USERS SET LOTTERY = ? WHERE DISCORD_ID = ?"
    values = [lotto, discord_id]

    async with aiosqlite.connect(globals.USER_DATABASE_NAME) as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(sql, values)
            await conn.commit()


async def update_status(discord_id: discord.Member.id, status: str) -> None:
    """
    Called by event_interaction.handle_interaction() to update status when a member clicks event embed button
    """
    # shouldn't need to check on event status as they can only update if there is an active event. But do it anyways
    if globals.eventMessage is None:
        logging.error('update_status called when globals.eventMessage was \'None\'')
        return

    sql = "UPDATE USERS SET STATUS = ? WHERE DISCORD_ID = ?"
    values = [status, discord_id]

    async with aiosqlite.connect(globals.USER_DATABASE_NAME) as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(sql, values)
            await conn.commit()


async def update_interacted_with_event(discord_id: discord.Member.id, intxn: int) -> None:
    sql = "UPDATE USERS SET INTERACTED_WITH_EVENT = ? WHERE DISCORD_ID = ?"
    values = [intxn, discord_id]

    async with aiosqlite.connect(globals.USER_DATABASE_NAME) as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(sql, values)
            await conn.commit()


# this one can just run immediately rather than go into write-loop
async def reset_user_event_data() -> None:
    sql = "UPDATE USERS SET STATUS = ?, INTERACTED_WITH_EVENT = ?"
    val = ["NO", 0]

    async with aiosqlite.connect(globals.USER_DATABASE_NAME) as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(sql, val)
            await conn.commit()


async def all_of_category(category: str, value: Union[str, int], guild=None, status='YES',
                          display_name=False) -> Optional[list[tuple]]:
    """
    return a list of all user tuples that satisfy a condition
    """
    # all (ID, prof) of class
    if category == "class":
        sql = "SELECT DISCORD_ID, CLASS, LEVEL, UNIT, MARCH_SIZE, ALLIANCE, MM_TRAPS, SKINS " \
              "FROM USERS WHERE "
        if status in ['YES', 'MAYBE', 'NO']:
            sql += "STATUS = ? AND CLASS = ?"
            values = [status, value]
        elif status == 'ALL':
            sql += "CLASS = ?"
            values = [value]
        else:
            logging.info(f'ERROR: status "{status}" not recognized.')
            return

    # all ID attending event who have opted in to lotto
    elif category == "lotto":
        sql = "SELECT DISCORD_ID FROM USERS WHERE STATUS = ? AND LOTTERY = ?"
        values = [status, value]

    # just used for checking maybes. Could be used for repopulating embed name fields if bot restarts.
    elif category == 'status':
        sql = "SELECT DISCORD_ID FROM USERS WHERE STATUS = ?"
        values = [value]

    elif category == 'interacted_with_event':
        sql = "SELECT DISCORD_ID, STATUS, ALLIANCE FROM USERS WHERE INTERACTED_WITH_EVENT = ?"
        values = [value]

    else:
        logging.info(f'ERROR: category "{category}" not recognized.')
        return

    async with aiosqlite.connect(globals.USER_DATABASE_NAME) as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(sql, values)
            entries = await cursor.fetchall()

    if display_name:
        if not guild:
            logging.error('Failed to provide guild object for display names.')
        display_name_entries = []
        for entry in entries:
            name = await get_display_name_from_id(guild, entry[0], require_csv_role=True)
            if not name:
                continue
            new_entry = (name, *entry[1:])
            display_name_entries.append(new_entry)
        return display_name_entries

    else:
        return entries


async def dump_db(filename: str) -> discord.File:
    with open(filename, 'w') as file:
        async with aiosqlite.connect(globals.USER_DATABASE_NAME) as conn:
            async for line in conn.iterdump():
                file.write(line + '\n')

    return discord.File(filename)


async def get_display_name_from_id(guild: discord.Guild, discord_id: discord.User.id, require_csv_role=False) -> Union[None, str]:
    """
    Get a member's display name from a guild, stripping emojis and non-ascii chars
    """
    # Get the member object from main 1508 guild to get their display name
    member = guild.get_member(discord_id)
    if member is None:
        logging.info(f'Get display name failed: discord ID {discord_id} is not a member of guild {guild}.')
        return None

    name = member.display_name

    if require_csv_role:
        if globals.CSV_ROLE_NAME not in [r.name for r in member.roles]:
            logging.info(f'User "{name} does not have role {globals.CSV_ROLE_NAME}, skipping name retrieval.')
            return None

    # encode into ascii, ignoring unknown chars, then decode back into ascii
    try:
        byteName = name.encode('ascii', 'ignore')
        name = byteName.decode('ascii').strip()
        if name == '':
            # if the user's name is entirely non-ascii characters, it will become an empty string
            logging.error(f"Discord ID {discord_id}'s name has no ascii characters.")
            return None
    except UnicodeEncodeError:
        # if the user's name cannot be encoded into ascii
        logging.error(f"Discord ID {discord_id}'s name cannot be translated to ascii.")
        return None

    return name


async def delete_user(discord_id: int) -> None:
    async with aiosqlite.connect(globals.USER_DATABASE_NAME) as conn:
        async with conn.cursor() as cursor:
            sql = "DELETE FROM USERS WHERE discord_ID = ?"
            values = [discord_id]
            await cursor.execute(sql, values)
            await conn.commit()
