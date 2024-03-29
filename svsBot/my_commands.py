import discord
from discord.ext import commands, tasks

import logging

from . import db, helpers, globals
from . event_interaction import EventButtonsView
from . profession_interaction import ProfessionMenuView


class Event(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # delete commands after they resolve properly
    # the error handler already deletes messages if they raise an exception
    async def cog_after_invoke(self, ctx) -> None:
        if globals.DELETE_MESSAGES and not ctx.command_failed:
            await ctx.message.delete()

        logging.info(f'USER: {ctx.author.display_name}   COMMAND: {ctx.message.content[:100]}')

    async def cog_check(self, ctx) -> bool:
        # not in guild channel
        if isinstance(ctx.channel, discord.DMChannel):
            raise commands.NoPrivateMessage()

        # not in valid event channel
        if ctx.channel.id not in globals.MAIN_CHANNEL_ID_LIST:
            channelsInGuild = filter(lambda c: c.guild == ctx.guild, self.bot.main_channels)
            channelMentions = [c.mention for c in channelsInGuild]

            if channelMentions:
                msg = 'Command restricted to channels:\n' + ', '.join(channelMentions)
            else:
                msg = 'This command is not authorized for use in this guild - likely config error.'
            raise commands.CheckFailure(msg)

        # not admin role
        if globals.ADMIN_ROLE_NAME not in [r.name for r in ctx.author.roles]:
            raise commands.MissingRole(globals.ADMIN_ROLE_NAME)

        # not in active event channel errors
        if globals.eventChannel is not None:
            # special cases for $create when there is an active event
            if ctx.command.name == 'create':
                if ctx.channel != globals.eventChannel:
                    raise commands.CheckFailure(f'An event is already active in {globals.eventChannel.mention}. Only '
                                                f'one event may be active at a time.')
                elif ctx.channel == globals.eventChannel:
                    raise commands.CheckFailure(f'An event is already active in this channel. {ctx.clean_prefix}delete '
                                                f'to delete the active event.')
            # other commands just need to be in the active event channel
            elif ctx.channel != globals.eventChannel:
                raise commands.CheckFailure(f'Must use command in {globals.eventChannel.mention}.')

        # if there is not an active event, all commands except $create should error
        elif globals.eventChannel is None and ctx.command.name != 'create':
            raise commands.CheckFailure('No active event.')

        return True

    @commands.command(help='Creates event at time (PST, 24hr format).\n'
                           'Must be used in a valid server channel when there is not an active event.\n'
                           f'Requires role \'{globals.ADMIN_ROLE_NAME}\'.\n'
                           '\u200b\n'
                           'If <title> or <description> are not one word, they must be enclosed in \"\"\n'
                           f'Example:   {globals.COMMAND_PREFIX}create 22/7/3 15 \"My Event\" \"This is an event\"\n'
                           f'\u200b\n'
                           f'Note: Discord embeds are limited to 6000 characters, which puts a limit on the number of '
                           f'people that can fit in the sign-up fields. Beyond that limit, the database will still '
                           f'track sign-ups, but they will not be reflected in the event embed.',
                      usage='<yy/mm/dd> <hh> <\"title\"> <\"description\">')
    @commands.max_concurrency(1)
    async def create(self, ctx, datestring, hour: int, title, descr):
        """
        Creates event with title and description for specified date and time in PST
        Can only be used in a valid server channel, when there is not currently an active event
        Requires ADMIN Role
        """

        # parse event information
        eventTimeFmt, timeUntilEvent = helpers.parse_event_input(datestring=datestring, hour=hour)
        title = helpers.parse_event_input(title=title)
        descr = helpers.parse_event_input(descr=descr)
        descr = '@ ' + eventTimeFmt + '\n\n' + descr

        # TODO: make sure this actually calls confirm_maybe() only once
        # start the background task to remind the "MAYBE's"
        # loop will only start if timeUntilConfirmMaybe > 2 days
        maybeLoop = await helpers.start_confirm_maybe_loop(timeUntilEvent, ctx.guild)
        self.bot.maybe_loop = maybeLoop

        # get the cmdList to be put into footer
        cmdList = [ctx.clean_prefix + cmd.name for cmd in self.get_commands()]
        cmdList.append(f'{globals.COMMAND_PREFIX}help')

        embed = helpers.build_event_embed(title, descr, cmdList)

        eventMessage = await ctx.send(embed=embed)
        view = EventButtonsView(eventMessage)
        await eventMessage.edit(embed=embed, view=view)

        # set globals to reduce DB accessing
        eventInfo = title + ' @ ' + eventTimeFmt
        globals.eventInfo = eventInfo
        globals.eventMessage = eventMessage
        globals.eventChannel = ctx.channel

        # store event data in event info database
        await db.update_event(title, eventTimeFmt, eventMessage.id, ctx.channel.id)

    @commands.command(help='Edit the existing event.\n'
                           'Must be used in the same channel as an active event.\n'
                           f'Requires role \'{globals.ADMIN_ROLE_NAME}\'.\n'
                           '\u200b\n'
                           'If <time>, must enter date and hour.\n'
                           f'Example:   {globals.COMMAND_PREFIX}edit time 22/5/6 20\n'
                           f'\u200b\n'
                           'If <title> or <description> are not one word, they must be enclosed in \"\"\n'
                           f'Example:   {globals.COMMAND_PREFIX}edit title "New Event Title"\n'
                           f'\u200b\n',
                      usage='<time/title/description> <value>'
                      )
    @commands.max_concurrency(1)
    async def edit(self, ctx, category, *vals):
        """
        Edit the existing event
        Does not change the status of current attendees
        """

        category = category.lower()
        categories = ['time', 'title', 'description']
        if category not in categories:
            raise commands.CheckFailure(f'Category must be one of "time", "title", "description".')

        if not vals:
            raise commands.CheckFailure(f'Must enter a new value for event "{category}".')

        # get the original embed values
        old_embed = globals.eventMessage.embeds[0]
        old_title = old_embed.title
        old_description = old_embed.description

        # get the cmdList to be put into footer
        cmdList = [ctx.clean_prefix + cmd.name for cmd in self.get_commands()]
        cmdList.append(f'{globals.COMMAND_PREFIX}help')

        if category == 'time':
            if len(vals) != 2:
                raise commands.CheckFailure('Category "time" requires two arguments.')

            # get the new event time
            eventTimeFmt, timeUntilEvent = helpers.parse_event_input(datestring=vals[0], hour=vals[1])

            # replace the eventTimeFmt in the embed description with the new one
            temp = old_description.split('\n\n')
            temp[0] = '@ ' + eventTimeFmt
            description = '\n\n'.join(temp)

            # create new embed
            embed = helpers.build_event_embed(old_title, description, cmdList, old_embed)

            # change the maybe_loop to new event time
            if self.bot.maybe_loop is not None:
                self.bot.maybe_loop.cancel()
            maybeLoop = await helpers.start_confirm_maybe_loop(timeUntilEvent, ctx.guild)
            self.bot.maybe_loop = maybeLoop

        elif category == 'title':
            if len(vals) != 1:
                raise commands.CheckFailure('Category "title" requires one argument.')

            # get the new event title
            title = helpers.parse_event_input(title=vals[0])

            # replace the title and create new embed
            embed = helpers.build_event_embed(title, old_description, cmdList, old_embed)

        elif category == 'description':
            if len(vals) != 1:
                raise commands.CheckFailure('Category "description" requires one argument.')

            # get the new description
            description = helpers.parse_event_input(descr=vals[0])

            # get the old eventTimeFmt and add it to the description
            temp = old_description.split('\n\n')
            old_eventTimeFmt = temp[0] + '\n\n'
            description = old_eventTimeFmt + description

            # create new embed
            embed = helpers.build_event_embed(old_title, description, cmdList, old_embed)

        else:
            return

        # replace old embed with new one
        await globals.eventMessage.edit(embed=embed)

    @commands.command(help='Closes event sign-ups and DMs the user a formatted CSV of attendees.\n'
                           'Must be used in the same channel as an active event.\n'
                           f'Requires role \'{globals.ADMIN_ROLE_NAME}\'.')
    @commands.max_concurrency(1)
    async def close(self, ctx):
        """
        Close signups and send sorted .csv of attendees to user
        Calls fxn to build the teams for the upcoming event. Should not be re-used as it consumes tokens.
        Requires ADMIN role
        """

        await helpers.delete_event(ctx.author, self.bot, intent='make_csv')

    @commands.command(help='Closes event sign-ups and resets database to prepare for new event.\n'
                           'Must be used in the same channel as an active event.\n'
                           f'Requires role \'{globals.ADMIN_ROLE_NAME}\'.')
    @commands.max_concurrency(1)
    async def delete(self, ctx):
        """
        Resets event info database to default value
        Resets everyone's status to "NO"
        Requires ADMIN role
        """
        await helpers.delete_event(ctx.author, self.bot, intent='delete')


class DM(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_after_invoke(self, ctx) -> None:
        if globals.DELETE_MESSAGES and not ctx.command_failed:
            await ctx.message.delete()

        logging.info(f'USER: {ctx.author.display_name}   COMMAND: {ctx.message.content[:100]}')

    @commands.command(help='Change or show your database entry.\n'
                           f'Example: {globals.COMMAND_PREFIX}info change\n',
                      usage='<change/show>')
    @commands.dm_only()
    async def info(self, ctx, intent: str) -> None:
        """
        $info change sends the user a ProfessionMenuView object to initiate database entry population
        $info show sends the user a db.info_embed() with their database info

        If the user is not in the database, either one will send a ProfessionMenuView object to get a first entry.
        """

        member = ctx.author
        ID = member.id

        intent = intent.lower()
        if intent not in ['change', 'show']:
            raise commands.CheckFailure(f'Argument must be either \'change\' or \'show\'.')

        entry = await db.get_entry(ID)
        if not entry:   # check if user has been registered in DB. if not, register them
            await helpers.request_entry(member)

        elif intent == "change":
            msg = await ctx.send(content="Enter information. Menu will disappear in 5 minutes.")
            view = ProfessionMenuView(msg, 'class')
            await msg.edit(view=view)

        elif intent == "show":
            embed = db.info_embed(entry)
            await ctx.send(embed=embed)

    @commands.command(help='Toggles lottery opt in/out.')
    @commands.dm_only()
    async def lottery(self, ctx) -> None:
        """
        Toggles lottery opt in/out
        """
        member = ctx.author
        ID = member.id
        entry = await db.get_entry(ID)

        if not entry:
            await helpers.request_entry(member)
        else:
            lotto = 1 - entry[db.LOTTERY_IND]
            lotto_in_out = 'in to' if lotto else 'out of'
            msg = f'You have opted ' + lotto_in_out + ' the lottery\n'
            await db.update_lotto(ID, lotto)
            await ctx.send(msg)


class Misc(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # delete commands after they resolve properly, if they were used outside of DM
    # the error handler already deletes messages if they raise an exception
    async def cog_after_invoke(self, ctx) -> None:
        if globals.DELETE_MESSAGES and not ctx.command_failed and not isinstance(ctx.channel, discord.DMChannel):
            await ctx.message.delete()

        logging.info(f'USER: {ctx.author.display_name}   COMMAND: {ctx.message.content[:100]}')

    @commands.command(help='Logs a bug with the bot.\n'
                           'Limit of 4000 characters.\n'
                           f'Example: {globals.COMMAND_PREFIX}bug Something is not working.\n',
                      usage='<description of bug>')
    @commands.dm_only()
    async def bug(self, ctx, *, arg):
        if self.bot.bug_report_channel is None:
            raise commands.CheckFailure('The bot failed to acquire the bug report channel during startup.\n'
                                        'If the bug is critical, please contact an admin.')

        title = 'Bug Report'
        descr = str(ctx.author) + ' sent the following bug report:\n'
        descr += arg

        # limit it to 4000 chars
        if len(descr) > 4096:
            raise commands.CheckFailure('Bug report too long, must stay below 4000 characters.')

        # send bug report to svsBotTestServer/bug-reports
        embed = discord.Embed(title=title, description=descr)
        await self.bot.bug_report_channel.send(embed=embed)

        # ACK the report
        await ctx.send('Bug report has been logged. Thank you.')

    @commands.command(help='Sends the user a CSV of the database.\n'
                           'Must specify if you want just event attendees, or everyone in database.\n'
                           f'Requires role \'{globals.ADMIN_ROLE_NAME}\'.\n'
                           '\u200b\n'
                           f'Example:   {globals.COMMAND_PREFIX}get_csv all\n',
                      usage='<all/attending>')
    @commands.has_role(globals.ADMIN_ROLE_NAME)
    @commands.max_concurrency(1)
    async def get_csv(self, ctx, arg):
        if arg not in ['all', 'attending']:
            raise commands.CheckFailure('Argument must be either \'all\' or \'attending\'.')

        central_guild = self.bot.get_guild(globals.GUILD_ID_1508)

        if central_guild is None:
            raise commands.CheckFailure('Failed to acquire 1508 guild.')

        csvFile = await helpers.build_csv(central_guild, status=arg.upper())

        if arg == 'all':
            msg = 'CSV of all users in the database'
        else:
            msg = f'CSV of all users that responded "YES" or "MAYBE" to {globals.eventInfo}'

        await ctx.author.send(msg, file=csvFile)

    @commands.command(help='Sends the user a CSV of all users that interacted with the event.\n'
                           f'Requires role \'{globals.ADMIN_ROLE_NAME}\'.\n')
    @commands.has_role(globals.ADMIN_ROLE_NAME)
    @commands.max_concurrency(1)
    async def get_ymn(self, ctx):
        """
        Send the user a CSV of everyone who has interacted with the event
        """
        if not globals.eventMessage:
            return

        central_guild = self.bot.get_guild(globals.GUILD_ID_1508)
        if central_guild is None:
            raise commands.CheckFailure('Failed to acquire 1508 guild.')

        msg = 'mini-CSV of all users that interacted with the event'
        csvFile = await helpers.build_ymn_csv(central_guild)
        await ctx.author.send(msg, file=csvFile)

    @commands.command(help='Sends the user a dump of the SQL database.\n'
                           f'Requires role \'{globals.ADMIN_ROLE_NAME}\'.')
    @commands.has_role(globals.ADMIN_ROLE_NAME)
    @commands.max_concurrency(1)
    async def get_db_dump(self, ctx):
        """
        Sends dump of SQL database to user
        Requires ADMIN role
        """
        dump = await db.dump_db(globals.USER_DATABASE_DUMP_NAME)
        await ctx.author.send(f"Dump of {globals.USER_DATABASE_NAME}", file=dump)

    @commands.command(help='Purge a user from the database by discord ID.\n'
                           f'Requires role \'{globals.ADMIN_ROLE_NAME}\'.\n'
                           f'Example:   {globals.COMMAND_PREFIX}purge 164196268631916544\n',
                      usage='<DISCORD_ID>')
    @commands.has_role(globals.ADMIN_ROLE_NAME)
    @commands.max_concurrency(1)
    async def purge(self, ctx, arg: int):
        """
        Purge a user from the user info database by their unique discord ID
        """
        if len(str(arg)) != 18:
            raise commands.CheckFailure(f'{arg} is not a valid discord ID. All IDs should be 18 digit integers.')

        central_guild = self.bot.get_guild(globals.GUILD_ID_1508)
        if central_guild is None:
            raise commands.CheckFailure('Failed to acquire 1508 guild.')

        member_name = await db.get_display_name_from_id(central_guild, arg)
        user_info = f'ID: {arg}'
        if member_name:
            user_info += f', Name: {member_name}'

        if not await db.get_entry(arg):
            msg = f'ERROR: Target not in {globals.USER_DATABASE_NAME}: ```{user_info}```'
            await ctx.author.send(msg)
            return

        await db.delete_user(arg)

        if await db.get_entry(arg):
            msg = f'ERROR: Failed to purge {globals.USER_DATABASE_NAME}: ```{user_info}```\n' \
                  f'Possible bug.'
            logging.error(msg.replace('`', ''))
            await ctx.author.send(msg)
            return

        msg = f'Purged from {globals.USER_DATABASE_NAME}: ```{user_info}```'
        logging.info(msg.replace('`', ''))
        await ctx.author.send(msg)
