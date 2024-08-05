import discord
from collections import defaultdict
import re
import asyncio
from datetime import datetime, timedelta

SPECIFIC_CHANNEL_ID = 1268341467466698843
NOTIFICATION_CHANNEL_ID = 1182246453964443652
ROLE_ID = 1189132183806427219
TRIGGER_CHANNEL_ID = 1268341614556876890
REACTION_EMOJI = '✅'  # Replace with the emoji you want to use for reactions

intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.members = True
intents.message_content = True

client = discord.Client(intents=intents)

mention_counts = defaultdict(int)
original_sender_counts = defaultdict(int)
processed_messages = set()  # Set to keep track of processed message IDs
trigger_messages = defaultdict(list)  # Dictionary to store messages and their timestamps
verification_enabled = False  # Global variable to track verification status
triggering_enabled = False  # Global variable to track triggering status

@client.event
async def on_ready():
    print(f'Logged in as {client.user}')

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    global verification_enabled, triggering_enabled

    if message.content.startswith('!enable_verification'):
        verification_enabled = True
        triggering_enabled = True
        await message.channel.send('Verification and triggering have been enabled.')

    elif message.content.startswith('!disable_verification'):
        verification_enabled = False
        triggering_enabled = False
        await message.channel.send('Verification and triggering have been disabled.')

    if triggering_enabled and message.channel.id == TRIGGER_CHANNEL_ID:
        trigger_messages[message.author.id].append((message.id, message.created_at))
        notification_channel = client.get_channel(NOTIFICATION_CHANNEL_ID)
        if notification_channel:
            role = message.guild.get_role(ROLE_ID)
            embed = discord.Embed(title="Notification", color=0x00ff00)
            embed.add_field(name="User", value=f"{message.author.display_name} asking for help", inline=False)
            embed.add_field(name="Message", value=message.content, inline=False)
            await rate_limited_send(notification_channel, role.mention, embed)

    if verification_enabled and message.channel.id == SPECIFIC_CHANNEL_ID:
        await check_and_react_to_trigger_messages(message)

    if message.content.startswith('!leaderboard'):
        parts = message.content.split()

        if len(parts) == 1:
            await process_mentions(message.channel, False)
        elif len(parts) == 2:
            mention = parts[1]
            user_id = int(re.findall(r'\d+', mention)[0])
            user = message.guild.get_member(user_id)
            if user:
                await process_mentions(message.channel, True, user)
            else:
                await message.channel.send('User not found.')

async def rate_limited_send(channel, content=None, embed=None):
    try:
        await channel.send(content=content, embed=embed)
    except discord.errors.HTTPException as e:
        if e.status == 429:  # Too many requests
            retry_after = e.retry_after
            print(f'Rate limited. Retrying after {retry_after} seconds.')
            await asyncio.sleep(retry_after)
            await channel.send(content=content, embed=embed)
        else:
            raise e

async def check_and_react_to_trigger_messages(message):
    for embed in message.embeds:
        if embed.type == 'rich' and embed.author and embed.author.name:
            author_name = embed.author.name
            member = discord.utils.get(message.guild.members, name=author_name)
            if member:
                user_id = member.id
                if user_id in trigger_messages:
                    for msg_id, timestamp in trigger_messages[user_id]:
                        if abs((message.created_at - timestamp).total_seconds()) <= 3600:
                            try:
                                trigger_message = await client.get_channel(TRIGGER_CHANNEL_ID).fetch_message(msg_id)
                                await trigger_message.add_reaction(REACTION_EMOJI)
                            except discord.errors.NotFound:
                                print(f'Message with ID {msg_id} not found in trigger channel.')

async def process_mentions(channel, specific_user_check=False, specific_user=None):
    global mention_counts, original_sender_counts

    mention_counts.clear()
    original_sender_counts.clear()

    channel_to_check = client.get_channel(SPECIFIC_CHANNEL_ID)
    if channel_to_check:
        await count_mentions_in_channel(channel_to_check)

        if specific_user_check and specific_user:
            mention_count = mention_counts.get(specific_user.display_name, 0)
            sender_count = original_sender_counts.get(specific_user.display_name, 0)
            await channel.send(f'{specific_user.display_name} has helped {mention_count} times and requested for help {sender_count} times.')
        else:
            sorted_mentions = sorted(mention_counts.items(), key=lambda x: x[1], reverse=True)[:10]
            sorted_senders = sorted(original_sender_counts.items(), key=lambda x: x[1], reverse=True)[:10]

            embed = discord.Embed(title="Helps Scoreboard for August", color=0x400080)

            if sorted_mentions:
                embed.add_field(
                    name="Top 10 Helpers",
                    value='\n'.join(f"{i + 1}. {user}: {count} Help Points" for i, (user, count) in enumerate(sorted_mentions)),
                    inline=False
                )

            if sorted_senders:
                embed.add_field(
                    name="Top 10 Requesters",
                    value='\n'.join(f"{i + 1}. {get_member_display_name(channel.guild, user)}: {count} times" for i, (user, count) in enumerate(sorted_senders)),
                    inline=False
                )

            try:
                await channel.send(embed=embed)
            except discord.errors.HTTPException as e:
                if e.status == 429:  # Too many requests
                    retry_after = e.retry_after
                    print(f'Rate limited. Retrying after {retry_after} seconds.')
                    await asyncio.sleep(retry_after)
                    await channel.send(embed=embed)
                else:
                    raise e

        mention_counts.clear()
        original_sender_counts.clear()
    else:
        await channel.send('Specific channel not found.')

def count_mentions_in_message(msg):
    for user in msg.mentions:
        mention_counts[user.display_name] += 1

    for embed in msg.embeds:
        if embed.type == 'rich':
            if embed.author and embed.author.name:
                original_sender = discord.utils.get(msg.guild.members, name=embed.author.name)
                if original_sender:
                    original_sender_counts[original_sender.display_name] += 1

            mentions_from_embed = extract_mentions_from_embed(embed, msg.guild)
            for user, count in mentions_from_embed.items():
                mention_counts[user] += count

async def count_mentions_in_channel(channel):
    async for msg in channel.history(limit=None):
        count_mentions_in_message(msg)

def extract_mentions_from_embed(embed, guild):
    mention_counts = defaultdict(int)
    mention_pattern = re.compile(r'<@!?(\d+)>')

    if embed.description:
        mention_counts.update(get_mentions_from_text(embed.description, guild))

    for field in embed.fields:
        mention_counts.update(get_mentions_from_text(field.value, guild))

    return mention_counts

def get_mentions_from_text(text, guild):
    mention_counts = defaultdict(int)
    mention_pattern = re.compile(r'<@!?(\d+)>')
    mentions = mention_pattern.findall(text)

    for mention in mentions:
        user = guild.get_member(int(mention))
        if user:
            mention_counts[user.display_name] += 1

    return mention_counts

def get_member_display_name(guild, name):
    member = discord.utils.get(guild.members, name=name)
    return member.display_name if member else name

client.run(TOKEN)
