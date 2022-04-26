import discord  # development branch 2.0.0a to be able to use Views, Interactions
from discord.ext import commands
import logging
import globals

logging.basicConfig(level=logging.INFO)

# create the bot
intents = discord.Intents(messages=True, members=True, guilds=True, message_content=True)
bot = commands.Bot(command_prefix=globals.commandPrefix, intents=intents)
globals.bot = bot

import commands
import requestEntry
import db
import tokenFile


@bot.event
async def on_ready():
    print(f'{bot.user.name} connected!')
    print(f'discord.py version = {discord.__version__}')

    # populate guild variables
    globals.guild = bot.get_guild(globals.guildID)
    for _id in globals.mainChannelIDs:
        globals.mainChannels.append(bot.get_channel(_id))
    # globals.mainChannel = bot.get_channel(globals.mainChannelID)

    # populate the global event vars if bot is restarted while event is already active
    eventTitle, eventTime, eventMessageID, eventChannelID = db.get_event()
    if eventMessageID:
        globals.eventInfo = eventTitle + ' @ ' + eventTime
        globals.eventMessageID = eventMessageID
        globals.eventChannel = bot.get_channel(eventChannelID)

    # start the sql_write loop that executes sql writes every # seconds
    db.sql_write.start()

    # await bot.change_presence(activity=discord.CustomActivity(name='Managing events'))

if __name__ == "__main__":
    bot.run(tokenFile.token)
